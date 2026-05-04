"""
Ollama Client for Qwen2.5-Coder
"""

import json
import aiohttp
import logging
from typing import Dict, List, Optional, AsyncGenerator

from src.config import config

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self):
        self.base_url = config.ollama.host
        self.model = config.ollama.model
        self.timeout = aiohttp.ClientTimeout(total=config.ollama.timeout)

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return any(self.model in m for m in models)
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def generate_review(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        format_schema: Optional[Dict] = None
    ) -> Dict:
        """
        Call Ollama /api/chat and return parsed JSON review dict.

        Always returns a dict — never raises, never returns None.
        On any failure the dict will contain {"parsed": False, "raw_response": <str>, "error": <str>}
        so callers can handle it without crashing.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": config.ollama.temperature,
                "num_predict": config.ollama.num_predict,
                "num_ctx": config.ollama.num_ctx,
                "repeat_penalty": config.ollama.repeat_penalty,
                "top_p": config.ollama.top_p,
                "top_k": config.ollama.top_k,
                "seed": 42,
            },
        }

        if format_schema:
            payload["format"] = format_schema

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise Exception(f"Ollama HTTP {resp.status}: {error_text}")

                    raw = await resp.json()

        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            # Return a safe sentinel — do NOT re-raise so callers get a dict, not None
            return {"parsed": False, "raw_response": "", "error": str(e)}

        # ── Validate response structure ──────────────────────────────────────
        if not raw or not isinstance(raw, dict):
            logger.error(f"Ollama returned non-dict: {type(raw)} | {raw!r:.200}")
            return {"parsed": False, "raw_response": str(raw), "error": "response is not a dict"}

        message = raw.get("message")
        if not isinstance(message, dict):
            logger.error(f"Ollama response missing 'message' dict: {raw!r:.300}")
            return {"parsed": False, "raw_response": str(raw), "error": "missing message field"}

        content = message.get("content")
        if not content:
            logger.error(f"Ollama message has no 'content': {message!r:.300}")
            return {"parsed": False, "raw_response": str(message), "error": "missing content in message"}

        # ── Extract JSON from markdown fences if present ─────────────────────
        try:
            if "```json" in content:
                content = content.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in content:
                content = content.split("```", 1)[1].split("```", 1)[0]

            parsed = json.loads(content.strip())
            logger.debug(f"Ollama response parsed OK: {json.dumps(parsed)[:200]}")
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed ({e}); returning raw content")
            return {"parsed": False, "raw_response": content, "error": f"JSONDecodeError: {e}"}

    async def stream_review(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ):
        messages = [
            {"role": "system", "content": system_prompt or ""},
            {"role": "user", "content": prompt},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": config.ollama.temperature,
                "num_predict": config.ollama.num_predict,
            },
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                async for line in resp.content:
                    if line:
                        try:
                            data = json.loads(line)
                            if "message" in data:
                                yield data["message"]["content"]
                        except json.JSONDecodeError:
                            continue

    def create_review_prompt(
        self,
        diff_content: str,
        file_path: str,
        pr_context: Dict,
        language: str = "python",
    ) -> str:
        try:
            with open("prompts/system_prompt.txt", "r") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            system_prompt = "You are an expert code reviewer."

        lang_rules = ""
        lang_file = f"prompts/review_templates/{language}.md"
        try:
            with open(lang_file, "r") as f:
                lang_rules = f"\n\n## LANGUAGE SPECIFIC RULES ({language.upper()})\n{f.read()}"
        except FileNotFoundError:
            pass

        max_chars = config.ollama.context_window * 3
        if len(diff_content) > max_chars:
            diff_content = diff_content[:max_chars] + "\n... [truncated due to size] ..."

        prompt = f"""{system_prompt}

## PULL REQUEST CONTEXT
Title: {pr_context.get('title', 'N/A')}
Description: {(pr_context.get('body') or 'N/A')[:1000]}
Author: {pr_context.get('user', {}).get('login', 'unknown')}
Base Branch: {pr_context.get('base', {}).get('ref', 'main')}
Head Branch: {pr_context.get('head', {}).get('ref', 'feature')}

## FILE UNDER REVIEW
Path: {file_path}
Language: {language}

{lang_rules}

## CODE CHANGES (DIFF)
```diff
{diff_content}
```

## YOUR TASK
Analyze the code changes above and provide a structured review following the Code Review Format Specification.
Focus on:
1. Security vulnerabilities introduced by these changes
2. Logic errors or bugs in the new code
3. Performance implications
4. Maintainability concerns
5. Missing tests or error handling

Return ONLY valid JSON matching the specification format."""

        return prompt


ollama_client = OllamaClient()

"""
AI Code Reviewer - FastAPI Application
"""

import os
import logging
from typing import Optional

from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from src.config import config, ReviewMode
from src.review_engine import review_engine
from src.ollama_client import ollama_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Code Reviewer",
    description="Locally-hosted AI code review using Ollama + Qwen2.5-Coder",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    try:
        config.validate()
        logger.info(f"Starting AI Code Reviewer in {config.mode.value} mode")
        logger.info(f"Using Ollama model: {config.ollama.model}")

        healthy = await ollama_client.health_check()
        if not healthy:
            logger.warning("Ollama health check failed - reviews will fail until resolved")
        else:
            logger.info("Ollama connection established successfully")

    except Exception as e:
        logger.error(f"Startup validation failed: {e}")
        raise


# ✅ HEALTH ENDPOINT (already present)
@app.get("/health")
async def health_check():
    ollama_healthy = await ollama_client.health_check()

    return {
        "status": "healthy" if ollama_healthy else "degraded",
        "ollama_connected": ollama_healthy,
        "model": config.ollama.model,
        "mode": config.mode.value
    }


# ✅ NEW ROOT ENDPOINT (FIX ADDED HERE)
@app.get("/")
async def root():
    return {
        "service": "AI Code Reviewer",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None)
):
    body = await request.body()

    if not review_engine.github.verify_webhook(body, x_hub_signature_256 or ""):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    if x_github_event == "ping":
        return {"status": "pong"}

    if x_github_event != "pull_request":
        return {"status": "ignored", "event": x_github_event}

    action = payload.get("action")
    if action not in ["opened", "synchronize", "reopened"]:
        return {"status": "ignored", "action": action}

    pr_data = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})

    owner = repo_data.get("owner", {}).get("login")
    repo = repo_data.get("name")
    pr_number = pr_data.get("number")

    if not all([owner, repo, pr_number]):
        raise HTTPException(status_code=400, detail="Missing PR information")

    background_tasks.add_task(
        review_engine.review_pr,
        owner=owner,
        repo=repo,
        pr_number=pr_number
    )

    return {
        "status": "review_triggered",
        "pr": f"{owner}/{repo}#{pr_number}",
        "delivery_id": x_github_delivery
    }


@app.post("/review/manual")
async def manual_review(
    owner: str,
    repo: str,
    pr_number: int,
    background_tasks: BackgroundTasks,
    branch: Optional[str] = None
):
    background_tasks.add_task(
        review_engine.review_pr,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        specific_branch=branch
    )

    return {
        "status": "review_triggered",
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "branch_filter": branch
    }


@app.get("/config")
async def get_config():
    return {
        "mode": config.mode.value,
        "model": config.ollama.model,
        "auto_approve": config.github.auto_approve,
        "max_files": config.github.max_files_per_review,
        "exclude_patterns": config.github.exclude_patterns
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

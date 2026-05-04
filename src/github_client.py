"""
GitHub Client for PR Reviews
"""

import json
import hmac
import hashlib
import aiohttp
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class PRFile:
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str
    raw_url: str
    blob_url: str
    previous_filename: Optional[str] = None


@dataclass
class ReviewComment:
    path: str
    line: int
    body: str
    side: str = "RIGHT"
    start_line: Optional[int] = None
    start_side: Optional[str] = None


class GitHubClient:
    def __init__(self):
        self.token = config.github.token
        self.api_base = config.github.api_base
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Code-Reviewer/1.0"
        }
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not config.github.webhook_secret:
            logger.warning("No webhook secret configured, skipping verification")
            return True

        expected = "sha256=" + hmac.new(
            config.github.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> List[PRFile]:
        url = f"{self.api_base}/repos/{owner}/{repo}/pulls/{pr_number}/files"

        files = []
        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch PR files: {await resp.text()}")

            data = await resp.json()
            for f in data:
                if any(pattern in f["filename"] for pattern in config.github.exclude_patterns):
                    continue

                files.append(PRFile(
                    filename=f["filename"],
                    status=f["status"],
                    additions=f["additions"],
                    deletions=f["deletions"],
                    changes=f["changes"],
                    patch=f.get("patch", ""),
                    raw_url=f["raw_url"],
                    blob_url=f["blob_url"],
                    previous_filename=f.get("previous_filename")
                ))

        return files

    async def get_pr_details(self, owner: str, repo: str, pr_number: int) -> Dict:
        url = f"{self.api_base}/repos/{owner}/{repo}/pulls/{pr_number}"

        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch PR details: {await resp.text()}")

            return await resp.json()

    async def get_current_user(self) -> Dict:
        url = f"{self.api_base}/user"

        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch user: {await resp.text()}")

            return await resp.json()

    async def create_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comments: List[ReviewComment] = None,
        body: str = "",
        event: str = "COMMENT"
    ) -> Dict:
        url = f"{self.api_base}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        payload = {
            "body": body,
            "event": event,
            "comments": []
        }

        if comments:
            for comment in comments:
                c = {
                    "path": comment.path,
                    "body": comment.body,
                    "side": comment.side
                }
                
                if comment.start_line and comment.start_side:
                    c["start_line"] = comment.start_line
                    c["start_side"] = comment.start_side
                    c["line"] = comment.line
                else:
                    c["line"] = comment.line
                
                payload["comments"].append(c)

        async with self.session.post(url, json=payload) as resp:
            if resp.status not in [200, 201]:
                raise Exception(f"Failed to create review: {await resp.text()}")

            return await resp.json()

    async def update_pr_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str
    ) -> Dict:
        url = f"{self.api_base}/repos/{owner}/{repo}/statuses/{sha}"

        payload = {
            "state": state,
            "description": description,
            "context": "ai-code-reviewer"
        }

        async with self.session.post(url, json=payload) as resp:
            if resp.status not in [200, 201]:
                raise Exception(f"Failed to update status: {await resp.text()}")

            return await resp.json()

    async def add_labels(self, owner: str, repo: str, pr_number: int, labels: List[str]) -> Dict:
        url = f"{self.api_base}/repos/{owner}/{repo}/issues/{pr_number}/labels"

        payload = {"labels": labels}

        async with self.session.post(url, json=payload) as resp:
            if resp.status not in [200, 201]:
                logger.warning(f"Failed to add labels: {await resp.text()}")
                return {}

            return await resp.json()

    async def post_issue_comment(self, owner: str, repo: str, pr_number: int, body: str) -> Dict:
        url = f"{self.api_base}/repos/{owner}/{repo}/issues/{pr_number}/comments"

        payload = {"body": body}

        async with self.session.post(url, json=payload) as resp:
            if resp.status not in [200, 201]:
                raise Exception(f"Failed to post comment: {await resp.text()}")

            return await resp.json()


github_client = GitHubClient()

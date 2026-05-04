"""
AI Code Reviewer Configuration
"""

import os
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class ReviewMode(Enum):
    GITHUB_APP = "github_app"
    GITHUB_ACTION = "github_action"
    SELF_HOSTED = "self_hosted"
    CLI = "cli"


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:7b"
    temperature: float = 0.1
    max_tokens: int = 8192
    context_window: int = 32768
    timeout: int = 300
    num_ctx: int = 32768
    num_predict: int = 8192
    repeat_penalty: float = 1.1
    top_p: float = 0.9
    top_k: int = 40


@dataclass
class GitHubConfig:
    token: str = ""
    webhook_secret: Optional[str] = None
    app_id: Optional[str] = None
    private_key: Optional[str] = None
    api_base: str = "https://api.github.com"
    auto_approve: bool = False
    require_tests: bool = True
    max_files_per_review: int = 50
    max_lines_per_file: int = 500
    exclude_patterns: List[str] = None

    def __post_init__(self):
        if self.exclude_patterns is None:
            self.exclude_patterns = [
                "*.lock", "package-lock.json", "yarn.lock",
                "*.min.js", "*.min.css", "dist/", "build/",
                "vendor/", "node_modules/", ".gitignore"
            ]


@dataclass
class ReviewConfig:
    min_confidence_for_comment: float = 0.7
    min_confidence_for_approval: float = 0.9
    max_chunk_size: int = 15000
    max_concurrent_reviews: int = 3
    enable_security_scan: bool = True
    enable_performance_check: bool = True
    enable_style_check: bool = False
    custom_rules_path: Optional[str] = None


class Config:
    def __init__(self):
        self.mode = ReviewMode(os.getenv("REVIEW_MODE", "self_hosted"))
        self.ollama = OllamaConfig(
            host=os.getenv("OLLAMA_HOST", "http://ollama:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            temperature=float(os.getenv("TEMPERATURE", "0.1")),
        )
        self.github = GitHubConfig(
            token=os.getenv("GITHUB_TOKEN", ""),
            webhook_secret=os.getenv("WEBHOOK_SECRET"),
            app_id=os.getenv("GITHUB_APP_ID"),
            private_key=os.getenv("GITHUB_PRIVATE_KEY"),
            auto_approve=os.getenv("AUTO_APPROVE", "false").lower() == "true",
        )
        self.review = ReviewConfig()

    def validate(self) -> bool:
        if not self.github.token:
            raise ValueError("GITHUB_TOKEN is required")
        if self.mode == ReviewMode.GITHUB_APP and not all([
            self.github.app_id, self.github.private_key
        ]):
            raise ValueError("GitHub App mode requires APP_ID and PRIVATE_KEY")
        return True


config = Config()

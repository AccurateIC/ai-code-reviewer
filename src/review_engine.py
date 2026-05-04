"""
Review Engine
Orchestrates the complete review workflow
"""

import json
import logging
import re
import traceback
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio

from src.config import config
from src.ollama_client import ollama_client
from src.github_client import github_client, ReviewComment
from src.diff_parser import diff_parser

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    file_path: str
    chunks_reviewed: int
    issues_found: List[Dict]
    summary: str
    confidence: float


class ReviewEngine:
    def __init__(self):
        self.ollama = ollama_client
        self.github = github_client
        self.diff = diff_parser

    # ──────────────────────────────────────────────────────────────────────────
    # Diff line validator
    # ──────────────────────────────────────────────────────────────────────────

    def _get_valid_diff_lines(self, patch: str) -> set:
        """
        Return the set of line numbers present on the RIGHT (new-file) side
        of the diff — i.e. the only lines GitHub will accept for inline review
        comments.

        Hunk header format:  @@ -old_start[,old_count] +new_start[,new_count] @@
        - Lines starting with ' ' (context) and '+' (added) increment new_line.
        - Lines starting with '-' (removed) do NOT appear in the new file.
        """
        valid: set = set()
        if not patch:
            return valid

        current_line = 0
        for raw_line in patch.splitlines():
            if raw_line.startswith("@@"):
                m = re.search(r"\+(\d+)(?:,\d+)?", raw_line)
                if m:
                    current_line = int(m.group(1))
                continue

            if raw_line.startswith("-"):
                # Deleted line — only on LEFT side, skip
                continue

            # Context line (' ') or added line ('+') — both appear on RIGHT side
            valid.add(current_line)
            current_line += 1

        return valid

    # ──────────────────────────────────────────────────────────────────────────
    # Main PR review entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def review_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        specific_branch: Optional[str] = None,
    ) -> Dict:
        async with self.github:
            pr_details = await self.github.get_pr_details(owner, repo, pr_number)
            current_user = await self.github.get_current_user()

            pr_author = pr_details["user"]["login"]
            bot_user  = current_user["login"]

            logger.info(f"PR Author: {pr_author}, Bot User: {bot_user}")

            if specific_branch and pr_details["head"]["ref"] != specific_branch:
                logger.info(f"Skipping PR {pr_number}: branch mismatch")
                return {"skipped": True, "reason": "branch_mismatch"}

            await self.github.update_pr_status(
                owner, repo, pr_details["head"]["sha"],
                "pending", "AI code review in progress...",
            )

            files = await self.github.get_pr_files(owner, repo, pr_number)

            if not files:
                await self.github.update_pr_status(
                    owner, repo, pr_details["head"]["sha"],
                    "success", "No files to review",
                )
                return {"status": "no_files"}

            all_comments:     List[ReviewComment] = []
            all_issues:       List[Dict]          = []
            review_summaries: List[str]           = []

            for file in files[: config.github.max_files_per_review]:
                try:
                    result = await self._review_file(file, pr_details)
                    all_issues.extend(result.issues_found)
                    review_summaries.append(f"**{file.filename}**: {result.summary}")

                    # FIX 1 — only include inline comments on lines that are
                    #          actually present in this file's diff hunk.
                    valid_lines = (
                        self._get_valid_diff_lines(file.patch)
                        if file.patch else set()
                    )
                    logger.debug(
                        f"{file.filename}: valid diff lines = {sorted(valid_lines)[:20]}"
                    )

                    for issue in result.issues_found:
                        if issue.get("severity") in ["CRITICAL", "HIGH"]:
                            line = issue.get("line", 1)
                            if line in valid_lines:
                                comment = ReviewComment(
                                    path=file.filename,
                                    line=line,
                                    body=self._format_issue_comment(issue),
                                    side="RIGHT",
                                )
                                all_comments.append(comment)
                            else:
                                logger.warning(
                                    f"Dropping inline comment for {file.filename}:{line} "
                                    f"— not in diff. Issue will appear in review body only. "
                                    f"(sample valid lines: {sorted(valid_lines)[:10]})"
                                )

                except Exception as e:
                    logger.error(f"Failed to review {file.filename}: {e}")
                    logger.error(traceback.format_exc())
                    review_summaries.append(
                        f"**{file.filename}**: ⚠️ Review failed - {str(e)}"
                    )

            verdict = self._determine_verdict(all_issues)
            logger.info(f"Initial verdict: {verdict}")

            # GitHub forbids APPROVE / REQUEST_CHANGES on your own PR
            if pr_author == bot_user and verdict["action"] in ("APPROVE", "REQUEST_CHANGES"):
                logger.info(
                    f"Changing {verdict['action']} to COMMENT for own PR (author: {pr_author})"
                )
                verdict["reason"] = f"{verdict['reason']} (own PR — downgraded to COMMENT)"
                verdict["action"] = "COMMENT"

            logger.info(f"Final verdict: {verdict}")

            review_body = self._format_review_body(
                verdict, all_issues, review_summaries, pr_details
            )

            try:
                # FIX 2 — re-fetch the latest head SHA immediately before
                #          submitting so we don't pass a stale SHA if the
                #          author pushed another commit while we were reviewing.
                fresh_pr  = await self.github.get_pr_details(owner, repo, pr_number)
                fresh_sha = fresh_pr["head"]["sha"]
                logger.info(
                    f"Using fresh SHA {fresh_sha} "
                    f"(original: {pr_details['head']['sha']})"
                )

                review = await self.github.create_review(
                    owner, repo, pr_number,
                    comments=all_comments,
                    body=review_body,
                    event=verdict["action"],
                )

                labels = self._generate_labels(all_issues)
                if labels:
                    await self.github.add_labels(owner, repo, pr_number, labels)

                # Use the FINAL verdict action (after own-PR downgrade) to decide
                # the commit status.  COMMENT is informational — never a blocker.
                status_state = {
                    "APPROVE":         "success",
                    "COMMENT":         "success",
                    "REQUEST_CHANGES": "failure",
                }.get(verdict["action"], "success")
                await self.github.update_pr_status(
                    owner, repo, fresh_sha,
                    status_state, verdict["reason"],
                )

                return {
                    "status": "completed",
                    "verdict": verdict,
                    "issues_count": len(all_issues),
                    "review_id": review["id"],
                }

            except Exception as e:
                logger.error(f"Failed to submit review: {e}")
                logger.error(traceback.format_exc())

                # FIX 3 — if the 422 slipped through (e.g. race condition pushed
                #          a new commit mid-review), retry without any inline
                #          comments so the review body is never lost.
                if "422" in str(e) and all_comments:
                    logger.warning(
                        "422 on review with inline comments — retrying as body-only"
                    )
                    try:
                        body_only_note = (
                            "\n\n> ⚠️ **Note:** Inline comments were omitted because "
                            "one or more line numbers could not be resolved against "
                            "the current diff (GitHub 422). All findings are listed above."
                        )
                        review = await self.github.create_review(
                            owner, repo, pr_number,
                            comments=[],
                            body=review_body + body_only_note,
                            event=verdict["action"],
                        )
                        return {
                            "status": "completed_body_only",
                            "verdict": verdict,
                            "issues_count": len(all_issues),
                            "review_id": review["id"],
                        }
                    except Exception as retry_err:
                        logger.error(f"Body-only retry also failed: {retry_err}")

                # Last-resort fallback: plain issue comment
                await self.github.post_issue_comment(
                    owner, repo, pr_number,
                    f"## AI Code Review (Error)\n\nFailed to create formal review: {str(e)}",
                )
                raise

    # ──────────────────────────────────────────────────────────────────────────
    # Per-file review
    # ──────────────────────────────────────────────────────────────────────────

    async def _review_file(self, file, pr_details: Dict) -> ReviewResult:
        if not file.patch:
            return ReviewResult(
                file_path=file.filename,
                chunks_reviewed=0,
                issues_found=[],
                summary="No diff available (binary or large file)",
                confidence=1.0,
            )

        chunks     = self.diff.chunk_large_diff(file.filename, file.patch)
        all_issues: List[Dict] = []
        chunk_summaries: List[str] = []

        for chunk in chunks:
            result = None  # ensure always defined before try block
            try:
                prompt = self.ollama.create_review_prompt(
                    diff_content=chunk.content,
                    file_path=chunk.file_path,
                    pr_context=pr_details,
                    language=chunk.language,
                )

                try:
                    with open("prompts/code_review_format.md", "r") as f:
                        system_prompt = f.read()
                except FileNotFoundError:
                    system_prompt = "You are an expert code reviewer."

                result = await self.ollama.generate_review(
                    prompt=prompt,
                    system_prompt=system_prompt,
                )

                if result is None:
                    logger.error(
                        f"generate_review returned None for chunk {chunk.chunk_id} "
                        f"(file: {file.filename}) — skipping"
                    )
                    chunk_summaries.append("AI returned None response")
                    continue

                if not isinstance(result, dict):
                    logger.error(
                        f"generate_review returned {type(result)} for chunk {chunk.chunk_id}: "
                        f"{result!r:.200}"
                    )
                    chunk_summaries.append("Invalid AI response type")
                    continue

                logger.info(f"Ollama response for {chunk.chunk_id}: {json.dumps(result)[:300]}")

                if result.get("parsed") is False:
                    error_detail = result.get("error", "unknown")
                    raw_preview  = result.get("raw_response", "")[:200]
                    logger.error(
                        f"Unparseable response for chunk {chunk.chunk_id} "
                        f"(error: {error_detail}) | raw: {raw_preview}"
                    )
                    chunk_summaries.append(f"AI response not parseable: {error_detail}")
                    continue

                categories = result.get("categories", {})

                if categories:
                    for severity in ["critical_issues", "important_issues", "suggestions"]:
                        issues = categories.get(severity, [])
                        if not isinstance(issues, list):
                            continue
                        for issue in issues:
                            if not isinstance(issue, dict):
                                continue
                            issue["file"]     = file.filename
                            issue["chunk_id"] = chunk.chunk_id
                            all_issues.append(issue)

                    chunk_summaries.append(
                        result.get("summary", {}).get("overall_assessment", "Reviewed")
                    )
                else:
                    chunk_summaries.append("No issues found")

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Chunk review failed for {chunk.chunk_id}: {e}")
                logger.error(traceback.format_exc())
                if result is not None:
                    logger.error(f"Result at time of failure: {str(result)[:200]}")
                chunk_summaries.append(f"Error reviewing chunk: {str(e)}")

        return ReviewResult(
            file_path=file.filename,
            chunks_reviewed=len(chunks),
            issues_found=all_issues,
            summary=f"Found {len(all_issues)} issues across {len(chunks)} chunks",
            confidence=0.8 if all_issues else 0.95,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Verdict logic
    # ──────────────────────────────────────────────────────────────────────────

    def _determine_verdict(self, issues: List[Dict]) -> Dict:
        critical = sum(1 for i in issues if i.get("severity") == "CRITICAL")
        high     = sum(1 for i in issues if i.get("severity") == "HIGH")
        medium   = sum(1 for i in issues if i.get("severity") == "MEDIUM")
        low      = sum(1 for i in issues if i.get("severity") == "LOW")
        total    = critical + high + medium + low

        if critical > 0:
            return {
                "action": "REQUEST_CHANGES",
                "reason": f"Found {critical} critical issues",
                "confidence": 0.95,
            }

        if high >= 2:
            return {
                "action": "REQUEST_CHANGES" if not config.github.auto_approve else "COMMENT",
                "reason": f"Found {high} high-severity issues",
                "confidence": 0.85,
            }

        if medium > 5:
            return {
                "action": "COMMENT",
                "reason": f"Found {medium} medium issues",
                "confidence": 0.75,
            }

        reason = "Code looks good" if total == 0 else f"Found {total} issue(s) — no blockers"
        return {
            "action": "APPROVE" if config.github.auto_approve else "COMMENT",
            "reason": reason,
            "confidence": 0.9 if total == 0 else 0.75,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Comment / review body formatters
    # ──────────────────────────────────────────────────────────────────────────

    def _format_issue_comment(self, issue: Dict) -> str:
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH":     "🟠",
            "MEDIUM":   "🟡",
            "LOW":      "🔵",
        }.get(issue.get("severity"), "⚪")

        severity       = issue.get("severity", "MEDIUM")
        category       = issue.get("category", "")
        title          = issue.get("title", "Issue")
        description    = issue.get("description", "")
        current_code   = issue.get("current_code", "")
        suggested_fix  = issue.get("suggested_fix", "")
        impact         = issue.get("impact", "")
        fix_complexity = issue.get("fix_complexity", "EASY")
        cwe_id         = issue.get("cwe_id", "")
        line_num       = issue.get("line", "?")
        file_name      = issue.get("file", "this file")

        recommendations = {
            "SECURITY": (
                "Ensure this fix is applied consistently across the codebase. "
                "Run a security scan (`npm audit` / `bandit` / `trivy`) after patching."
            ),
            "ERROR_HANDLING": (
                "Avoid broad `except` or empty catch blocks. "
                "Always log the exception with context so failures are traceable in production."
            ),
            "PERFORMANCE": (
                "Benchmark before and after. If this is in a hot path, "
                "consider profiling the full function to catch related bottlenecks."
            ),
            "MAINTAINABILITY": (
                "Apply the refactor and check for duplicate patterns in the same module. "
                "Consistent code makes future changes faster and safer."
            ),
            "TESTING": (
                "Uncovered edge cases become production bugs. "
                "Add the test, run coverage, and confirm the gap is closed before merging."
            ),
            "DOCUMENTATION": (
                "Clear docs reduce onboarding time and prevent misuse of APIs. "
                "Even a one-line docstring is better than none."
            ),
        }
        recommendation = recommendations.get(
            category,
            "Review the flagged pattern carefully and apply the fix consistently across the codebase.",
        )

        if category == "SECURITY":
            snippet = (current_code or title)[:40]
            steps = [
                f"1. **Locate** — Find all occurrences: `grep -rn \"{snippet}\" .`",
                "2. **Fix** — Apply the suggested fix shown above",
                "3. **Audit** — Scan the rest of the codebase for the same pattern",
                "4. **Test** — Verify with security tests or manual endpoint testing",
                "5. **Confirm** — Ensure no sensitive data leaks in logs or API responses",
            ]
        elif category == "ERROR_HANDLING":
            steps = [
                f"1. **Locate** — Find the broad exception at line `{line_num}` in `{file_name}`",
                "2. **Identify** — List all specific exceptions this block should catch",
                "3. **Fix** — Replace with typed exceptions as shown in the suggested fix",
                "4. **Log** — Add structured logging with error context inside the catch",
                "5. **Test** — Simulate the failure to confirm it is handled correctly",
            ]
        elif category == "PERFORMANCE":
            steps = [
                "1. **Baseline** — Measure execution time before making changes",
                "2. **Fix** — Apply the suggested fix shown above",
                "3. **Benchmark** — Re-measure and confirm the improvement",
                "4. **Scan** — Look for the same pattern elsewhere in the file",
                "5. **Load test** — Validate under realistic data volumes",
            ]
        elif category == "MAINTAINABILITY":
            steps = [
                "1. **Understand** — Read the current code and suggested fix carefully",
                "2. **Refactor** — Apply the suggested change",
                "3. **Test** — Run the full test suite to ensure nothing breaks",
                "4. **Document** — Add a brief comment if the logic is non-obvious",
                "5. **Scan** — Check if the same pattern exists elsewhere in the module",
            ]
        elif category == "TESTING":
            steps = [
                "1. **Identify** — Determine the untested scenario or edge case",
                "2. **Write** — Add the test case using the suggested fix as a guide",
                "3. **Run** — Execute: `pytest` / `npm test` / equivalent",
                "4. **Coverage** — Confirm the gap is closed in the coverage report",
                "5. **CI** — Verify all tests pass in the pipeline before merging",
            ]
        elif category == "DOCUMENTATION":
            steps = [
                "1. **Docstring** — Add function/class docs with params and return type",
                "2. **Inline** — Comment any non-obvious logic inline",
                "3. **API docs** — Update OpenAPI/Swagger if this is an endpoint change",
                "4. **Changelog** — Add an entry if the change is user-facing",
            ]
        else:
            fix_instruction = (
                "Apply the suggested fix shown above" if suggested_fix
                else "Rewrite based on the description"
            )
            steps = [
                f"1. **Locate** — Find the flagged code at line `{line_num}` in `{file_name}`",
                f"2. **Fix** — {fix_instruction}",
                "3. **Search** — Run `grep -rn` to check for the same issue elsewhere",
                "4. **Test** — Run the full test suite to confirm nothing is broken",
                f"5. **Commit** — `fix: resolve {title.lower()}`",
            ]

        L = []
        L.append(f"### {severity_emoji} {title}")
        L.append("")
        L.append(description)
        L.append("")

        if current_code:
            L.append("**Current code:**")
            L.append("```")
            L.append(current_code)
            L.append("```")
            L.append("")

        if suggested_fix:
            L.append("**✅ Suggested fix:**")
            L.append("```")
            L.append(suggested_fix)
            L.append("```")
            L.append("")

        L.append("**⚠️ Recommendation**")
        L.append(recommendation)
        L.append("")

        L.append("**🛠️ Steps to resolve:**")
        for step in steps:
            L.append(step)
        L.append("")

        L.append("**📊 Impact**")
        severity_label = severity.capitalize()
        effort_label   = fix_complexity.capitalize() if fix_complexity else "Easy"
        L.append(f"- **Severity:** {severity_emoji} {severity_label}")
        L.append(f"- **Reason:** {impact if impact else description}")
        L.append(f"- **Effort:** {effort_label} fix")
        if cwe_id:
            cwe_num = cwe_id.replace("CWE-", "")
            L.append(
                f"- **Reference:** [{cwe_id}]"
                f"(https://cwe.mitre.org/data/definitions/{cwe_num}.html)"
            )
        L.append("")

        L.append("**👍 Summary**")
        if suggested_fix:
            L.append(
                f"Apply the fix above to resolve this "
                f"`{category.lower().replace('_', ' ')}` issue and keep the codebase healthy."
            )
        else:
            L.append(
                f"Review and address this "
                f"`{category.lower().replace('_', ' ')}` issue before merging."
            )

        return "\n".join(L)

    def _format_review_body(self, verdict, issues, summaries, pr_details):
        verdict_emoji = {
            "APPROVE":         "✅",
            "REQUEST_CHANGES": "❌",
            "COMMENT":         "💬",
        }.get(verdict["action"], "💬")

        critical = sum(1 for i in issues if i.get("severity") == "CRITICAL")
        high     = sum(1 for i in issues if i.get("severity") == "HIGH")
        medium   = sum(1 for i in issues if i.get("severity") == "MEDIUM")
        low      = sum(1 for i in issues if i.get("severity") == "LOW")

        lines = [
            f"## {verdict_emoji} AI Code Review",
            f"> **Verdict:** `{verdict['action']}` — {verdict['reason']}",
            "",
            "### 📊 Summary",
            "| Severity | Count |",
            "|----------|-------|",
        ]
        if critical: lines.append(f"| 🔴 Critical | {critical} |")
        if high:     lines.append(f"| 🟠 High     | {high} |")
        if medium:   lines.append(f"| 🟡 Medium   | {medium} |")
        if low:      lines.append(f"| 🔵 Low      | {low} |")
        if not issues:
            lines.append("| ✅ None     | 0 |")

        if summaries:
            lines.append("")
            lines.append("### 📁 Files Reviewed")
            for s in summaries:
                lines.append(f"- {s}")

        must_fix = [
            i.get("title", "?")
            for i in issues
            if i.get("severity") in ("CRITICAL", "HIGH")
        ]
        if must_fix:
            lines.append("")
            lines.append("### 🚨 Must Fix Before Merge")
            for t in must_fix:
                lines.append(f"- {t}")

        lines += [
            "",
            "---",
            "*🤖 Reviewed by local Qwen2.5-Coder via Ollama*",
        ]

        return "\n".join(lines)

    def _generate_labels(self, issues: List[Dict]) -> List[str]:
        labels = []
        if any(i.get("category") == "SECURITY" for i in issues):
            labels.append("security-issue")
        if any(i.get("severity") == "CRITICAL" for i in issues):
            labels.append("critical-bug")
        if len(issues) > 10:
            labels.append("needs-refactoring")
        return labels


review_engine = ReviewEngine()

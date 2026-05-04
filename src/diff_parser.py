"""
Diff Parser and Chunker
"""

import re
import hashlib
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from src.config import config


@dataclass
class DiffChunk:
    file_path: str
    content: str
    start_line: int
    end_line: int
    change_type: str
    language: str
    chunk_id: str

    def estimate_tokens(self) -> int:
        return len(self.content) // 4


@dataclass
class DiffHunk:
    header: str
    lines: List[str]
    old_start: int
    old_count: int
    new_start: int
    new_count: int


class DiffParser:
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.go': 'go',
        '.rs': 'rust',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.r': 'r',
        '.sql': 'sql',
        '.sh': 'bash',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.json': 'json',
        '.xml': 'xml',
        '.md': 'markdown',
        '.dockerfile': 'dockerfile',
        '.tf': 'terraform',
        '.hcl': 'terraform',
    }

    @classmethod
    def detect_language(cls, filename: str) -> str:
        lower = filename.lower()
        if 'dockerfile' in lower:
            return 'dockerfile'

        for ext, lang in cls.LANGUAGE_MAP.items():
            if lower.endswith(ext):
                return lang

        return 'unknown'

    @classmethod
    def parse_patch(cls, file_path: str, patch: str) -> List[DiffHunk]:
        if not patch:
            return []

        hunks = []
        lines = patch.split('\n')
        current_hunk = None
        hunk_lines = []

        for line in lines:
            if line.startswith('@@'):
                if current_hunk:
                    current_hunk.lines = hunk_lines
                    hunks.append(current_hunk)

                match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if match:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1

                    current_hunk = DiffHunk(
                        header=line,
                        lines=[],
                        old_start=old_start,
                        old_count=old_count,
                        new_start=new_start,
                        new_count=new_count
                    )
                    hunk_lines = []

            elif current_hunk is not None:
                hunk_lines.append(line)

        if current_hunk:
            current_hunk.lines = hunk_lines
            hunks.append(current_hunk)

        return hunks

    @classmethod
    def chunk_large_diff(
        cls,
        file_path: str,
        patch: str,
        max_chunk_tokens: int = 6000
    ) -> List[DiffChunk]:
        language = cls.detect_language(file_path)
        hunks = cls.parse_patch(file_path, patch)

        chunks = []
        current_chunk_lines = []
        current_start = 0
        current_tokens = 0

        for hunk in hunks:
            hunk_text = '\n'.join([hunk.header] + hunk.lines)
            hunk_tokens = len(hunk_text) // 4

            if hunk_tokens > max_chunk_tokens:
                lines = hunk.lines
                sub_chunks = []
                current_sub = []
                current_sub_tokens = 0

                for line in lines:
                    line_tokens = len(line) // 4
                    if current_sub_tokens + line_tokens > max_chunk_tokens and current_sub:
                        sub_chunks.append(current_sub)
                        current_sub = [line]
                        current_sub_tokens = line_tokens
                    else:
                        current_sub.append(line)
                        current_sub_tokens += line_tokens

                if current_sub:
                    sub_chunks.append(current_sub)

                for i, sub in enumerate(sub_chunks):
                    content = hunk.header + '\n' + '\n'.join(sub)
                    chunk_id = hashlib.md5(f"{file_path}:{hunk.new_start}:{i}".encode()).hexdigest()[:8]

                    chunks.append(DiffChunk(
                        file_path=file_path,
                        content=content,
                        start_line=hunk.new_start,
                        end_line=hunk.new_start + len(sub),
                        change_type="modified",
                        language=language,
                        chunk_id=chunk_id
                    ))

            elif current_tokens + hunk_tokens > max_chunk_tokens and current_chunk_lines:
                content = '\n'.join(current_chunk_lines)
                chunk_id = hashlib.md5(f"{file_path}:{current_start}".encode()).hexdigest()[:8]

                chunks.append(DiffChunk(
                    file_path=file_path,
                    content=content,
                    start_line=current_start,
                    end_line=hunk.new_start + hunk.new_count,
                    change_type="modified",
                    language=language,
                    chunk_id=chunk_id
                ))

                current_chunk_lines = [hunk.header] + hunk.lines
                current_start = hunk.new_start
                current_tokens = hunk_tokens

            else:
                if not current_chunk_lines:
                    current_start = hunk.new_start
                current_chunk_lines.extend([hunk.header] + hunk.lines)
                current_tokens += hunk_tokens

        if current_chunk_lines:
            content = '\n'.join(current_chunk_lines)
            chunk_id = hashlib.md5(f"{file_path}:{current_start}".encode()).hexdigest()[:8]

            chunks.append(DiffChunk(
                file_path=file_path,
                content=content,
                start_line=current_start,
                end_line=current_start + len(current_chunk_lines),
                change_type="modified",
                language=language,
                chunk_id=chunk_id
            ))

        return chunks

    @classmethod
    def extract_changed_lines(cls, patch: str) -> List[Tuple[int, str, str]]:
        hunks = cls.parse_patch("temp", patch)
        changes = []

        for hunk in hunks:
            line_num = hunk.new_start
            for line in hunk.lines:
                if line.startswith('+'):
                    changes.append((line_num, 'addition', line[1:]))
                    line_num += 1
                elif line.startswith('-'):
                    changes.append((line_num, 'deletion', line[1:]))
                elif line.startswith(' '):
                    line_num += 1

        return changes


diff_parser = DiffParser()

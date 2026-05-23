# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Recall Tool — Fetch original document content by memory_id.

This is the second level of the two-level memory system.
The first level (search) returns summaries with memory_id references.
When more detail is needed, the model calls recall to fetch the full text.
"""

import re
import sqlite3
from pathlib import Path

from knowledge.config import KNOWLEDGE_ROOT, VECTOR_DB_PATH, RAW_MEMORIES_DIR, RAW_TOOLS_DIR, RAW_SKILLS_DIR

# Path conventions for resolving memory_id to file paths without DB lookup
TYPE_TO_DIR = {
    "conv": "raw_memories",
    "tool": "raw_tools",
    "skill": "raw_skills",
}

# File to read for tool/skill types — raw_* has flat .md files
TYPE_TO_FILE = {
    "tool": None,   # raw_tools/{name}.md
    "skill": None,  # raw_skills/{name}.md
}

MAX_RETURN_CHARS = 8000


def _resolve_path(memory_id: str) -> Path | None:
    """Resolve a memory_id to a file path under KNOWLEDGE_ROOT.

    memory_id formats:
      conv:20260115-143022-a1b2c3  →  knowledge/memories/20260115-143022-a1b2c3.md
      tool:read                    →  knowledge/tools/read/README.md
      skill:idea-to-code-sculpting →  knowledge/skills/idea-to-code-sculpting.md
    """
    if ":" not in memory_id:
        return None

    prefix, name = memory_id.split(":", 1)
    if prefix not in TYPE_TO_DIR:
        return None

    subdir = TYPE_TO_DIR[prefix]
    if prefix == "conv":
        # name is the timestamp-hash, e.g. "20260115-143022-a1b2c3"
        path = KNOWLEDGE_ROOT / subdir / f"{name}.md"
    elif prefix == "tool":
        path = KNOWLEDGE_ROOT / subdir / f"{name}.md"
    elif prefix == "skill":
        path = KNOWLEDGE_ROOT / subdir / f"{name}.md"
    else:
        return None

    if path.exists():
        return path
    return None


def _resolve_from_db(memory_id: str) -> Path | None:
    """Fallback: look up source_file or source from vectors table."""
    conn = sqlite3.connect(VECTOR_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT source FROM vectors WHERE memory_id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            source = row[0]
            # source may be "file:tools/read/README.md" or "memories/xxx.md"
            if source.startswith("file:"):
                source = source[5:]
            path = KNOWLEDGE_ROOT / source
            if path.exists():
                return path

        # Also try matching conv type by source
        if memory_id.startswith("conv:"):
            conv_name = memory_id[5:]
            cursor.execute(
                "SELECT source FROM vectors WHERE type LIKE 'conversation%' AND source LIKE ?",
                (f"%{conv_name}%",),
            )
            row = cursor.fetchone()
            if row and row[0]:
                source = row[0]
                if source.startswith("file:"):
                    source = source[5:]
                path = KNOWLEDGE_ROOT / source
                if path.exists():
                    return path
    finally:
        conn.close()
    return None


def _search_within(text: str, query: str) -> str:
    """Find the most relevant paragraph for query and return its context."""
    paragraphs = text.split("\n\n")
    if len(paragraphs) <= 1:
        return text[:MAX_RETURN_CHARS]

    query_lower = query.lower()
    best_idx = 0
    best_score = 0
    for i, para in enumerate(paragraphs):
        score = para.lower().count(query_lower)
        if score > best_score:
            best_score = score
            best_idx = i

    # Return the best paragraph with one paragraph of context on each side
    start = max(0, best_idx - 1)
    end = min(len(paragraphs), best_idx + 2)
    result = "\n\n".join(paragraphs[start:end])
    if len(result) > MAX_RETURN_CHARS:
        result = result[:MAX_RETURN_CHARS] + "\n\n[... truncated]"
    return result


def execute(memory_id: str, query: str = "", lines: str = "") -> str:
    """Fetch original document content by memory_id.

    This is the second-level retrieval tool. When the model sees a summary
    in context with a memory_id reference, it can call recall to get the
    full original text for detailed work.

    Args:
        memory_id: Unique identifier (e.g., "conv:20260115-143022-a1b2c3",
                   "tool:read", "skill:idea-to-code-sculpting")
        query: Optional keyword to locate specific paragraphs within the document
        lines: Optional line range like "10-30" or "50" for precise retrieval

    Returns:
        The full or filtered document content with metadata header.
    """
    if not memory_id or not memory_id.strip():
        return "Error: memory_id is required. Use an ID from the context summaries (e.g., 'conv:xxx', 'tool:read', 'skill:xxx')."

    memory_id = memory_id.strip()

    # Resolve the file path
    path = _resolve_path(memory_id)
    if path is None:
        path = _resolve_from_db(memory_id)

    if path is None:
        return (
            f"Recall failed: no file found for memory_id '{memory_id}'.\n"
            f"Valid prefixes: conv:, tool:, skill:\n"
            f"Verify the ID matches a summary shown in context."
        )

    # Security: ensure path is within KNOWLEDGE_ROOT
    try:
        path.resolve().relative_to(KNOWLEDGE_ROOT.resolve())
    except ValueError:
        return f"Recall denied: path '{path}' is outside the knowledge directory."

    # Read the file
    try:
        full_text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Recall failed: cannot read {path}: {e}"

    # Apply line range filter
    if lines:
        line_nums = _parse_lines(lines, len(full_text.split("\n")))
        if isinstance(line_nums, str):
            return line_nums  # error message
        all_lines = full_text.split("\n")
        selected = all_lines[line_nums[0] - 1 : line_nums[1]]
        full_text = "\n".join(selected)

    # Apply query filter
    if query:
        full_text = _search_within(full_text, query)

    # Truncate if too long and apply metadata header
    token_estimate = len(full_text) // 4
    line_count = len(full_text.split("\n"))
    truncated = False
    if len(full_text) > MAX_RETURN_CHARS:
        full_text = full_text[:MAX_RETURN_CHARS] + "\n\n[... truncated]"
        truncated = True

    header = (
        f"## 📄 recall: {memory_id}\n"
        f"- Source: {path.relative_to(KNOWLEDGE_ROOT)}\n"
        f"- Characters: {len(full_text)} (~{token_estimate} tokens)\n"
        f"- Lines: {line_count}"
    )
    if truncated:
        header += " (truncated)"
    header += "\n\n"
    header += "---\n\n"

    return header + full_text


def _parse_lines(lines: str, total_lines: int):
    """Parse a line range string like '10-30' or '50'."""
    m = re.match(r"^(\d+)(?:-(\d+))?$", lines.strip())
    if not m:
        return f"Error: invalid lines format '{lines}'. Use 'N' or 'N-M' (e.g., '10-30')."
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if start < 1:
        start = 1
    if end > total_lines:
        end = total_lines
    if start > end:
        return f"Error: start line {start} > end line {end}."
    return (start, end)

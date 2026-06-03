# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Recall Tool — Fetch original document or crystal content by ID.

This is the second level of the two-level memory system.
The first level (search) returns summaries with memory_id/crystal_id references.
When more detail is needed, the model calls recall to fetch the full text.

Supports two ID types:
  - memory_id: conv:/tool:/skill: — resolves to files on disk
  - crystal_id: ExperienceCrystal:... — resolves from CrystalStore
"""

import re
import json
import sqlite3
from pathlib import Path

from knowledge.config import KNOWLEDGE_ROOT, VECTOR_DB_PATH, RAW_MEMORIES_DIR, RAW_TOOLS_DIR, RAW_SKILLS_DIR

# Crystal types that use reference_values for dim lookup
_DIM_CRYSTAL_TYPES = {"ExperienceCrystal"}

# Path conventions for resolving memory_id to file paths without DB lookup
TYPE_TO_DIR = {
    "conv": "raw_memories",
    "tool": "raw_tools",
    "skill": "raw_skills",
}

MAX_RETURN_CHARS = 999_999  # effectively no truncation


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


def execute(memory_id: str = "", crystal_id: str = "",
            query: str = "", lines: str = "", dim: str = "") -> str:
    """Fetch original document or crystal content by ID.

    This is the second-level retrieval tool. When the model sees a summary
    in context with a memory_id or crystal_id reference, it can call recall
    to get the full content.

    Args:
        memory_id: Unique identifier (e.g., "conv:20260115-143022-a1b2c3",
                   "tool:read", "skill:idea-to-code-sculpting")
        crystal_id: Crystal identifier (e.g., "ExperienceCrystal:proj:mod.name:v1.0").
                    When provided, fetches from CrystalStore instead of disk.
        query: Optional keyword to locate specific paragraphs within the document
        lines: Optional line range like "10-30" or "50" for precise retrieval
        dim: Optional dimension filter (e.g., "debug", "algorithm").
             For memory_id: extracts matching dimension summary from vector DB.
             For crystal_id (ExperienceCrystal): returns specific reference_value.

    Returns:
        The full or filtered content with metadata header.
    """
    mid = memory_id.strip() if memory_id else ""
    cid = crystal_id.strip() if crystal_id else ""

    if not mid and not cid:
        return (
            "Error: memory_id or crystal_id is required. "
            "Use an ID from the context summaries."
        )

    # ── crystal_id path ──
    if cid:
        return _resolve_crystal(cid, dim, query)

    # ── memory_id path (existing behavior) ──
    path = _resolve_path(mid)
    if path is None:
        path = _resolve_from_db(mid)

    if path is None:
        return (
            f"Recall failed: no file found for memory_id '{mid}'.\n"
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

    # Truncate early to limit memory on large files before further processing
    original_len = len(full_text)
    if len(full_text) > MAX_RETURN_CHARS:
        full_text = full_text[:MAX_RETURN_CHARS] + "\n\n[... truncated]"

    # Apply line range filter
    if lines:
        line_nums = _parse_lines(lines, len(full_text.split("\n")))
        if isinstance(line_nums, str):
            return line_nums
        all_lines = full_text.split("\n")
        selected = all_lines[line_nums[0] - 1 : line_nums[1]]
        full_text = "\n".join(selected)

    # Apply query filter
    if query:
        full_text = _search_within(full_text, query)

    token_estimate = len(full_text) // 4
    line_count = len(full_text.split("\n"))
    truncated = original_len > MAX_RETURN_CHARS

    header = (
        f"## 📄 recall: {mid}\n"
        f"- Source: {path.relative_to(KNOWLEDGE_ROOT)}\n"
        f"- Characters: {len(full_text)} (~{token_estimate} tokens)"
        + (f" (original: {original_len})" if truncated else "") + "\n"
        f"- Lines: {line_count}"
    )
    if truncated:
        header += " (truncated)"
    header += "\n"

    # Inject dimension info from vector DB when dim is specified
    if dim:
        dim_text = _lookup_dim(mid, dim)
        if dim_text:
            header += f"- Dimension [{dim}]: {dim_text}\n"

    header += "\n---\n\n"

    return header + full_text


def _resolve_crystal(crystal_id: str, dim: str, query: str) -> str:
    """Resolve a crystal_id from CrystalStore and format its content.

    For ExperienceCrystal with dim, returns only the matching reference_value.
    """
    from src import state

    store = state.crystal_store
    if not store:
        return "Error: CrystalStore is not initialized. Cannot resolve crystal_id."

    crystal = store.get_crystal_by_string_id(crystal_id)
    if not crystal:
        return (
            f"Recall failed: no crystal found for crystal_id '{crystal_id}'.\n"
            f"Verify the ID matches a crystal shown in context."
        )

    content = crystal.get("content", {})
    if not isinstance(content, dict):
        content = {}

    ctype = crystal.get("crystal_type", "")

    # ── Dimension-specific fetch ──
    if dim and ctype in _DIM_CRYSTAL_TYPES:
        refs = content.get("reference_values", {})
        if isinstance(refs, dict) and dim in refs and refs[dim]:
            return (
                f"## 🧠 recall: {crystal_id}\n"
                f"- Type: {ctype}\n"
                f"- Title: {content.get('title', crystal.get('name', ''))}\n"
                f"- Dimension [{dim}]\n"
                f"\n---\n\n"
                f"{refs[dim]}"
            )

    # Also support dim for conversation summaries in crystal context
    if dim and ctype not in _DIM_CRYSTAL_TYPES:
        dim_text = _lookup_dim(crystal_id, dim)
        if dim_text:
            return (
                f"## 📄 recall: {crystal_id}\n"
                f"- Type: {ctype}\n"
                f"- Dimension [{dim}]: {dim_text}\n"
                f"\n---\n\n"
                f"(Full content not available for dimension-only recall on this type. "
                f"Use recall without dim to fetch the full crystal.)"
            )

    # ── Full crystal content ──
    return _format_crystal(crystal_id, crystal, query)


def _format_crystal(crystal_id: str, crystal: dict, query: str) -> str:
    """Format a crystal's content for display."""
    content = crystal.get("content", {})
    if not isinstance(content, dict):
        content = {}

    ctype = crystal.get("crystal_type", "")

    header = (
        f"## 🧠 recall: {crystal_id}\n"
        f"- Type: {ctype}\n"
        f"- Project: {crystal.get('project_id', '')}\n"
        f"- Module: {crystal.get('module', '')}\n"
        f"- Vitality: {crystal.get('vitality', 0)}\n"
        f"\n---\n\n"
    )

    # Format content by crystal type
    if ctype == "ExperienceCrystal":
        body = _format_experience_content(content, query)
    else:
        body = _format_generic_crystal_content(content, query)

    result = header + body
    if len(result) > MAX_RETURN_CHARS:
        result = result[:MAX_RETURN_CHARS] + "\n\n[... truncated]"
    return result


def _format_experience_content(content: dict, query: str) -> str:
    """Format ExperienceCrystal content."""
    lines = [
        f"**{content.get('title', '')}**",
        f"摘要：{content.get('summary', '')}",
        "",
        f"### 问题",
        f"{content.get('problem', '')}",
        "",
        f"### 解决方案",
        f"{content.get('solution', '')}",
        "",
        "### 参考价值",
    ]

    refs = content.get("reference_values", {})
    if isinstance(refs, dict):
        for dim_label, dim_key in [
            ("架构", "architecture"), ("契约", "contract"),
            ("算法", "algorithm"), ("实现", "implementation"),
            ("调试", "debug"), ("元认知", "meta"),
        ]:
            val = refs.get(dim_key, "")
            if val and isinstance(val, str) and len(val) > 5:
                lines.append(f"- **[{dim_label}]** {val}")
                if query and query.lower() in val.lower():
                    lines[-1] = f"- **[{dim_label}]** {val}  ← 匹配关键词"

    tags = content.get("tags", [])
    if tags:
        lines.append(f"\n标签：{', '.join(tags)}")

    source = content.get("source_project", "")
    if source:
        lines.append(f"来源项目：{source}")

    return "\n".join(lines) + "\n"


def _format_generic_crystal_content(content: dict, query: str) -> str:
    """Format generic (non-Experience) crystal content."""
    lines = []
    for key, value in content.items():
        if key in ("reference_values", "tags", "source_project"):
            continue
        if isinstance(value, list):
            lines.append(f"**{key}**：")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, str) and value:
            lines.append(f"**{key}**：{value}")
        elif isinstance(value, (int, float, bool)):
            lines.append(f"**{key}**：{value}")
    return "\n".join(lines) + "\n" if lines else "(no content fields)\n"


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


def _lookup_dim(memory_id: str, dim: str) -> str:
    """Look up the matching dimension summary from the vector DB.

    Returns the dimension's summary text, or empty string if not found.
    """
    conn = sqlite3.connect(VECTOR_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT summary_json FROM vectors WHERE memory_id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            sj = json.loads(row[0])
            dimensions = sj.get("dimensions", [])
            for d in dimensions:
                if isinstance(d, dict) and d.get("dim") == dim:
                    return d.get("summary", "")
    except (json.JSONDecodeError, TypeError, sqlite3.OperationalError):
        pass
    finally:
        conn.close()
    return ""

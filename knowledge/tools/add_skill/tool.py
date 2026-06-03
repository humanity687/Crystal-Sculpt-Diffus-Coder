# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

import time
import json
import sqlite3
from pathlib import Path

from knowledge.config import RAW_SKILLS_DIR, SKILLS_SUMMARY_DIR, VECTOR_DB_PATH, KNOWLEDGE_ROOT


def execute(name: str, content: str):
    """
    Save a skill as Markdown to raw_skills/ and index its summary into the knowledge base.

    Args:
        name: Skill name (used as filename, e.g., "nginx_setup")
        content: Skill content in Markdown format
    """
    # Lazy import to avoid circular dependency at module load time
    from knowledge.vector import add_summary
    from knowledge.summarizer import extract_summary_from_text, build_searchable_text

    # Sanitize name
    safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-")).strip()
    if not safe_name:
        return "Error: Invalid skill name"

    filename = f"{safe_name}.md"
    filepath = RAW_SKILLS_DIR / filename
    try:
        relative_path = str(filepath.relative_to(KNOWLEDGE_ROOT))
    except ValueError:
        import os
        relative_path = os.path.relpath(filepath, KNOWLEDGE_ROOT)
    source_key = f"file:{relative_path}"

    # Write the raw skill file
    filepath.write_text(content, encoding="utf-8")

    # Generate summary and write to skills_summary/
    summary_text = extract_summary_from_text(content)
    if not summary_text:
        return f"Error: Could not extract summary from skill '{safe_name}'"

    memory_id = f"skill:{safe_name}"
    summary_data = {
        "memory_id": memory_id,
        "title": safe_name,
        "summary": summary_text[:200],
        "key_points": [summary_text],
        "tags": [],
    }
    searchable = build_searchable_text(summary_data)

    summary_path = SKILLS_SUMMARY_DIR / f"{safe_name}.summary.json"
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Index new summary first (idempotent upsert), then clean up old entries.
    # If the DELETE step fails, the worst case is stale entries coexist with
    # the new one — the DB is still consistent.
    add_summary(
        memory_id=memory_id,
        text=searchable,
        doc_type="skill_summary",
        source=source_key,
        summary_json=json.dumps(summary_data, ensure_ascii=False),
    )

    conn = sqlite3.connect(VECTOR_DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM vectors WHERE source = ?", (source_key,))
        old_ids = cursor.fetchall()
        for (old_id,) in old_ids:
            cursor.execute("DELETE FROM fts WHERE rowid = ?", (old_id,))
        cursor.execute("DELETE FROM vectors WHERE source = ?", (source_key,))

        # Update file_versions to prevent re-indexing on restart
        mtime = filepath.stat().st_mtime
        cursor.execute(
            "INSERT OR REPLACE INTO file_versions (path, mtime, last_updated) VALUES (?, ?, ?)",
            (relative_path, mtime, time.time()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return f"Skill '{safe_name}' saved and indexed successfully."

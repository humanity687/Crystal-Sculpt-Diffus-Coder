# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Vector Database Operations

Two-level summary memory system:
  - Level 1 (summaries): Only structured summaries are embedded and indexed.
    Conversation summaries are generated at runtime; tool/skill summaries are
    extracted from markdown files during incremental indexing.
  - Level 2 (recall): Full original text stays on disk. The recall tool
    fetches it by memory_id when the model needs details.
"""

import sqlite3
import sys
import numpy as np
import time
import re
import json
from pathlib import Path

from .config import (
    KNOWLEDGE_ROOT, VECTOR_DB_PATH,
    RAW_MEMORIES_DIR, RAW_TOOLS_DIR, RAW_SKILLS_DIR,
    MEMORIES_SUMMARY_DIR, TOOLS_SUMMARY_DIR, SKILLS_SUMMARY_DIR,
    encode_single,
)


def _get_conn():
    """Return a sqlite3 connection with busy_timeout set to avoid 'database is locked'.

    Retries up to 3 times with exponential backoff if the database is locked
    despite the busy_timeout. This handles edge cases where WAL checkpointing
    or multi-process access blocks the connection.
    """
    for attempt in range(3):
        try:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
from .summarizer import (
    extract_summary_from_text,
    build_searchable_text,
    _extract_tool_summary_data,
    _extract_skill_summary_data,
)

# ── Type → weight mapping (used by search.py) ─────────────────────────
# Summary types are embedded instead of full documents.
# Old full-document types still exist for backward compat.
SUMMARY_TYPES = {
    "conversation_summary": 0.3,
    "tool_summary": 1.0,
    "skill_summary": 0.8,
    "experience_crystal": 0.6,
}
LEGACY_TYPES = {
    "conversation": 0.2,
    "tool": 1.0,
    "skill": 0.8,
    "hyw": 1.0,
}

# Override from config.json if memory_weights is present
try:
    import json
    with open("config.json", "r", encoding="utf-8") as _f:
        cfg = json.load(_f)
    mw = cfg.get("memory_weights")
    if isinstance(mw, dict):
        SUMMARY_TYPES.update({k: v for k, v in mw.items() if k in SUMMARY_TYPES})
        LEGACY_TYPES.update({k: v for k, v in mw.items() if k in LEGACY_TYPES})
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass


def get_file_state():
    """Get the status of all summary files in *_summary/ directories (path -> mtime).

    Only .summary.json files are tracked — these are the source of truth
    for what gets indexed into the vector DB.
    """
    state = {}
    for summary_dir in (MEMORIES_SUMMARY_DIR, TOOLS_SUMMARY_DIR, SKILLS_SUMMARY_DIR):
        for sf in summary_dir.rglob("*.summary.json"):
            try:
                mtime = sf.stat().st_mtime
                state[str(sf.relative_to(KNOWLEDGE_ROOT))] = mtime
            except Exception as e:
                print(f"[Vector] Failed to stat {sf}: {e}", file=sys.stderr)
    return state


def add_document(text: str, source: str = "", doc_type: str = "generic"):
    """Insert a full document into the vector DB (legacy API).

    New code should prefer add_summary() for the two-level memory system.
    """
    emb = encode_single(text)
    emb_blob = emb.tobytes()
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM vectors WHERE text = ?", (text,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO vectors (text, embedding, source, type) VALUES (?, ?, ?, ?)",
            (text, emb_blob, source, doc_type),
        )
        new_id = cursor.lastrowid
        try:
            cursor.execute(
                "INSERT INTO fts (rowid, text) VALUES (?, ?)", (new_id, text)
            )
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
        conn.commit()
    conn.close()


def add_summary(
    memory_id: str,
    text: str,
    doc_type: str,
    source: str = "",
    summary_json: str = "",
):
    """Insert or update a summary entry in the vector DB.

    Only the summary text is embedded and indexed — the original document
    stays on disk and is accessible via the recall tool.

    Args:
        memory_id: Unique ID (e.g., "conv:20260115-143022-a1b2c3", "tool:read")
        text: Searchable summary text (title + summary + key_points concatenation)
        doc_type: One of "conversation_summary", "tool_summary", "skill_summary",
                  "experience_crystal"
        source: Relative path under KNOWLEDGE_ROOT to the original file
        summary_json: Full structured summary as JSON string (for metadata extraction)
    """
    emb = encode_single(text)
    emb_blob = emb.tobytes()

    for attempt in range(3):
        try:
            conn = _get_conn()
            cursor = conn.cursor()

            # Upsert by memory_id
            cursor.execute("SELECT id FROM vectors WHERE memory_id = ?", (memory_id,))
            row = cursor.fetchone()
            if row:
                doc_id = row[0]
                cursor.execute(
                    "UPDATE vectors SET text=?, embedding=?, summary_json=?, type=?, source=? "
                    "WHERE id=?",
                    (text, emb_blob, summary_json, doc_type, source, doc_id),
                )
                cursor.execute("DELETE FROM fts WHERE rowid = ?", (doc_id,))
                try:
                    cursor.execute(
                        "INSERT INTO fts (rowid, text) VALUES (?, ?)", (doc_id, text)
                    )
                except sqlite3.OperationalError:
                    pass
            else:
                cursor.execute(
                    "INSERT INTO vectors (text, embedding, memory_id, summary_json, type, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (text, emb_blob, memory_id, summary_json, doc_type, source),
                )
                new_id = cursor.lastrowid
                try:
                    cursor.execute(
                        "INSERT INTO fts (rowid, text) VALUES (?, ?)", (new_id, text)
                    )
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e):
                        raise

            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            try:
                conn.close()
            except Exception:
                pass
            if "locked" in str(e).lower() and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise


def init_vector_db():
    """Create database tables if they do not exist, and add missing columns.

    Cleans up residual WAL/SHM files from a previous crashed process before
    opening any connection — these are the #1 cause of 'database is locked'
    on startup.
    """
    # Purge residual WAL/SHM from a killed process. Safe: these only contain
    # uncommitted data; the main .db file is unaffected.
    wal_path = Path(str(VECTOR_DB_PATH) + "-wal")
    shm_path = Path(str(VECTOR_DB_PATH) + "-shm")
    for p in (wal_path, shm_path):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_versions (
            path TEXT PRIMARY KEY,
            mtime REAL,
            last_updated REAL
        )
    """)
    # Legacy columns
    try:
        cursor.execute("ALTER TABLE vectors ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE vectors ADD COLUMN type TEXT")
    except sqlite3.OperationalError:
        pass
    # New columns for two-level memory system
    try:
        cursor.execute("ALTER TABLE vectors ADD COLUMN memory_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE vectors ADD COLUMN summary_json TEXT")
    except sqlite3.OperationalError:
        pass
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
            text,
            tokenize = 'unicode61'
        )
    """)
    conn.commit()
    conn.close()


def rebuild_fts_index():
    """Rebuild the FTS index from the vectors table"""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fts")
    cursor.execute("SELECT id, text FROM vectors")
    rows = cursor.fetchall()
    for rowid, text in rows:
        try:
            cursor.execute("INSERT INTO fts (rowid, text) VALUES (?, ?)", (rowid, text))
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def _ensure_tool_summary(tool_name: str) -> str | None:
    """Get or generate a tool summary. Reads from tools_summary/ first,
    falls back to extracting from raw_tools/ and saving the result.
    Regenerates if the raw file is newer than the cached summary.

    Uses _extract_tool_summary_data() to parse structured tool markdown
    into natural-language-like fields with Chinese labels.
    """
    summary_path = TOOLS_SUMMARY_DIR / f"{tool_name}.summary.json"
    raw_path = RAW_TOOLS_DIR / f"{tool_name}.md"

    if not raw_path.exists():
        print(f"[Vector] Tool raw file missing: {tool_name}", file=sys.stderr)
        return None

    raw_mtime = raw_path.stat().st_mtime
    if summary_path.exists():
        summary_mtime = summary_path.stat().st_mtime
        if raw_mtime <= summary_mtime:
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                result = build_searchable_text(data)
                if result:
                    return result
            except (json.JSONDecodeError, KeyError):
                pass

    text = raw_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    # Use structured extraction for tool documentation
    summary_data = _extract_tool_summary_data(text, tool_name)
    if summary_data is None:
        # Fallback to generic extractive summary
        fallback = extract_summary_from_text(text)
        if fallback:
            summary_data = {
                "title": tool_name,
                "summary": fallback[:200],
                "key_points": [],
                "tags": [],
            }
        else:
            return None

    summary_data["memory_id"] = f"tool:{tool_name}"
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")
    searchable = build_searchable_text(summary_data)
    print(f"[Vector] Tool summary generated: {tool_name} ({len(searchable)} chars)", file=sys.stderr)
    return searchable


def _ensure_skill_summary(skill_name: str) -> str | None:
    """Get or generate a skill summary. Reads from skills_summary/ first,
    falls back to extracting from raw_skills/ and saving the result.
    Regenerates if the raw file is newer than the cached summary.

    Uses _extract_skill_summary_data() to parse skill markdown, strip
    YAML frontmatter, and extract core principles as distinct key_points.
    """
    summary_path = SKILLS_SUMMARY_DIR / f"{skill_name}.summary.json"
    raw_path = RAW_SKILLS_DIR / f"{skill_name}.md"

    if not raw_path.exists():
        print(f"[Vector] Skill raw file missing: {skill_name}", file=sys.stderr)
        return None

    raw_mtime = raw_path.stat().st_mtime
    if summary_path.exists():
        summary_mtime = summary_path.stat().st_mtime
        if raw_mtime <= summary_mtime:
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                result = build_searchable_text(data)
                if result:
                    return result
            except (json.JSONDecodeError, KeyError):
                pass

    text = raw_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    # Use structured extraction that strips YAML frontmatter and extracts
    # core principles from the skill document
    summary_data = _extract_skill_summary_data(text, skill_name)
    if summary_data is None:
        fallback = extract_summary_from_text(text)
        if fallback:
            summary_data = {
                "title": skill_name,
                "summary": fallback[:200],
                "key_points": [],
                "tags": [],
            }
        else:
            return None

    summary_data["memory_id"] = f"skill:{skill_name}"
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")
    searchable = build_searchable_text(summary_data)
    print(f"[Vector] Skill summary generated: {skill_name} ({len(searchable)} chars)", file=sys.stderr)
    return searchable


def _ensure_memory_summary(ts_name: str) -> str | None:
    """Get or generate a conversation summary from raw_memories/ backup.
    Regenerates if the raw file is newer than the cached summary.

    Extracts User/AI messages from the backup, generates a structured
    summary with distinct key_points (not duplicated from summary).
    """
    summary_path = MEMORIES_SUMMARY_DIR / f"{ts_name}.summary.json"
    raw_path = RAW_MEMORIES_DIR / f"{ts_name}.md"

    if not raw_path.exists():
        return None

    raw_mtime = raw_path.stat().st_mtime
    if summary_path.exists():
        summary_mtime = summary_path.stat().st_mtime
        if raw_mtime <= summary_mtime:
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                result = build_searchable_text(data)
                if result:
                    return result
            except (json.JSONDecodeError, KeyError):
                pass

    text = raw_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    # Extract User/AI parts for summary generation
    user_msg = ""
    ai_msg = ""
    for line in text.split("\n"):
        if line.startswith("User: "):
            user_msg = line[6:]
        elif line.startswith("AI: "):
            ai_msg = line[4:]

    combined = f"User: {user_msg}\nAI: {ai_msg}"
    result = extract_summary_from_text(ai_msg or combined)
    if result:
        # Use only the first 20 chars as title, summary as-is,
        # and leave key_points empty to avoid duplication
        summary_data = {
            "memory_id": f"conv:{ts_name}",
            "title": result[:15],
            "main_summary": result[:40],
            "dimensions": [],
            "summary": result[:200],
            "key_points": [],
            "tags": [],
        }
        summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return build_searchable_text(summary_data)
    return None


def _generate_all_missing_summaries():
    """Generate or regenerate summary files for raw files.

    A summary is regenerated when:
      - No summary file exists yet (missing)
      - The raw file is newer than the summary (stale)
      - The summary file is corrupted (handled in _ensure_* functions)
    """
    print("[Vector] Checking for missing/stale summary files...", file=sys.stderr)
    # Tools
    for raw in RAW_TOOLS_DIR.glob("*.md"):
        tool_name = raw.stem
        _ensure_tool_summary(tool_name)
    # Skills
    for raw in RAW_SKILLS_DIR.glob("*.md"):
        skill_name = raw.stem
        _ensure_skill_summary(skill_name)
    # Memories
    for raw in RAW_MEMORIES_DIR.glob("*.md"):
        ts_name = raw.stem
        _ensure_memory_summary(ts_name)


def incremental_update():
    """Incremental update: index .summary.json files from *_summary/ directories.

    Only structured summary files are embedded and indexed. Raw files under
    raw_memories/, raw_tools/, raw_skills/ stay on disk and are accessed by
    the recall tool directly.

    File tracking uses summary file paths (relative to KNOWLEDGE_ROOT), so
    source keys look like "file:tools_summary/read.summary.json".
    """
    print("Performing incremental vector library update...", file=sys.stderr)

    # Generate missing summaries before indexing
    _generate_all_missing_summaries()

    current_state = get_file_state()
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT path, mtime FROM file_versions")
    stored = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    # 1. Process new or modified summary files
    for path, mtime in current_state.items():
        if path not in stored or stored[path] != mtime:
            summary_path = KNOWLEDGE_ROOT / path
            try:
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                searchable = build_searchable_text(data)
                if not searchable:
                    continue

                memory_id = data.get("memory_id", "")

                # Determine doc_type from directory name
                path_str = str(path)
                if "memories_summary" in path_str:
                    doc_type = "conversation_summary"
                elif "tools_summary" in path_str:
                    doc_type = "tool_summary"
                elif "skills_summary" in path_str:
                    doc_type = "skill_summary"
                else:
                    doc_type = "summary"

                source_key = f"file:{path}"

                # Encode with connection closed (CPU-intensive, no lock needed)
                emb = encode_single(searchable)
                emb_blob = emb.tobytes()
                summary_json = json.dumps(data, ensure_ascii=False)

                # Re-open connection for the write — held only briefly
                conn = _get_conn()
                cursor = conn.cursor()

                # Remove old entries for this source
                cursor.execute(
                    "SELECT id FROM vectors WHERE source = ?", (source_key,)
                )
                old_ids = cursor.fetchall()
                for (old_id,) in old_ids:
                    cursor.execute("DELETE FROM fts WHERE rowid = ?", (old_id,))
                cursor.execute(
                    "DELETE FROM vectors WHERE source = ?", (source_key,)
                )

                # Insert new entry
                cursor.execute(
                    "INSERT INTO vectors (text, embedding, memory_id, summary_json, type, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (searchable, emb_blob, memory_id, summary_json, doc_type, source_key),
                )
                new_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO fts (rowid, text) VALUES (?, ?)", (new_id, searchable)
                )

                cursor.execute(
                    "INSERT OR REPLACE INTO file_versions (path, mtime, last_updated) VALUES (?, ?, ?)",
                    (path, mtime, time.time()),
                )
                conn.commit()
                conn.close()
                print(f"[Vector] Indexed summary: {path}", file=sys.stderr)
            except Exception as e:
                print(f"[Vector] Failed to index summary {path}: {e}", file=sys.stderr)

    # 2. Remove entries for deleted summary files
    conn = _get_conn()
    cursor = conn.cursor()
    for path in stored:
        if path not in current_state:
            source_key = f"file:{path}"
            cursor.execute("SELECT id FROM vectors WHERE source = ?", (source_key,))
            old_ids = cursor.fetchall()
            for (old_id,) in old_ids:
                cursor.execute("DELETE FROM fts WHERE rowid = ?", (old_id,))
            cursor.execute("DELETE FROM vectors WHERE source = ?", (source_key,))
            cursor.execute("DELETE FROM file_versions WHERE path = ?", (path,))
            print(f"[Vector] Removed stale entry: {path}", file=sys.stderr)

    # 3. Orphan cleanup: entries whose summary file no longer exists on disk
    cursor.execute(
        "SELECT id, source FROM vectors WHERE type IN "
        "('conversation_summary', 'tool_summary', 'skill_summary')"
    )
    for vec_id, source in cursor.fetchall():
        if not source:
            continue
        src_path = source[5:] if source.startswith("file:") else source
        if not (KNOWLEDGE_ROOT / src_path).exists():
            cursor.execute("DELETE FROM fts WHERE rowid = ?", (vec_id,))
            cursor.execute("DELETE FROM vectors WHERE id = ?", (vec_id,))
            cursor.execute("DELETE FROM file_versions WHERE path = ?", (src_path,))
            print(f"[Vector] Cleaned orphan: {src_path}", file=sys.stderr)

    conn.commit()
    conn.close()
    print("Incremental update completed.", file=sys.stderr)


def full_rebuild():
    """Full rebuild: clear everything, generate all summaries from raw files,
    then index all .summary.json files into the vector DB."""
    print("Performing full vector library rebuild...", file=sys.stderr)
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vectors")
    cursor.execute("DELETE FROM file_versions")
    cursor.execute("DELETE FROM fts")
    conn.commit()
    conn.close()

    # Generate summary files for all raw content
    _generate_all_missing_summaries()

    # Index all summaries
    incremental_update()
    rebuild_fts_index()
    print("Full rebuild completed.", file=sys.stderr)


def check_and_update():
    """Initialize DB and check if full rebuild is needed"""
    init_vector_db()
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vectors")
    count = cursor.fetchone()[0]
    conn.close()
    if count == 0:
        full_rebuild()
    else:
        incremental_update()

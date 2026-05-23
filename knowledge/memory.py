# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Conversation Memory Management

Two-level summary memory system:
  - Level 1: Back up original conversation to disk, then generate a structured
    summary and store only the summary in the vector DB.
  - Level 2: The recall tool fetches the original on-disk backup by memory_id
    when the model needs full context.
"""

import json
import threading
from datetime import datetime

from .config import KNOWLEDGE_ROOT, RAW_MEMORIES_DIR, MEMORIES_SUMMARY_DIR
from .vector import add_summary
from .summarizer import (
    generate_conversation_summary,
    build_searchable_text,
)


def add_conversation(user_msg: str, ai_msg: str):
    """Store a conversation turn in the two-level memory system.

    1. Write original full text to knowledge/memories/{timestamp}.md (backup)
    2. Generate a structured summary (with LLM if client available, else extractive)
    3. Store only the summary text in the vector DB
    4. Original text is NOT embedded — it stays on disk, retrievable via recall tool
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"{timestamp}.md"
    backup_path = RAW_MEMORIES_DIR / backup_filename
    source = str(backup_path.relative_to(KNOWLEDGE_ROOT))

    # Step 1: Write original conversation to disk
    full_text = f"User: {user_msg}\nAI: {ai_msg}"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(full_text)
    except Exception as e:
        print(f"Failed to write memory backup: {e}")
        return  # Don't proceed if we can't back up

    # Step 2: Generate summary (extractive fallback — LLM generation is async)
    summary = generate_conversation_summary(user_msg, ai_msg)
    if summary is None:
        return

    # Step 3: Store summary in vector DB
    searchable = build_searchable_text(summary)
    if not searchable:
        return

    summary_json = json.dumps(summary, ensure_ascii=False)
    add_summary(
        memory_id=summary["memory_id"],
        text=searchable,
        doc_type="conversation_summary",
        source=source,
        summary_json=summary_json,
    )


def add_conversation_with_llm(
    user_msg: str,
    ai_msg: str,
    client,
    model: str,
    background: bool = True,
):
    """Store conversation AND generate summary via LLM.

    When background=True (default), the LLM call runs in a daemon thread
    so it doesn't block the SSE stream.

    Args:
        user_msg: The user's message.
        ai_msg: The full AI response.
        client: OpenAI-compatible client instance.
        model: Model name for summarization.
        background: If True, run LLM call in background thread.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"{timestamp}.md"
    backup_path = RAW_MEMORIES_DIR / backup_filename
    source = str(backup_path.relative_to(KNOWLEDGE_ROOT))

    # Step 1: Write original conversation to disk (always synchronous)
    full_text = f"User: {user_msg}\nAI: {ai_msg}"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(full_text)
    except Exception as e:
        print(f"Failed to write memory backup: {e}")
        return

    def _generate_and_store():
        summary = generate_conversation_summary(
            user_msg, ai_msg, client=client, model=model
        )
        if summary is None:
            return
        searchable = build_searchable_text(summary)
        if not searchable:
            return
        summary_json = json.dumps(summary, ensure_ascii=False)
        add_summary(
            memory_id=summary["memory_id"],
            text=searchable,
            doc_type="conversation_summary",
            source=source,
            summary_json=summary_json,
        )

    if background:
        t = threading.Thread(target=_generate_and_store, daemon=True)
        t.start()
    else:
        _generate_and_store()

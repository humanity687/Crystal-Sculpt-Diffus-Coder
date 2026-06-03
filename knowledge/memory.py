# Copyright (C) 2026 humanity687
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
import queue
import sys
import threading
from datetime import datetime

import openai as _openai

from .config import KNOWLEDGE_ROOT, RAW_MEMORIES_DIR, MEMORIES_SUMMARY_DIR
from .vector import add_summary
from .summarizer import (
    generate_conversation_summary,
    build_searchable_text,
)

# --- Background LLM summary worker (single thread, serialized queue) ---
# Avoids httpx.Client multi-thread contention by using a dedicated
# OpenAI client instance and a single worker thread.

_summary_client = None
_summary_lock = threading.Lock()
_pending_summaries = queue.Queue()
_summary_worker_started = False


_current_summary_model: str | None = None

def _ensure_summary_worker(api_key: str, base_url: str, model: str):
    """Start or update the singleton summary worker thread."""
    global _summary_client, _summary_worker_started, _current_summary_model
    with _summary_lock:
        if not _summary_worker_started:
            _summary_client = _openai.OpenAI(api_key=api_key, base_url=base_url)
            _current_summary_model = model
            t = threading.Thread(
                target=_summary_worker, daemon=True
            )
            t.start()
            _summary_worker_started = True
            print(
                "[SummaryWorker] Background LLM summary worker started",
                file=sys.stderr,
            )
        elif model != _current_summary_model:
            _current_summary_model = model
            _summary_client = _openai.OpenAI(api_key=api_key, base_url=base_url)
            print(
                f"[SummaryWorker] Model updated to {model}",
                file=sys.stderr,
            )


def _summary_worker():
    """Single background thread that processes summary tasks one at a time."""
    while True:
        try:
            task = _pending_summaries.get()
            if task is None:
                break
            user_msg, ai_msg, source = task
            model = _current_summary_model or ""
            _generate_and_store(user_msg, ai_msg, source, _summary_client, model)
        except Exception as e:
            print(f"[SummaryWorker] Unexpected error: {e}", file=sys.stderr)


# --- Public API ---


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

    When background=True (default), the summary is enqueued to a single
    worker thread with its own OpenAI client, avoiding httpx.Client
    multi-thread contention with the main agent.

    Args:
        user_msg: The user's message.
        ai_msg: The full AI response.
        client: OpenAI-compatible client instance (used to extract credentials
                for the worker's own client).
        model: Model name for summarization.
        background: If True, enqueue to background worker thread.
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

    if background:
        _ensure_summary_worker(
            api_key=client.api_key,
            base_url=str(client.base_url),
            model=model,
        )
        _pending_summaries.put((user_msg, ai_msg, source))
    else:
        _generate_and_store(user_msg, ai_msg, source, client, model)


def _generate_and_store(
    user_msg: str,
    ai_msg: str,
    source: str,
    client,
    model: str,
):
    """Generate LLM summary and store in vector DB. Called from worker thread."""
    try:
        summary = generate_conversation_summary(
            user_msg, ai_msg, client=client, model=model
        )
        if summary is None:
            print(
                "[SummaryWorker] LLM summary returned None, "
                "falling back to extractive summary",
                file=sys.stderr,
            )
            summary = generate_conversation_summary(user_msg, ai_msg)
            if summary is None:
                print(
                    "[SummaryWorker] Extractive summary also failed, "
                    "skipping this turn",
                    file=sys.stderr,
                )
                return

        searchable = build_searchable_text(summary)
        if not searchable:
            print(
                "[SummaryWorker] build_searchable_text returned empty",
                file=sys.stderr,
            )
            return

        summary_json = json.dumps(summary, ensure_ascii=False)
        add_summary(
            memory_id=summary["memory_id"],
            text=searchable,
            doc_type="conversation_summary",
            source=source,
            summary_json=summary_json,
        )
        print(
            f"[SummaryWorker] Summary stored: {summary.get('memory_id', '?')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[SummaryWorker] Error generating summary: {e}", file=sys.stderr)

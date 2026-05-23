# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Hybrid Search (Vector + FTS5 + RRF)

Two-level summary memory system:
  - Returns structured dicts with memory_id for recall tool integration.
  - Summary types (conversation_summary, tool_summary, skill_summary) have
    their own weight tiers, replacing the old full-document type weights.
  - Legacy types (tool, skill, conversation, hyw) still supported for
    backward compatibility with existing vector DB entries.
"""

import sqlite3
import numpy as np
import re
import json

from .config import VECTOR_DB_PATH, HYBRID_VECTOR_WEIGHT, HYBRID_FTS_WEIGHT, get_model

# ── Type weight mapping ──────────────────────────────────────────────
TYPE_WEIGHTS = {
    # New summary types (two-level memory system)
    "conversation_summary": 0.15,
    "tool_summary": 1.0,
    "skill_summary": 0.8,
    # Legacy full-document types (backward compat)
    "conversation": 0.2,
    "tool": 1.0,
    "skill": 0.8,
    "hyw": 1.0,
    # Fallback
    "generic": 1.0,
}

# ── Type icon mapping for display ────────────────────────────────────
TYPE_ICONS = {
    "conversation_summary": "💬 对话",
    "conversation": "💬 对话(旧)",
    "tool_summary": "🔧 工具",
    "tool": "🔧 工具(旧)",
    "skill_summary": "📋 技能",
    "skill": "📋 技能(旧)",
    "hyw": "📖 文档",
    "generic": "📄",
}


def search(query: str, k: int = 5) -> list[dict]:
    """Retrieve the top k knowledge entries.

    Returns structured dicts for the two-level memory system.
    Each dict contains:
      - memory_id: Unique ID for recall tool (or None for legacy entries)
      - text: The searchable text (summary or full document)
      - type: Document type (conversation_summary, tool_summary, etc.)
      - score: Combined RRF score
      - title: Extracted title from summary_json (if available)
      - icon: Display icon string

    Legacy callers that expect list[str] can use [r['text'] for r in results].
    """
    conn = sqlite3.connect(VECTOR_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, embedding, type, memory_id, summary_json FROM vectors"
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return []

    model = get_model()
    q_emb = model.encode(query)

    vector_scores = []
    for doc_id, text, emb_blob, doc_type, memory_id, summary_json in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        dot = np.dot(q_emb, emb)
        norm_q = np.linalg.norm(q_emb)
        norm_d = np.linalg.norm(emb)
        sim = dot / (norm_q * norm_d) if norm_q * norm_d != 0 else 0

        weight = TYPE_WEIGHTS.get(doc_type, TYPE_WEIGHTS["generic"])
        final_score = sim * weight
        vector_scores.append(
            (final_score, doc_id, text, doc_type or "generic", memory_id, summary_json)
        )

    vector_scores.sort(reverse=True, key=lambda x: x[0])

    # ── FTS5 keyword search ──────────────────────────────────────────
    def clean_fts_query(q: str) -> str:
        cleaned = re.sub(r"[^\w一-鿿\s]", " ", q)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    conn_fts = sqlite3.connect(VECTOR_DB_PATH)
    cursor_fts = conn_fts.cursor()
    fts_query = clean_fts_query(query)
    if fts_query:
        try:
            cursor_fts.execute(
                "SELECT rowid, rank FROM fts WHERE text MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, k * 2),
            )
            fts_results = cursor_fts.fetchall()
        except Exception as e:
            print(f"FTS search failed: {e}")
            fts_results = []
    else:
        fts_results = []
    conn_fts.close()

    fts_rank_map = {}
    fts_rowids = []
    for rank_idx, (rowid, rank) in enumerate(fts_results):
        fts_rank_map[rowid] = rank_idx + 1
        fts_rowids.append(rowid)

    # Fetch metadata for FTS-only results
    fts_data_map = {}
    if fts_rowids:
        conn_fts2 = sqlite3.connect(VECTOR_DB_PATH)
        cursor_fts2 = conn_fts2.cursor()
        placeholders = ",".join("?" * len(fts_rowids))
        cursor_fts2.execute(
            f"SELECT id, text, type, memory_id, summary_json FROM vectors "
            f"WHERE id IN ({placeholders})",
            fts_rowids,
        )
        for doc_id, text, doc_type, memory_id, summary_json in cursor_fts2.fetchall():
            fts_data_map[doc_id] = (text, doc_type or "generic", memory_id, summary_json)
        conn_fts2.close()

    # ── RRF fusion ───────────────────────────────────────────────────
    K = 60
    combined = {}
    for idx, (vec_score, doc_id, text, doc_type, memory_id, summary_json) in enumerate(
        vector_scores
    ):
        rank = idx + 1
        rrf_score = HYBRID_VECTOR_WEIGHT / (K + rank)
        combined[doc_id] = [
            rrf_score, text, doc_type, memory_id, summary_json, vec_score
        ]

    for doc_id, fts_rank in fts_rank_map.items():
        rrf_score = HYBRID_FTS_WEIGHT / (K + fts_rank)
        if doc_id in combined:
            combined[doc_id][0] += rrf_score
        else:
            text, doc_type, memory_id, summary_json = fts_data_map.get(
                doc_id, ("", "generic", None, None)
            )
            combined[doc_id] = [rrf_score, text, doc_type, memory_id, summary_json, 0]

    # ── Build structured results ─────────────────────────────────────
    sorted_items = sorted(combined.items(), key=lambda x: x[1][0], reverse=True)

    results = []
    seen_texts = set()
    for doc_id, (score, text, doc_type, memory_id, summary_json, _) in sorted_items:
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)

        icon = TYPE_ICONS.get(doc_type, TYPE_ICONS["generic"])

        # Extract title from summary_json if available
        title = None
        if summary_json:
            try:
                sj = json.loads(summary_json)
                title = sj.get("title")
            except (json.JSONDecodeError, TypeError):
                pass

        results.append({
            "memory_id": memory_id,
            "text": text,
            "type": doc_type,
            "score": round(score, 4),
            "title": title,
            "icon": icon,
        })

        if len(results) >= k:
            break

    # Fallback padding from vector-only results
    if len(results) < k:
        for _, doc_id, text, doc_type, memory_id, summary_json in vector_scores:
            if text and text not in seen_texts:
                seen_texts.add(text)
                icon = TYPE_ICONS.get(doc_type or "generic", TYPE_ICONS["generic"])
                results.append({
                    "memory_id": memory_id,
                    "text": text,
                    "type": doc_type or "generic",
                    "score": 0.0,
                    "title": None,
                    "icon": icon,
                })
                if len(results) >= k:
                    break

    return results


def search_texts(query: str, k: int = 5) -> list[str]:
    """Backward-compatible wrapper: return only text strings.

    Use this when callers need the old list[str] interface.
    """
    return [r["text"] for r in search(query, k=k)]

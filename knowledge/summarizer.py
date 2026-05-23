# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Conversation Summarizer — Lightweight LLM probe for incremental summary generation.

Generates structured summaries for the two-level memory system.
Called after each conversation turn to produce a JSON summary.
"""

import json
import hashlib
import sys
import re
from datetime import datetime


SUMMARY_PROMPT = """你是一个对话摘要探针。将以下用户-AI对话回合压缩为结构化摘要。

要求：
1. title 不超过 20 字，精准概括本轮主题
2. summary 用 1-2 句话概述核心讨论和结论（≤100 字）
3. key_points 列出 2-5 个关键决策/发现/产出
4. tags 列出 3-6 个关键词或技术术语
5. 如果本轮讨论与之前对话相关，在 summary 中体现这种延续性

只返回 JSON 对象，不要其他内容：
{{
  "title": "...",
  "summary": "...",
  "key_points": ["...", "..."],
  "tags": ["...", "..."]
}}

对话回合：
User: {user_msg}
AI: {ai_msg}"""


def _make_memory_id(prefix: str, timestamp: str) -> str:
    """Generate a unique memory_id with short hash suffix."""
    raw = f"{prefix}:{timestamp}"
    hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:6]
    return f"{prefix}:{timestamp}-{hash_suffix}"


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter (--- delimited) and ```yaml fences from the start of text."""
    t = text.strip()
    stripped = False
    # Strip ```yaml ... ``` code fence wrapping YAML frontmatter
    if t.startswith("```yaml\n") or t.startswith("```yml\n"):
        end_fence = t.find("\n```", 7)
        if end_fence != -1:
            t = t[end_fence + 4:].strip()
            stripped = True
    elif t.startswith("```\n"):
        end_fence = t.find("\n```", 4)
        if end_fence != -1:
            t = t[end_fence + 4:].strip()
            stripped = True
    # Strip YAML frontmatter: starts with ---, ends with --- or ...
    if t.startswith("---"):
        rest = t[3:]
        for delim in ("\n---\n", "\n---", "\n...\n", "\n..."):
            idx = rest.find(delim)
            if idx != -1:
                t = rest[idx + len(delim):].strip()
                stripped = True
                break
        else:
            if rest.startswith("\n"):
                t = rest.strip()
                stripped = True
    if stripped:
        preview = t[:80].replace("\n", "\\n")
        print(f"[Summarizer] Stripped frontmatter, result preview: {preview}...", file=sys.stderr)
    return t


def extract_summary_from_text(text: str, max_sentences: int = 3) -> str:
    """Extract a simple summary from text without LLM.

    Used as fallback when no LLM client is available, or for tool/skill
    README files during incremental indexing.

    Strategy: take the first substantive paragraph after skipping
    HTML comments and markdown headers.
    """
    lines = _strip_frontmatter(text).split("\n")
    content_lines = []
    in_comment = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<!--"):
            in_comment = True
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith("```"):
            if content_lines:
                break
            continue
        if stripped.startswith("**") or stripped.startswith("* "):
            continue
        content_lines.append(stripped)

    if not content_lines:
        fallback = text[:200].strip()
        print(f"[Summarizer] No content lines found, fallback to first 200 chars: {fallback[:80]}...", file=sys.stderr)
        return fallback

    summary = " ".join(content_lines)
    # Handle both Chinese (。) and English (. ) sentence boundaries
    sentences = re.split(r"[。.!?]\s*", summary)
    selected = [s for s in sentences[:max_sentences] if s.strip()]
    result = "。".join(selected) + "。"
    if len(result) > 300:
        result = result[:300] + "..."
    print(f"[Summarizer] Extracted summary: {result[:120]}...", file=sys.stderr)
    return result


def generate_conversation_summary(
    user_msg: str,
    ai_msg: str,
    client=None,
    model: str = "",
) -> dict | None:
    """Generate a structured summary for a conversation turn.

    Uses a lightweight LLM call when a client is available. Falls back
    to extractive summarization when no client is provided.

    Args:
        user_msg: The user's message.
        ai_msg: The full AI response.
        client: OpenAI-compatible client instance (optional).
        model: Model name to use (required if client is provided).

    Returns:
        Summary dict with memory_id, title, summary, key_points, tags,
        or None if summarization fails entirely.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    memory_id = _make_memory_id("conv", timestamp)

    if client and model:
        return _llm_summarize(user_msg, ai_msg, client, model, memory_id)

    # Fallback: extractive summarization (no LLM needed)
    combined = f"User: {user_msg}\nAI: {ai_msg}"
    summary_text = extract_summary_from_text(ai_msg)
    title = summary_text[:20] if summary_text else "对话摘要"

    return {
        "memory_id": memory_id,
        "title": title,
        "summary": summary_text,
        "key_points": [summary_text] if summary_text else [],
        "tags": [],
        "source_file": f"memories/{timestamp.replace('-', '')}.md",
        "token_count": len(combined) // 4,
        "timestamp": datetime.now().isoformat(),
    }


def _llm_summarize(
    user_msg: str,
    ai_msg: str,
    client,
    model: str,
    memory_id: str,
) -> dict | None:
    """Use a lightweight LLM probe to generate a summary."""
    # Truncate very long messages for the summarization probe
    user_truncated = user_msg[:2000] if len(user_msg) > 2000 else user_msg
    ai_truncated = ai_msg[:3000] if len(ai_msg) > 3000 else ai_msg

    prompt = SUMMARY_PROMPT.format(
        user_msg=user_truncated,
        ai_msg=ai_truncated,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        result_text = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            result_text = "\n".join(lines)

        result = json.loads(result_text)

        return {
            "memory_id": memory_id,
            "title": result.get("title", "对话摘要"),
            "summary": result.get("summary", ""),
            "key_points": result.get("key_points", []),
            "tags": result.get("tags", []),
            "source_file": f"memories/{memory_id.split(':',1)[1].replace('-', '')}.md",
            "token_count": (len(user_msg) + len(ai_msg)) // 4,
            "timestamp": datetime.now().isoformat(),
        }

    except json.JSONDecodeError as e:
        print(f"[Summarizer] Invalid JSON from LLM: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[Summarizer] Non-fatal error: {e}", file=sys.stderr)
        return None


def build_searchable_text(summary_dict: dict) -> str:
    """Build the searchable text from a summary dict.

    This text is what gets embedded and stored in the vector DB.
    It concatenates title + summary + key_points for maximal search relevance.
    """
    parts = [summary_dict.get("title", "")]
    parts.append(summary_dict.get("summary", ""))
    parts.extend(summary_dict.get("key_points", []))
    return " ".join(p for p in parts if p)

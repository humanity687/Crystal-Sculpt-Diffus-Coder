# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Conversation Summarizer — Lightweight LLM probe for incremental summary generation.

Generates structured summaries for the two-level memory system.
Called after each conversation turn to produce a JSON summary.
Also provides extractive fallbacks for tool, skill, and memory indexing.
"""

import json
import hashlib
import sys
import re
from datetime import datetime


SUMMARY_PROMPT = """你是一个对话摘要探针。将以下用户-AI对话回合压缩为多维层次化摘要。

六维度体系（只包含本轮有实质内容的维度）：
- architecture（架构）：系统结构、模块划分、组件关系
- contract（契约）：接口定义、数据格式、前置/后置条件
- algorithm（算法）：流程逻辑、计算步骤、决策树
- implementation（实现）：代码细节、语言特性、库使用
- debug（调试）：错误排查、根因分析、修复方案
- meta（元认知）：计划制定、进度管理、任务拆分

要求：
1. title 不超过 15 字，精准概括本轮主题
2. main_summary 用 1 句话概述核心结论（≤40 字），聚焦"做了什么/决定了什么"
3. dimensions 列出有实质内容的维度，每个含 dim（六维度之一）和 summary（≤30 字）
   仅包含本轮实际涉及的维度，不强行填充所有六个
4. tags 列出 3-6 个关键词或技术术语

只返回 JSON 对象，不要其他内容：
{{
  "title": "...",
  "main_summary": "...",
  "dimensions": [
    {{"dim": "algorithm", "summary": "JWT采用滑动窗口，每次请求顺延有效期"}},
    {{"dim": "debug", "summary": "last_activity未含时区导致无限刷新"}}
  ],
  "tags": ["...", "..."]
}}

对话回合：
User: {user_msg}
AI: {ai_msg}"""


EXPERIENCE_GENERATION_PROMPT = """你是一个工程经验提炼师。根据以下项目的模块快照和故障记录，提炼出可跨项目复用的工程经验。

六维度参考价值：
- architecture（架构）：系统结构、模块划分、组件关系的设计教训
- contract（契约）：接口定义、数据格式、前置/后置条件的经验
- algorithm（算法）：流程逻辑、计算步骤、决策树的优化心得
- implementation（实现）：代码细节、语言特性、库使用的技巧
- debug（调试）：错误排查、根因分析、修复方案
- meta（元认知）：计划制定、进度管理、任务拆分的反省

要求：
1. 每个经验必须基于提供的材料，不能凭空编造
2. 每个经验的 reference_values 按维度给出具体建议，使用非绝对化表述（"可能是""可以考虑""建议检查"等）
3. 如果材料不足以提炼有价值的经验，返回空列表 []
4. 不生成与已有经验高度重复的内容
5. 每个经验聚焦一个明确的问题→解决→参考价值链条
6. 只输出 JSON 数组，不要其他内容

已有经验（避免重复）：
{existing_titles}

项目材料（ModuleRecord + TraceCrystal）：
{materials}

返回格式：
[
  {{
    "title": "经验标题（≤20字）",
    "summary": "一句话概述（≤50字）",
    "problem": "遇到的问题描述",
    "solution": "解决方案描述",
    "reference_values": {{
      "debug": "如果你在调试时看到...可能是...造成的，可以尝试...",
      "architecture": "在设计...时，可能需要预定义...避免...",
      "implementation": "实现时注意...",
      "contract": "接口定义中明确...",
      "algorithm": "处理流程中确保...",
      "meta": "项目规划阶段锁定..."
    }},
    "tags": ["关键词1", "关键词2"]
  }}
]
只返回有实际参考价值的维度，留空无意义的维度为 ""。
"""


def _make_memory_id(prefix: str, timestamp: str) -> str:
    """Generate a unique memory_id with short hash suffix."""
    raw = f"{prefix}:{timestamp}"
    hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:6]
    return f"{prefix}:{timestamp}-{hash_suffix}"


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter (--- delimited) and ```yaml fences from the start of text."""
    t = text.strip()
    # Strip BOM (byte order mark) that interferes with prefix detection
    if t.startswith("﻿"):
        t = t[1:].strip()
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


def _strip_markdown_inline(text: str) -> str:
    """Strip inline markdown formatting to produce natural-language-like text.

    Removes bold/italic markers, inline code, links, and image syntax.
    Does NOT remove structural elements (headings, lists) — those are
    handled separately during extraction.
    """
    t = text
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)             # bold
    t = re.sub(r"\*([^*]+)\*", r"\1", t)                 # italic
    t = re.sub(r"`([^`]+)`", r"\1", t)                   # inline code
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)        # links
    t = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", t)       # images
    t = re.sub(r"\s+", " ", t).strip()                    # normalize whitespace
    return t


def _extract_params_format(text: str, tool_name: str, heading_desc: str) -> dict | None:
    """Extract summary from Parameters-based tool README format.

    Used by tools like crystallize, add_skill, dependency, set_project
    that use: heading + description paragraph + **Parameters:** + usage guidance.
    """
    # Find the descriptive paragraph between heading and first bold section
    # The heading is already consumed; look for text before **Parameters:** or **When**
    desc_text = ""
    desc_m = re.search(
        r"(.+?)(?=\n\s*\*\*Parameters?:?\*\*|\n\s*\*\*When\b|\n\s*\*\*Sub-commands?:?\*\*|\n\s*##|\Z)",
        text, re.DOTALL,
    )
    if desc_m:
        # Skip the heading line itself if it's at the start
        raw_desc = desc_m.group(1).strip()
        # Remove the heading line (### name - desc) if still present
        if raw_desc.startswith("#"):
            lines = raw_desc.split("\n", 1)
            raw_desc = lines[1].strip() if len(lines) > 1 else ""
        desc_text = _strip_markdown_inline(raw_desc)

    # Extract **Parameters:** section
    params_text = ""
    m = re.search(r"\*\*Parameters?:?\*\*\s*\n(.+?)(?=\n\n\s*\*\*|\n\s*##|\n\s*---|\Z)", text, re.DOTALL)
    if m:
        params_text = m.group(1)

    # Extract **When to use:** section for additional context
    when_use = ""
    m = re.search(
        r"\*\*When to use(?: activate)?:?\*\*\s*\n(.+?)(?=\n\s*\*\*When NOT|\n\s*\*\*Sub-commands|\n\s*##|\Z)",
        text, re.DOTALL,
    )
    if m:
        when_lines = []
        for l in m.group(1).split("\n"):
            stripped = l.strip()
            if stripped.startswith("- "):
                stripped = stripped[2:]  # strip leading "- " bullet
            elif stripped.startswith("-"):
                stripped = stripped[1:]  # strip leading "-" (no space)
            if stripped:
                when_lines.append(_strip_markdown_inline(stripped))
        if when_lines:
            when_use = "；".join(when_lines[:3])

    # Extract **Sub-commands:** table (dependency tool)
    sub_commands = ""
    m = re.search(r"\*\*Sub-commands?:?\*\*\s*\n(.+?)(?=\n\s*\*\*When|\n\s*##|\Z)", text, re.DOTALL)
    if m:
        # Parse markdown table rows: | `cmd` | trigger | what |
        for line in m.group(1).split("\n"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 3 and cells[0].startswith("`"):
                cmd = cells[0].strip("`")
                what = cells[2] if len(cells) > 2 else cells[1]
                sub_commands += f"{cmd}: {_strip_markdown_inline(what)}；"

    # Build key_points from parameters
    key_points = []
    if params_text:
        for line in params_text.split("\n"):
            stripped = line.strip()
            # Match: - `name` (type, required): description
            pm = re.match(r"- `(\w+)`\s*\(([^)]+)\)\s*:?\s*(.+)", stripped)
            if pm:
                pname = pm.group(1)
                pdesc = _strip_markdown_inline(pm.group(3).strip())
                key_points.append(f"输入：{pname} — {pdesc[:100]}")

    # Add sub-commands as key points (for dependency)
    if sub_commands:
        key_points.append(sub_commands.strip("；")[:150])

    # Add when-to-use as notes-style key point
    if when_use:
        key_points.append(f"使用时机：{when_use[:150]}")

    # Build summary from heading description + paragraph
    summary = heading_desc or desc_text[:100]
    if desc_text and len(summary) < 30:
        combined = f"{summary}：{desc_text}"
        summary = combined[:100]
    if not summary:
        return None

    tags = [tool_name, "工具"]
    cn_keywords = re.findall(r"[一-鿿]{2,4}", f"{heading_desc} {desc_text}")
    for kw in cn_keywords[:3]:
        if kw not in tags:
            tags.append(kw)

    return {
        "title": tool_name,
        "summary": summary,
        "key_points": key_points[:8],
        "tags": tags,
    }


def _extract_tool_summary_data(text: str, tool_name: str) -> dict | None:
    """Parse tool README markdown and produce structured summary data.

    Tries lightweight LLM first for high-quality structured extraction;
    falls back to regex-based extraction if LLM is unavailable or fails.

    Returns a dict with title, summary, key_points, tags, or None.
    """
    # ── Try lightweight LLM first ──────────────────────────────────────
    try:
        from .lightweight import summarize_text
        llm_result = summarize_text(text, tool_name)
        if llm_result and llm_result.get("summary"):
            return llm_result
    except Exception:
        pass

    # ── Fallback: regex-based extraction ───────────────────────────────
    # Strip HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()

    # Extract the first heading line as description (e.g., "### `time` — Get current date and time")
    heading_match = re.search(r"#+\s*`?\w+`?\s*[—\-]\s*(.+)", text)
    heading_desc = heading_match.group(1).strip() if heading_match else ""

    # Extract Purpose
    purpose = ""
    m = re.search(r"\*\*Purpose\*\*\s*:\s*(.+?)(?=\n\s*[-*]\s+\*\*|\n\s*```|\n\n\s*##|\Z)", text, re.DOTALL)
    if m:
        purpose = _strip_markdown_inline(m.group(1).strip())

    # Extract Input — skip code blocks
    input_text = ""
    m = re.search(r"\*\*Input\*\*\s*:\s*(.+?)(?=\n\s*[-*]\s+\*\*|\n\n\s*##|\Z)", text, re.DOTALL)
    if m:
        raw_input = m.group(1)
        raw_input = re.sub(r"```[\s\S]*?```", "", raw_input)  # remove code blocks
        input_text = _strip_markdown_inline(raw_input.strip())

    # Extract Output — skip code blocks
    output_text = ""
    m = re.search(r"\*\*Output\*\*\s*:\s*(.+?)(?=\n\s*[-*]\s+\*\*|\n\n\s*##|\Z)", text, re.DOTALL)
    if m:
        raw_output = m.group(1)
        raw_output = re.sub(r"```[\s\S]*?```", "", raw_output)
        output_text = _strip_markdown_inline(raw_output.strip())

    # Extract Notes
    notes = ""
    m = re.search(r"\*\*Notes\*\*\s*:\s*(.+?)(?=\n\n\s*#|\Z)", text, re.DOTALL)
    if m:
        notes = _strip_markdown_inline(m.group(1).strip())

    # Determine if we got meaningful data from the standard format
    has_standard_data = bool(purpose or input_text or output_text)

    if has_standard_data:
        # ── Standard format (Purpose/Input/Output/Notes) ──
        summary = heading_desc or purpose
        if len(summary) > 100:
            summary = summary[:100]

        key_points = []
        if input_text:
            key_points.append(f"输入：{input_text[:120]}")
        if output_text:
            key_points.append(f"输出：{output_text[:120]}")
        if notes:
            key_points.append(f"注意：{notes[:120]}")

        tags = [tool_name, "工具"]
        cn_keywords = re.findall(r"[一-鿿]{2,4}", f"{heading_desc} {purpose}")
        for kw in cn_keywords[:3]:
            if kw not in tags:
                tags.append(kw)

        return {
            "title": tool_name,
            "summary": summary,
            "key_points": key_points,
            "tags": tags,
        }

    # ── Fallback: Parameters-based format ──
    # Tools like crystallize, add_skill, dependency, set_project use:
    #   ### name — Description\n\nParagraph\n\n**Parameters:**\n- `p` (...) : desc
    return _extract_params_format(text, tool_name, heading_desc)


def _extract_skill_summary_data(text: str, skill_name: str) -> dict | None:
    """Parse skill markdown and produce structured summary data.

    Tries lightweight LLM first for high-quality structured extraction;
    falls back to regex-based extraction if LLM is unavailable or fails.

    Returns a dict with title, summary, key_points, tags, or None.
    """
    # ── Try lightweight LLM first ──────────────────────────────────────
    try:
        from .lightweight import summarize_text
        llm_result = summarize_text(text, skill_name)
        if llm_result and llm_result.get("summary"):
            return llm_result
    except Exception:
        pass

    # ── Fallback: regex-based extraction ───────────────────────────────
    # Strip frontmatter first
    body = _strip_frontmatter(text)

    # Try to extract description from original text's YAML frontmatter
    description = ""
    fm_match = re.search(r"description\s*:\s*\|\s*\n\s*(.+?)(?=\n\n|\n\s*\n|\n\s*---)", text, re.DOTALL)
    if fm_match:
        desc_lines = []
        for line in fm_match.group(1).split("\n"):
            line = line.strip()
            if line.startswith("---") or line.startswith("触发") or line.startswith("不触发"):
                break
            if line:
                desc_lines.append(line)
        description = " ".join(desc_lines)

    if not description:
        # Fallback: extract from body after frontmatter
        description = extract_summary_from_text(body, max_sentences=2)

    if not description:
        return None

    # Build key_points from the body
    key_points = []
    # Look for numbered items or bullet points after frontmatter
    for line in body.split("\n")[:50]:
        stripped = line.strip()
        if re.match(r"^[\d]+[\.\、\)]", stripped):
            kp = _strip_markdown_inline(stripped)
            if len(kp) > 5:
                key_points.append(kp[:100])
        elif stripped.startswith("- ") and not stripped.startswith("- **"):
            kp = _strip_markdown_inline(stripped[2:])
            if len(kp) > 5 and len(key_points) < 6:
                key_points.append(kp[:100])

    # Extract tags
    tags = [skill_name]
    tags.append("技能")
    cn_keywords = re.findall(r"[一-鿿]{2,4}", description)
    for kw in cn_keywords[:4]:
        if kw not in tags:
            tags.append(kw)

    return {
        "title": skill_name,
        "summary": description[:100],
        "key_points": key_points[:5] if key_points else [description[:100]],
        "tags": tags,
    }


def extract_summary_from_text(text: str, max_sentences: int = 3) -> str:
    """Extract a simple summary from text without LLM.

    Used as fallback when no LLM client is available, or for tool/skill
    README files during incremental indexing.

    Strategy: take the first substantive paragraph after skipping
    HTML comments and markdown headers, then strip remaining inline
    formatting so the output reads like natural language.
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
        fallback = _strip_markdown_inline(text[:200].strip())
        print(f"[Summarizer] No content lines found, fallback to first 200 chars: {fallback[:80]}...", file=sys.stderr)
        return fallback

    summary = " ".join(content_lines)
    summary = _strip_markdown_inline(summary)
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
    title = summary_text[:15] if summary_text else "对话摘要"

    return {
        "memory_id": memory_id,
        "title": title,
        "main_summary": summary_text[:40] if summary_text else "",
        "dimensions": [],
        "summary": summary_text,
        "key_points": [],
        "tags": [],
        "source_file": f"raw_memories/{timestamp.replace('-', '')}.md",
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
        result_text = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences if present
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            result_text = "\n".join(lines)

        result = json.loads(result_text)

        # ── Parse new multi-dimensional format ──
        VALID_DIMS = {
            "architecture", "contract", "algorithm",
            "implementation", "debug", "meta",
        }
        main_summary = result.get("main_summary", result.get("summary", ""))
        raw_dimensions = result.get("dimensions", [])
        # Validate and normalize dimensions
        dimensions = []
        for d in raw_dimensions:
            if isinstance(d, dict) and d.get("dim") in VALID_DIMS and d.get("summary"):
                dimensions.append({
                    "dim": d["dim"],
                    "summary": d["summary"].strip()[:30],
                })

        # Build legacy fields for backward compatibility
        legacy_summary = main_summary or result.get("summary", "")
        legacy_key_points = [f"[{d['dim']}] {d['summary']}" for d in dimensions]
        # If LLM returned old-format key_points, merge them (deduped)
        old_key_points = result.get("key_points", [])
        for kp in old_key_points:
            if kp not in legacy_key_points and kp != legacy_summary:
                legacy_key_points.append(kp)

        return {
            "memory_id": memory_id,
            "title": result.get("title", "对话摘要"),
            "main_summary": main_summary,
            "dimensions": dimensions,
            "summary": legacy_summary,
            "key_points": legacy_key_points,
            "tags": result.get("tags", []),
            "source_file": f"raw_memories/{memory_id.split(':',1)[1].rsplit('-', 1)[0].replace('-', '')}.md",
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
    Concatenates title + main_summary + [dim] summary per dimension,
    with deduplication against the main summary.

    Backward compatible: falls back to legacy 'summary' and 'key_points'
    when 'main_summary' or 'dimensions' are absent.
    """
    title = summary_dict.get("title", "")
    main = summary_dict.get("main_summary", summary_dict.get("summary", ""))
    dimensions = summary_dict.get("dimensions", [])
    key_points = summary_dict.get("key_points", [])

    parts = [title] if title else []
    if main:
        parts.append(main)

    # Add dimension summaries with [dim] tags
    seen_texts = {main} if main else set()
    for d in dimensions:
        if isinstance(d, dict) and d.get("summary"):
            dim_text = f"[{d['dim']}] {d['summary']}"
            if dim_text not in seen_texts and d["summary"] not in seen_texts:
                parts.append(dim_text)
                seen_texts.add(dim_text)

    # Append legacy key_points not already covered
    for kp in key_points:
        kp_clean = kp.strip()
        if not kp_clean:
            continue
        if kp_clean in seen_texts:
            continue
        if main and (kp_clean in main or (len(main) >= 20 and main[:50] in kp_clean)):
            continue
        parts.append(kp_clean)
        seen_texts.add(kp_clean)

    return " ".join(parts)

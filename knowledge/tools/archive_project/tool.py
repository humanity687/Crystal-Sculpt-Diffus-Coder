# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
archive_project — Archive a completed project and generate ExperienceCrystals.

Two-phase workflow:
  1. action="preview": Collect ModuleRecords + TraceCrystals, generate
     ExperienceCrystal drafts via LLM. No writes — user reviews the drafts.
  2. action="confirm": Write approved ExperienceCrystals to CrystalStore,
     embed them in the vector DB, then archive the project (deprecating
     non-persistent crystals).
"""

import json
import sys

from knowledge.summarizer import EXPERIENCE_GENERATION_PROMPT

schema = {
    "type": "function",
    "function": {
        "name": "archive_project",
        "description": (
            "Archive a completed project and generate reusable ExperienceCrystals. "
            "Two-phase workflow: 'preview' (collect ModuleRecords + TraceCrystals, "
            "generate ExperienceCrystal drafts via LLM for review — no writes), "
            "'confirm' (write approved ExperienceCrystals to CrystalStore, embed in vector DB, archive project)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["preview", "confirm"], "description": "Phase: 'preview' (default) shows drafts, 'confirm' writes and archives."},
                "project_id": {"type": "string", "description": "The project to archive (required)."},
                "confirmed_experiences": {"type": "string", "description": "JSON array of confirmed ExperienceCrystal objects. Only for action='confirm'."},
            },
            "required": [],
        },
    },
}


def _collect_materials(project_id: str) -> str:
    """Collect ModuleRecords and TraceCrystals for a project as text."""
    from src import state

    store = state.crystal_store
    if not store:
        return ""

    records = store.get_module_records(project_id)
    traces = store.get_active_crystals(
        project_id=project_id, crystal_type="TraceCrystal"
    )

    parts = []

    if records:
        parts.append(f"## ModuleRecords ({len(records)} 条)")
        for r in records:
            content = r.get("content", {}) if isinstance(r.get("content"), dict) else {}
            parts.append(f"### {r.get('module', '?')}.{r.get('name', '?')}")
            parts.append(f"record_type: {content.get('record_type', '')}")
            parts.append(f"module: {r.get('module', '?')}")
            for key in ("contract_signature", "preconditions", "postconditions",
                        "algorithm_summary", "impl_files", "test_results",
                        "renegotiation_notes"):
                val = content.get(key)
                if val:
                    if isinstance(val, list):
                        parts.append(f"{key}: {', '.join(str(v) for v in val)}")
                    else:
                        parts.append(f"{key}: {val}")
            parts.append("")

    if traces:
        parts.append(f"## TraceCrystals ({len(traces)} 条)")
        for t in traces:
            content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
            parts.append(f"### {t['name']}")
            parts.append(f"symptom: {content.get('symptom', '')}")
            parts.append(f"root_cause: {content.get('root_cause', '')}")
            parts.append(f"fix: {content.get('fix', '')}")
            parts.append("")

    return "\n".join(parts) if parts else ""


def _get_existing_titles() -> str:
    """Get titles of existing persistent ExperienceCrystals for dedup."""
    from src import state

    store = state.crystal_store
    if not store:
        return ""

    existing = store.get_persistent_crystals("ExperienceCrystal")
    titles = []
    for c in existing:
        content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
        title = content.get("title", c.get("name", ""))
        if title:
            titles.append(f"- {title}")
    return "\n".join(titles) if titles else "（无已有经验）"


def _generate_experiences(project_id: str) -> str:
    """Generate ExperienceCrystal drafts via LLM. Returns formatted markdown."""
    from src import state

    materials = _collect_materials(project_id)
    if not materials:
        return "## 项目归档预览\n\n该项目没有 ModuleRecord 或 TraceCrystal，无法生成经验结晶。\n\n可调用 `archive_project(action=\"confirm\")` 直接归档（不会生成 ExperienceCrystal）。"

    existing_titles = _get_existing_titles()

    # Access LLM client from chat_agent
    agent = state.chat_agent
    if not agent or not getattr(agent, "client", None):
        return "Error: LLM client not available. Cannot generate ExperienceCrystals."

    client = agent.client
    model = getattr(agent, "model", "")

    prompt = EXPERIENCE_GENERATION_PROMPT.format(
        existing_titles=existing_titles,
        materials=materials[:8000],
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        result_text = response.choices[0].message.content.strip()

        # Strip markdown code fences
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            result_text = "\n".join(lines)

        experiences = json.loads(result_text)
    except json.JSONDecodeError as e:
        print(f"[archive_project] LLM returned invalid JSON: {e}", file=sys.stderr)
        return f"Error: LLM returned invalid JSON. Raw response:\n```\n{result_text[:1000]}\n```"
    except Exception as e:
        print(f"[archive_project] LLM call failed: {e}", file=sys.stderr)
        return f"Error: LLM generation failed: {e}"

    if not experiences:
        return (
            "## 项目归档预览\n\n"
            "LLM 分析后认为该项目没有可提炼的跨项目经验。\n\n"
            "可调用 `archive_project(action=\"confirm\")` 直接归档（不会生成 ExperienceCrystal）。"
        )

    # Format the drafts for user review
    lines = [
        "## 项目归档预览",
        "",
        f"LLM 从 {len(experiences)} 条候选经验中提炼出以下 ExperienceCrystal 草稿。",
        "请逐条审批：保留、修改或删除。",
        "",
        "审批通过后调用：",
        "```",
        "archive_project(action=\"confirm\", confirmed_experiences=<JSON数组>)",
        "```",
        "",
        "---",
        "",
    ]

    for i, exp in enumerate(experiences, 1):
        lines.append(f"### {i}. {exp.get('title', '未命名')}")
        lines.append(f"**摘要**：{exp.get('summary', '')}")
        lines.append(f"**问题**：{exp.get('problem', '')}")
        lines.append(f"**方案**：{exp.get('solution', '')}")
        lines.append("")
        lines.append("**参考价值**：")
        refs = exp.get("reference_values", {})
        for dim_label, dim_key in [
            ("架构", "architecture"), ("契约", "contract"),
            ("算法", "algorithm"), ("实现", "implementation"),
            ("调试", "debug"), ("元认知", "meta"),
        ]:
            val = refs.get(dim_key, "")
            if val and isinstance(val, str) and len(val) > 5:
                lines.append(f"  - [{dim_label}] {val}")
        tags = exp.get("tags", [])
        if tags:
            lines.append(f"**标签**：{', '.join(tags)}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def execute(action: str = "preview", project_id: str = "",
            confirmed_experiences: str = "") -> str:
    """Archive a completed project and generate reusable ExperienceCrystals.

    Two-phase workflow:
    1. preview: Show ModuleRecords + TraceCrystals, generate ExperienceCrystal drafts
    2. confirm: Write approved experiences, embed in vector DB, archive project

    Args:
        action: "preview" (default) or "confirm"
        project_id: The project to archive (required)
        confirmed_experiences: JSON array of confirmed ExperienceCrystal objects.
            Only used with action="confirm".

    Returns:
        Preview markdown or confirmation message.
    """
    from src import state

    if not project_id or not project_id.strip():
        return "Error: project_id is required."

    project_id = project_id.strip()
    store = state.crystal_store

    if not store:
        return "Error: CrystalStore is not initialized."

    # ── Preview ──
    if action == "preview":
        # Check project exists (has any crystals)
        all_crystals = store.get_active_crystals(project_id=project_id)
        if not all_crystals:
            return (
                f"Error: No active crystals found for project '{project_id}'. "
                "Verify the project_id or check that crystals were stored with crystallize()."
            )

        modules = list({c["module"] for c in all_crystals})
        module_records = store.get_module_records(project_id)
        traces = store.get_active_crystals(
            project_id=project_id, crystal_type="TraceCrystal"
        )

        header = [
            "## 项目归档预览",
            "",
            f"**项目**：{project_id}",
            f"**模块数**：{len(modules)}",
            f"**ModuleRecord**：{len(module_records)} 条",
            f"**TraceCrystal**：{len(traces)} 条",
            f"**总结晶数**：{len(all_crystals)}",
            "",
            "---",
            "",
        ]

        # Generate experiences
        experiences_text = _generate_experiences(project_id)
        return "\n".join(header) + experiences_text

    # ── Confirm ──
    if action == "confirm":
        experiences = []
        if confirmed_experiences and confirmed_experiences.strip():
            try:
                experiences = json.loads(confirmed_experiences)
                if not isinstance(experiences, list):
                    return "Error: confirmed_experiences must be a JSON array."
            except json.JSONDecodeError as e:
                return f"Error: confirmed_experiences is not valid JSON: {e}"

        # Store ExperienceCrystals
        persisted_ids = []
        for exp in experiences:
            if not isinstance(exp, dict):
                print(
                    f"[ArchiveProject] Skipping non-dict experience: {type(exp).__name__}",
                    file=sys.stderr,
                )
                continue
            # Validate required fields
            title = exp.get("title", "").strip()
            summary = exp.get("summary", "").strip()
            if not title or not summary:
                print(
                    f"[ArchiveProject] Skipping experience missing title/summary: {exp}",
                    file=sys.stderr,
                )
                continue
            refs = exp.get("reference_values", {})
            refs = exp.get("reference_values") or {}
            content = {
                "title": title,
                "summary": summary,
                "problem": exp.get("problem", ""),
                "solution": exp.get("solution", ""),
                "reference_values": {
                    "debug": refs.get("debug", ""),
                    "architecture": refs.get("architecture", ""),
                    "implementation": refs.get("implementation", ""),
                    "contract": refs.get("contract", ""),
                    "algorithm": refs.get("algorithm", ""),
                    "meta": refs.get("meta", ""),
                },
                "tags": exp.get("tags", []),
                "source_project": project_id,
            }

            try:
                crystal_id_str = store.put_crystal(
                    crystal_type="ExperienceCrystal",
                    project_id=project_id,
                    layer="L8",
                    module=exp.get("module", "__experience__"),
                    name=title[:40],
                    content=content,
                )
                # Mark as persistent
                cid = store.get_crystal_by_string_id(crystal_id_str)
                if cid:
                    store.set_persistent(cid["id"], True)
                    store.embed_experience_crystal(cid["id"])
                    persisted_ids.append(cid["id"])
            except Exception as e:
                print(f"[archive_project] Failed to store ExperienceCrystal: {e}", file=sys.stderr)

        # Archive the project
        try:
            archive_id = store.archive_project(
                project_id, persistent_crystal_ids=persisted_ids
            )
        except Exception as e:
            return f"Error during project archiving: {e}"

        # Record project lifecycle event and update journal tables
        if state.journal:
            state.journal.record_event(
                "project_lifecycle",
                project_id=project_id,
                data={"action": "archived"},
            )
            state.journal.mark_project_archived(project_id)
            state.journal.mark_modules_archived(project_id)

        return (
            f"## 项目归档完成\n\n"
            f"**项目**：{project_id}\n"
            f"**归档 ID**：{archive_id}\n"
            f"**生成 ExperienceCrystal**：{len(persisted_ids)} 条\n"
            f"**非持久结晶**：已标记为 deprecated\n"
            f"**持久结晶**：已保留并嵌入向量库，可跨项目检索\n"
        )

    return f"Error: Unknown action '{action}'. Use 'preview' or 'confirm'."

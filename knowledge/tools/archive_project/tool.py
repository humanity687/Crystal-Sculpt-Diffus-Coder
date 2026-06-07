# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
archive_project — Archive a completed project with comprehensive summarization.

Enhanced two-phase workflow:
  1. action="preview": Collect ALL crystal types + journal events + module progress,
     multi-stage LLM analysis, project report generation. No writes.
  2. action="confirm": Write approved ExperienceCrystals to CrystalStore,
     store project report (crystal + .md file), archive project, optional cleanup.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from knowledge.summarizer import (
    EXPERIENCE_GENERATION_PROMPT,
    MODULE_EXPERIENCE_PROMPT,
    CROSS_MODULE_SYNTHESIS_PROMPT,
    PROJECT_REPORT_PROMPT,
)

schema = {
    "type": "function",
    "function": {
        "name": "archive_project",
        "description": (
            "Archive a completed project with comprehensive summarization. "
            "Collects all crystal types, journal events, and module progress. "
            "Multi-stage LLM analysis for richer ExperienceCrystals. "
            "Generates project report stored as crystal + Markdown file. "
            "Two-phase: 'preview' shows drafts, 'confirm' writes and archives."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["preview", "confirm"],
                    "description": "Phase: 'preview' shows drafts, 'confirm' writes and archives.",
                },
                "project_id": {
                    "type": "string",
                    "description": "The project to archive (required).",
                },
                "prompt_hint": {
                    "type": "string",
                    "description": "Optional focus/emphasis hint to guide the LLM during experience generation and report writing. E.g. '重点关注错误处理的契约设计' or '侧重模块间接口的耦合问题'.",
                },
                "confirmed_experiences": {
                    "type": "string",
                    "description": "JSON array of confirmed ExperienceCrystal objects. Only for action='confirm'.",
                },
                "generate_report": {
                    "type": "boolean",
                    "description": "Whether to generate a project report (default true).",
                },
                "cleanup_options": {
                    "type": "string",
                    "description": (
                        "JSON object for cleanup after confirm. Keys: "
                        "trim_messages (bool), clean_raw_memories (bool), vacuum_db (bool), dry_run (bool). "
                        "Only for action='confirm'."
                    ),
                },
            },
            "required": [],
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════
#  Material Collection
# ═══════════════════════════════════════════════════════════════════════════

def _collect_all_materials(project_id: str) -> dict:
    """Collect ALL available data for a project.

    Returns dict with keys:
        project_overview, modules, timeline, cross_cutting,
        crystal_type_counts, total_chars, needs_chunking
    """
    from src import state

    store = state.crystal_store
    if not store:
        return {
            "project_overview": "(no CrystalStore)",
            "modules": [],
            "timeline": "",
            "cross_cutting": "",
            "crystal_type_counts": {},
            "total_chars": 0,
            "needs_chunking": False,
        }

    journal = state.journal

    # Group crystals by type
    all_crystals = store.get_active_crystals(project_id=project_id)
    by_type: dict[str, list[dict]] = {}
    for c in all_crystals:
        ct = c.get("crystal_type", "Unknown")
        by_type.setdefault(ct, []).append(c)

    modules_set = {c["module"] for c in all_crystals}

    project_overview = _collect_project_overview(project_id, by_type, modules_set, journal)
    per_module = [
        _collect_per_module(project_id, m, by_type, journal)
        for m in sorted(modules_set)
    ]
    timeline = _collect_timeline(project_id, journal)
    cross_cutting = _collect_cross_cutting(by_type)

    total_chars = (
        len(project_overview)
        + sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in per_module)
        + len(timeline)
        + len(cross_cutting)
    )

    return {
        "project_overview": project_overview,
        "modules": per_module,
        "timeline": timeline,
        "cross_cutting": cross_cutting,
        "crystal_type_counts": {k: len(v) for k, v in by_type.items()},
        "total_chars": total_chars,
        "needs_chunking": total_chars > 60000,
    }


def _collect_project_overview(
    project_id: str,
    by_type: dict[str, list[dict]],
    modules_set: set[str],
    journal,
) -> str:
    """Format project-level metadata and per-module progress summary."""
    lines = [f"## Project Overview: {project_id}", ""]

    if journal:
        summary = journal.get_project_summary(project_id)
        if summary:
            lines.append(f"- Created: {summary.get('created_at', '?')}")
            lines.append(f"- Last Active: {summary.get('last_active_at', '?')}")
            lines.append(f"- Status: {summary.get('status', '?')}")
            lines.append(f"- Total Modules: {summary.get('total_modules', 0)}")
            lines.append(f"- Completed Modules: {summary.get('completed_modules', 0)}")
            duration = _compute_duration(
                summary.get("created_at"), summary.get("last_active_at")
            )
            if duration:
                lines.append(f"- Duration: {duration}")
            lines.append("")

    lines.append("### Crystal Inventory")
    for ctype in sorted(by_type.keys()):
        lines.append(f"- {ctype}: {len(by_type[ctype])}")
    lines.append(f"- **Total**: {sum(len(v) for v in by_type.values())}")
    lines.append("")

    if journal:
        all_progress = journal.get_all_module_progress(project_id)
        if all_progress:
            lines.append("### Module Progress")
            lines.append(
                "| Module | Status | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 Incidents |"
            )
            lines.append(
                "|--------|--------|----|----|----|----|----|----|----|--------------|"
            )
            for mp in all_progress:
                def _fmt(ts):
                    return "Y" if ts else "-"

                lines.append(
                    f"| {mp.get('module', '?')} | {mp.get('status', '?')} "
                    f"| {_fmt(mp.get('l1_done_at'))} | {_fmt(mp.get('l2_done_at'))} "
                    f"| {_fmt(mp.get('l3_done_at'))} | {_fmt(mp.get('l4_done_at'))} "
                    f"| {_fmt(mp.get('l5_done_at'))} | {_fmt(mp.get('l6_done_at'))} "
                    f"| {_fmt(mp.get('l7_done_at'))} | {mp.get('l8_incidents', 0)} |"
                )
            lines.append("")

    return "\n".join(lines)


def _collect_per_module(
    project_id: str,
    module: str,
    by_type: dict[str, list[dict]],
    journal,
) -> dict:
    """Collect all crystals and progress for a single module."""
    result: dict = {"module": module}

    # Filter crystals belonging to this module
    module_crystals: dict[str, list[dict]] = {}
    for ctype, crystals in by_type.items():
        mod_crystals = [c for c in crystals if c.get("module") == module]
        if mod_crystals:
            module_crystals[ctype] = mod_crystals

    # ContractCrystal (L3)
    contracts = module_crystals.get("ContractCrystal", [])
    if contracts:
        c = contracts[0]
        content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
        result["contract_data"] = {
            "name": c.get("name", module),
            "signature": content.get("signature", ""),
            "preconditions": content.get("preconditions", []),
            "postconditions": content.get("postconditions", []),
            "constraints": content.get("constraints", []),
        }

    # LogicCrystal (L4/L5)
    logics = module_crystals.get("LogicCrystal", [])
    if logics:
        result["logic_data"] = []
        for lc in logics:
            content = lc.get("content", {}) if isinstance(lc.get("content"), dict) else {}
            result["logic_data"].append({
                "name": lc.get("name", ""),
                "algorithm_steps": content.get("algorithm_steps", []),
                "boundary_handling": str(content.get("boundary_handling", ""))[:500],
            })

    # ImplCrystal (L7) + SkeletonCrystal (L6)
    impls = module_crystals.get("ImplCrystal", [])
    skeletons = module_crystals.get("SkeletonCrystal", [])
    result["impl_data"] = {
        "implementations": len(impls),
        "skeletons": len(skeletons),
        "files": [],
    }
    for impl in impls:
        content = impl.get("content", {}) if isinstance(impl.get("content"), dict) else {}
        code = content.get("code", "")
        result["impl_data"]["files"].append({
            "name": impl.get("name", ""),
            "language": content.get("language", ""),
            "code_length": len(code) if isinstance(code, str) else 0,
        })

    # TraceCrystal (L8 incidents)
    traces = module_crystals.get("TraceCrystal", [])
    result["incidents"] = []
    for t in traces:
        content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
        result["incidents"].append({
            "name": t.get("name", ""),
            "symptom": content.get("symptom", ""),
            "root_cause": content.get("root_cause", ""),
            "fix": content.get("fix", ""),
        })

    # ModuleRecords
    records = module_crystals.get("ModuleRecord", [])
    result["module_records"] = [
        {
            "name": r.get("name", ""),
            "record_type": (
                r.get("content", {}).get("record_type", "")
                if isinstance(r.get("content"), dict)
                else ""
            ),
        }
        for r in records
    ]

    # Module progress from journal
    if journal:
        mp = journal.get_module_progress(project_id, module)
        if mp:
            result["progress"] = {
                k: mp.get(k)
                for k in [
                    "current_phase", "l1_done_at", "l2_done_at", "l3_done_at",
                    "l3_1_done_at", "l4_done_at", "l5_done_at", "l6_done_at",
                    "l7_done_at", "l8_incidents", "status",
                ]
            }

        events = journal.get_events(project_id=project_id, limit=30)
        module_events = [
            e for e in events
            if e.get("module") == module
            or (isinstance(e.get("data"), str) and module in str(e.get("data", "")))
        ][:10]
        result["events_summary"] = [
            f"{e['timestamp']} [{e['event_type']}] phase={e.get('phase', '')} "
            f"data={str(e.get('data', ''))[:200]}"
            for e in module_events
        ]

    return result


def _collect_timeline(project_id: str, journal) -> str:
    """Format journal events as a chronological timeline."""
    if not journal:
        return "(journal not available)"

    events = journal.get_events(project_id=project_id, limit=100)
    if not events:
        return "(no events recorded)"

    events.reverse()  # get_events returns newest first; we want oldest first

    lines = ["## Timeline", ""]
    current_date = ""

    for e in events:
        ts = e.get("timestamp", "")
        date_part = ts[:10] if ts else "?"
        if date_part != current_date:
            current_date = date_part
            lines.append(f"### {date_part}")

        event_type = e.get("event_type", "?")
        phase = e.get("phase", "")
        module = e.get("module", "")
        data = e.get("data", "{}")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"raw": str(data)[:200]}

        time_str = ts[11:19] if ts and len(ts) >= 19 else "?"

        if event_type == "phase_transition":
            lines.append(
                f"- [{time_str}] **Phase Transition**: "
                f"{data.get('from','?')} -> {data.get('to','?')}"
                f" (module: {module})"
            )
        elif event_type == "phase_rollback":
            lines.append(
                f"- [{time_str}] **Rollback**: "
                f"{data.get('from','?')} -> {data.get('to','?')}"
                f" (module: {module})"
            )
        elif event_type == "module_switch":
            lines.append(
                f"- [{time_str}] **Module Switch**: "
                f"to {module} (phase: {phase})"
            )
        elif event_type == "crystal_create":
            lines.append(
                f"- [{time_str}] Crystal: "
                f"{data.get('crystal_type','?')} "
                f"'{data.get('name','?')}' (module: {module})"
            )
        elif event_type == "project_lifecycle":
            lines.append(
                f"- [{time_str}] **Project**: {data.get('action','?')}"
            )
        else:
            lines.append(
                f"- [{time_str}] {event_type}: "
                f"{json.dumps(data, ensure_ascii=False)[:200]}"
            )

    return "\n".join(lines)


def _collect_cross_cutting(by_type: dict[str, list[dict]]) -> str:
    """Format dependency graph, architecture, and ModMap crystals."""
    lines = ["## Cross-Cutting Concerns", ""]

    dep_graphs = by_type.get("DependencyGraphCrystal", [])
    if dep_graphs:
        lines.append("### Dependency Graph")
        for dg in dep_graphs:
            content = dg.get("content", {}) if isinstance(dg.get("content"), dict) else {}
            graph = content.get("graph", {})
            if graph:
                for mod, deps in graph.items():
                    deps_str = ", ".join(deps) if deps else "(none)"
                    lines.append(f"- {mod} depends on: [{deps_str}]")
        lines.append("")

    archs = by_type.get("ArchCrystal", [])
    if archs:
        lines.append("### Architecture")
        for a in archs[:2]:
            content = a.get("content", {}) if isinstance(a.get("content"), dict) else {}
            lines.append(f"- **Summary**: {content.get('architecture_summary', 'N/A')}")
            tech = content.get("tech_stack", [])
            if tech:
                lines.append(f"- **Tech Stack**: {', '.join(tech)}")
            flow = content.get("core_flow", "")
            if flow:
                lines.append(f"- **Core Flow**: {flow}")
        lines.append("")

    modmaps = by_type.get("ModMap", [])
    if modmaps:
        lines.append("### Module Map")
        for mm in modmaps:
            content = mm.get("content", {}) if isinstance(mm.get("content"), dict) else {}
            modules = content.get("modules", [])
            if modules:
                for m in modules:
                    if isinstance(m, dict):
                        lines.append(
                            f"- {m.get('name','?')}: {m.get('responsibility','')}"
                        )
                    else:
                        lines.append(f"- {m}")
        lines.append("")

    return "\n".join(lines) if len(lines) > 2 else "(no cross-cutting data)"


def _compute_duration(created_at: str | None, last_active_at: str | None) -> str | None:
    """Compute human-readable duration between two ISO timestamps."""
    if not created_at or not last_active_at:
        return None
    try:
        start = datetime.fromisoformat(created_at)
        end = datetime.fromisoformat(last_active_at)
        delta = end - start
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() // 60)} minutes"
        elif hours < 24:
            return f"{hours:.1f} hours"
        else:
            return f"{hours / 24:.1f} days"
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Experience Generation (multi-stage LLM)
# ═══════════════════════════════════════════════════════════════════════════

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


def _strip_code_fences(text: str) -> str:
    """Strip ```json ... ``` fences from LLM output."""
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def _deduplicate_experiences(experiences: list[dict]) -> list[dict]:
    """Remove near-duplicate experiences by title substring matching."""
    seen_titles: set[str] = set()
    result = []
    for exp in experiences:
        title = exp.get("title", "").strip()
        if not title:
            continue
        norm = title.lower().replace(" ", "")
        is_dup = False
        for seen in seen_titles:
            if norm in seen or seen in norm:
                is_dup = True
                break
        if not is_dup:
            seen_titles.add(norm)
            result.append(exp)
    return result


def _generate_experiences(project_id: str, prompt_hint: str = "") -> str:
    """Generate ExperienceCrystal drafts via multi-stage LLM analysis.

    Pipeline:
      1. Collect ALL materials (_collect_all_materials)
      2. Small project: single enhanced call with EXPERIENCE_GENERATION_PROMPT
      3. Larger project: Stage 1 per-module + Stage 2 cross-module synthesis
      4. Deduplicate, format for user review

    Args:
        project_id: The project to archive.
        prompt_hint: Optional focus hint for the LLM to emphasize specific aspects.
    """
    from src import state

    materials = _collect_all_materials(project_id)

    if not materials.get("modules"):
        return (
            "## 项目归档预览\n\n"
            "该项目没有任何模块数据，无法生成经验结晶。\n\n"
            "可调用 `archive_project(action=\"confirm\")` 直接归档。"
        )

    agent = state.chat_agent
    if not agent or not getattr(agent, "client", None):
        return "Error: LLM client not available. Cannot generate ExperienceCrystals."

    client = agent.client
    model = getattr(agent, "model", "")
    existing_titles = _get_existing_titles()

    all_experiences: list[dict] = []
    total_chars = materials.get("total_chars", 0)

    if total_chars < 12000 and len(materials["modules"]) <= 2:
        # Small project: single enhanced call
        all_experiences = _single_stage_generation(
            materials, existing_titles, client, model, prompt_hint
        )
    else:
        # Stage 1: Per-module analysis
        module_experiences: list[dict] = []
        for mod_data in materials["modules"]:
            module_name = mod_data.get("module", "?")
            exps = _generate_module_experiences(
                client, model, module_name, mod_data, prompt_hint
            )
            module_experiences.extend(exps)

        # Stage 2: Cross-module synthesis
        cross_exps = _generate_cross_module_experiences(
            client, model,
            module_experiences,
            materials.get("timeline", ""),
            materials.get("cross_cutting", ""),
            materials.get("project_overview", ""),
            existing_titles,
            prompt_hint,
        )

        all_experiences = module_experiences + cross_exps

    if not all_experiences:
        return (
            "## 项目归档预览\n\n"
            "LLM 分析后认为该项目没有可提炼的跨项目经验。\n\n"
            "可调用 `archive_project(action=\"confirm\")` 直接归档。"
        )

    all_experiences = _deduplicate_experiences(all_experiences)
    return _format_experience_preview(project_id, materials, all_experiences)


def _generate_module_experiences(
    client, model: str, module: str, module_data: dict, prompt_hint: str = ""
) -> list[dict]:
    """Stage 1: LLM analysis of a single module."""
    module_json = json.dumps(module_data, ensure_ascii=False, default=str)
    if len(module_json) > 6000:
        # Truncate but note it
        module_data_truncated = dict(module_data)
        if "impl_data" in module_data_truncated:
            for f in module_data_truncated["impl_data"].get("files", []):
                f.pop("code_length", None)  # not needed by LLM
            module_data_truncated["_truncation_note"] = (
                "Implementation code truncated; structure preserved."
            )
        module_json = json.dumps(
            module_data_truncated, ensure_ascii=False, default=str
        )[:6000]

    if prompt_hint and prompt_hint.strip():
        module_json = f"**特别关注**：{prompt_hint.strip()}\n\n{module_json}"

    prompt = MODULE_EXPERIENCE_PROMPT.format(
        module=module,
        module_data=module_json,
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
        result_text = _strip_code_fences(result_text)
        experiences = json.loads(result_text)
        if isinstance(experiences, list):
            for exp in experiences:
                exp["module"] = module
            return experiences
    except Exception as e:
        print(
            f"[archive_project] Module experience generation failed for {module}: {e}",
            file=sys.stderr,
        )
    return []


def _generate_cross_module_experiences(
    client,
    model: str,
    module_experiences: list[dict],
    timeline: str,
    cross_cutting: str,
    project_overview: str,
    existing_titles: str,
    prompt_hint: str = "",
) -> list[dict]:
    """Stage 2: Cross-module synthesis."""
    mod_exp_summary = json.dumps(
        [
            {
                "title": e.get("title"),
                "summary": e.get("summary"),
                "module": e.get("module"),
                "problem": e.get("problem", "")[:200],
            }
            for e in module_experiences
        ],
        ensure_ascii=False,
        indent=2,
    )

    if prompt_hint and prompt_hint.strip():
        project_overview = f"{project_overview}\n\n**特别关注**：{prompt_hint.strip()}"

    prompt = CROSS_MODULE_SYNTHESIS_PROMPT.format(
        module_experiences=mod_exp_summary[:4000],
        timeline=timeline[:3000],
        cross_cutting=cross_cutting[:2000],
        project_overview=project_overview[:1000],
        existing_titles=existing_titles,
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
        result_text = _strip_code_fences(result_text)
        experiences = json.loads(result_text)
        if isinstance(experiences, list):
            for exp in experiences:
                exp["module"] = "__project__"
            return experiences
    except Exception as e:
        print(
            f"[archive_project] Cross-module synthesis failed: {e}",
            file=sys.stderr,
        )
    return []


def _single_stage_generation(
    materials: dict, existing_titles: str, client, model: str, prompt_hint: str = ""
) -> list[dict]:
    """Fallback: single LLM call for small projects with enhanced materials."""
    parts = [
        materials.get("project_overview", ""),
        "",
        "## Per-Module Data",
        "",
    ]
    for mod in materials.get("modules", []):
        parts.append(f"### Module: {mod.get('module', '?')}")
        parts.append(json.dumps(mod, ensure_ascii=False, default=str)[:3000])
        parts.append("")
    parts.append(materials.get("timeline", ""))
    parts.append(materials.get("cross_cutting", ""))

    combined = "\n".join(parts)[:8000]

    if prompt_hint and prompt_hint.strip():
        combined = f"**特别关注**：{prompt_hint.strip()}\n\n{combined}"

    prompt = EXPERIENCE_GENERATION_PROMPT.format(
        existing_titles=existing_titles,
        materials=combined,
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
        result_text = _strip_code_fences(result_text)
        return json.loads(result_text)
    except Exception as e:
        print(
            f"[archive_project] Single-stage generation failed: {e}",
            file=sys.stderr,
        )
        return []


def _format_experience_preview(
    project_id: str, materials: dict, experiences: list[dict]
) -> str:
    """Format experience drafts for user review."""
    lines = [
        "## 项目归档预览",
        "",
        f"**项目**：{project_id}",
        f"**总结晶**：{sum(materials.get('crystal_type_counts', {}).values())}",
        f"LLM 从多阶段分析中提炼出以下 {len(experiences)} 条 ExperienceCrystal 草稿。",
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
        module_tag = exp.get("module", "")
        header = (
            f"### {i}. {exp.get('title', '未命名')} "
            f"[{module_tag}]" if module_tag else f"### {i}. {exp.get('title', '未命名')}"
        )
        lines.append(header)
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


# ═══════════════════════════════════════════════════════════════════════════
#  Project Report Generation
# ═══════════════════════════════════════════════════════════════════════════

def _generate_project_report(
    project_id: str,
    materials: dict,
    experiences: list[dict],
    client,
    model: str,
    prompt_hint: str = "",
) -> str:
    """Generate a comprehensive project report as Markdown via LLM."""
    exp_summary = "\n".join(
        f"- **{e.get('title','?')}**: {e.get('summary','?')} [{e.get('module','?')}]"
        for e in experiences
    ) if experiences else "(no experiences generated)"

    # Build serialized materials (exclude large impl_data)
    all_materials = json.dumps(
        {
            "project_overview": materials.get("project_overview", ""),
            "modules": [
                {k: v for k, v in m.items() if k != "impl_data"}
                for m in materials.get("modules", [])
            ],
            "timeline": materials.get("timeline", ""),
            "cross_cutting": materials.get("cross_cutting", ""),
        },
        ensure_ascii=False,
        default=str,
    )

    if len(all_materials) > 12000:
        all_materials = all_materials[:12000] + "\n... (truncated)"

    try:
        if prompt_hint and prompt_hint.strip():
            # Prepend focus hint to the experiences summary
            exp_summary = f"**特别关注**：{prompt_hint.strip()}\n\n{exp_summary}"

        prompt = PROJECT_REPORT_PROMPT.format(
            all_materials=all_materials,
            experiences_summary=exp_summary,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(
            f"[archive_project] Report generation failed, using template: {e}",
            file=sys.stderr,
        )
        return _generate_report_from_template(project_id, materials, experiences)


def _generate_report_from_template(
    project_id: str, materials: dict, experiences: list[dict]
) -> str:
    """Fallback template-based project report (no LLM needed)."""
    lines = [
        f"# Project Archive Report: {project_id}",
        "",
        materials.get("project_overview", ""),
        "",
        "## Module Summary",
        "",
    ]

    for mod in materials.get("modules", []):
        module_name = mod.get("module", "?")
        lines.append(f"### {module_name}")

        contract = mod.get("contract_data")
        if contract:
            lines.append(
                f"- **Contract**: `{contract.get('name','?')}` "
                f"signature=`{contract.get('signature','?')[:200]}`"
            )

        logic = mod.get("logic_data", [])
        if logic:
            lines.append(f"- **Algorithm Steps**: {len(logic)} LogicCrystals")

        incidents = mod.get("incidents", [])
        if incidents:
            lines.append(f"- **Incidents**: {len(incidents)}")
            for inc in incidents:
                lines.append(
                    f"  - {inc.get('name','?')}: {inc.get('symptom','')[:100]}"
                )

        progress = mod.get("progress")
        if progress:
            phases_done = [
                k for k in [
                    "l1_done_at", "l2_done_at", "l3_done_at",
                    "l4_done_at", "l5_done_at", "l6_done_at", "l7_done_at",
                ] if progress.get(k)
            ]
            lines.append(f"- **Phases Completed**: {len(phases_done)}/7")

        lines.append("")

    lines.append(materials.get("timeline", ""))
    lines.append("")
    lines.append(materials.get("cross_cutting", ""))
    lines.append("")

    if experiences:
        lines.append("## Generated ExperienceCrystals")
        lines.append("")
        for i, exp in enumerate(experiences, 1):
            lines.append(
                f"{i}. **{exp.get('title','?')}**: {exp.get('summary','?')}"
            )
        lines.append("")

    return "\n".join(lines)


def _store_project_report(
    project_id: str, report_text: str, crystal_type_counts: dict
) -> str:
    """Store the project report as a persistent crystal with vector embedding."""
    from src import state

    store = state.crystal_store
    if not store:
        return "(CrystalStore not available)"

    content = {
        "title": f"Project Report: {project_id}",
        "report_markdown": report_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "crystal_inventory": crystal_type_counts,
    }

    crystal_id_str = store.put_crystal(
        crystal_type="ProjectReport",
        project_id=project_id,
        layer="L1",
        module="__report__",
        name=f"report_{project_id}",
        content=content,
    )

    cid = store.get_crystal_by_string_id(crystal_id_str)
    if cid:
        store.set_persistent(cid["id"], True)
        store.embed_project_report(cid["id"])

    return crystal_id_str


def _write_report_to_disk(project_id: str, report_text: str) -> str:
    """Write the project report to disk as a Markdown file."""
    try:
        from knowledge.config import KNOWLEDGE_ROOT

        reports_dir = KNOWLEDGE_ROOT / "project_reports"
    except ImportError:
        reports_dir = Path("knowledge/project_reports")

    reports_dir.mkdir(parents=True, exist_ok=True)
    filepath = reports_dir / f"{project_id}.md"
    filepath.write_text(report_text, encoding="utf-8")
    return str(filepath)


# ═══════════════════════════════════════════════════════════════════════════
#  Data Cleanup
# ═══════════════════════════════════════════════════════════════════════════

def _cleanup_data(project_id: str, cleanup_options: dict | None = None) -> str:
    """Optionally clean up data after successful archive.

    cleanup_options keys:
        trim_messages, clean_raw_memories, vacuum_db, dry_run
    """
    if cleanup_options is None:
        cleanup_options = {}

    dry_run = cleanup_options.get("dry_run", False)
    actions = []

    if cleanup_options.get("trim_messages"):
        result = _trim_messages_for_project(project_id, dry_run)
        actions.append(f"messages.json: {result}")

    if cleanup_options.get("clean_raw_memories"):
        result = _clean_raw_memories(project_id, dry_run)
        actions.append(f"raw_memories: {result}")

    if cleanup_options.get("vacuum_db"):
        result = _vacuum_databases(dry_run)
        actions.append(f"databases: {result}")

    if not actions:
        return "(no cleanup requested)"

    return "\n".join(actions)


def _trim_messages_for_project(project_id: str, dry_run: bool = False) -> str:
    """Remove from messages.json archived module chains."""
    from src import state

    agent = state.chat_agent
    if not agent:
        return "agent not available"

    if not hasattr(agent, 'message_meta') or not agent.message_meta:
        return "no message metadata available"

    to_remove = []
    for idx_str, meta in agent.message_meta.items():
        idx = int(idx_str)
        meta_project = meta.get("project_id", "")
        meta_archived = meta.get("archived", False)
        if meta_project == project_id and meta_archived:
            to_remove.append(idx)

    if not to_remove:
        return "no messages to trim"

    if dry_run:
        return f"would remove {len(to_remove)} messages"

    for idx in sorted(to_remove, reverse=True):
        if idx < len(agent.messages):
            agent.messages.pop(idx)

    if hasattr(agent, '_save_messages'):
        agent._save_messages()

    return f"removed {len(to_remove)} messages"


def _clean_raw_memories(project_id: str, dry_run: bool = False) -> str:
    """Remove raw memory files associated with a project."""
    try:
        from knowledge.config import RAW_MEMORIES_DIR
    except ImportError:
        RAW_MEMORIES_DIR = Path("knowledge/raw_memories")

    if not RAW_MEMORIES_DIR.exists():
        return "raw_memories directory not found"

    removed = 0
    for f in RAW_MEMORIES_DIR.glob("*.md"):
        if project_id in f.name:
            if not dry_run:
                f.unlink(missing_ok=True)
            removed += 1
            continue
        try:
            content = f.read_text(encoding="utf-8")[:500]
            if project_id in content:
                if not dry_run:
                    f.unlink(missing_ok=True)
                removed += 1
        except Exception:
            pass

    if dry_run:
        return f"would remove {removed} raw memory files"
    return f"removed {removed} raw memory files"


def _vacuum_databases(dry_run: bool = False) -> str:
    """Run VACUUM on all SQLite databases to reclaim space."""
    db_paths = [
        "./crystals.db",
        "./journal.db",
        "./knowledge/knowledge.db",
    ]

    results = []
    for db_path_str in db_paths:
        db_path = Path(db_path_str)
        if not db_path.exists():
            results.append(f"{db_path_str}: not found")
            continue

        if dry_run:
            size_mb = db_path.stat().st_size / (1024 * 1024)
            results.append(f"{db_path_str}: {size_mb:.1f} MB (would vacuum)")
            continue

        try:
            size_before = db_path.stat().st_size
            conn = sqlite3.connect(db_path_str)
            conn.execute("VACUUM")
            conn.close()
            size_after = db_path.stat().st_size
            saved_mb = (size_before - size_after) / (1024 * 1024)
            results.append(f"{db_path_str}: saved {saved_mb:.1f} MB")
        except Exception as e:
            results.append(f"{db_path_str}: VACUUM failed - {e}")

    return "; ".join(results) if results else "no databases to vacuum"


# ═══════════════════════════════════════════════════════════════════════════
#  Experience Storage
# ═══════════════════════════════════════════════════════════════════════════

def _store_experiences(project_id: str, experiences: list[dict]) -> list[int]:
    """Store validated ExperienceCrystals. Returns list of persisted crystal IDs."""
    from src import state

    store = state.crystal_store
    if not store:
        return []

    persisted_ids = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        title = exp.get("title", "").strip()
        summary = exp.get("summary", "").strip()
        if not title or not summary:
            continue

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
            "source_module": exp.get("module", "__experience__"),
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
            cid = store.get_crystal_by_string_id(crystal_id_str)
            if cid:
                store.set_persistent(cid["id"], True)
                store.embed_experience_crystal(cid["id"])
                persisted_ids.append(cid["id"])
        except Exception as e:
            print(
                f"[archive_project] Failed to store ExperienceCrystal: {e}",
                file=sys.stderr,
            )

    return persisted_ids


# ═══════════════════════════════════════════════════════════════════════════
#  Main execute()
# ═══════════════════════════════════════════════════════════════════════════

def execute(
    action: str = "preview",
    project_id: str = "",
    prompt_hint: str = "",
    confirmed_experiences: str = "",
    generate_report: bool = True,
    cleanup_options: str = "",
) -> str:
    """Archive a completed project with comprehensive summarization.

    Enhanced two-phase workflow:
    1. preview: Collect ALL materials, multi-stage LLM analysis. No writes.
    2. confirm: Write experiences, store report, archive project, optional cleanup.

    Args:
        action: "preview" (default) or "confirm"
        project_id: The project to archive (required)
        prompt_hint: Optional focus/emphasis for the LLM during experience
            generation and report writing. Guides what aspects to emphasize.
            E.g. "重点关注错误处理的契约设计，以及模块间接口的耦合问题"
        confirmed_experiences: JSON array of confirmed ExperienceCrystal objects.
            Only used with action="confirm".
        generate_report: Whether to generate a project report (default True).
        cleanup_options: JSON object with cleanup flags (only for confirm):
            {"trim_messages": true, "clean_raw_memories": true,
             "vacuum_db": false, "dry_run": false}
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
        all_crystals = store.get_active_crystals(project_id=project_id)
        if not all_crystals:
            return (
                f"Error: No active crystals found for project '{project_id}'. "
                "Verify the project_id or check that crystals were stored with crystallize()."
            )

        # Collect all materials
        materials = _collect_all_materials(project_id)
        module_names = [m.get("module", "?") for m in materials.get("modules", [])]

        header = [
            "## 项目归档预览",
            "",
            f"**项目**：{project_id}",
            f"**模块**：{', '.join(module_names)}" if module_names else "**模块**：none",
            f"**总结晶**：{len(all_crystals)}",
            "",
        ]

        for ctype, count in sorted(materials.get("crystal_type_counts", {}).items()):
            header.append(f"- {ctype}: {count}")
        header.append("")
        header.append("---")
        header.append("")

        result_parts = ["\n".join(header)]

        # Generate experiences (multi-stage)
        experiences_text = _generate_experiences(project_id, prompt_hint)
        result_parts.append(experiences_text)

        if generate_report:
            result_parts.append("")
            result_parts.append("---")
            result_parts.append("")
            result_parts.append("## 项目转储报告")
            result_parts.append("")
            result_parts.append(
                "确认归档后，LLM 将生成完整的项目归档报告，"
                "保存为 ProjectReport 结晶和 Markdown 文件。"
            )
            result_parts.append(
                "可在 confirm 时设置 `cleanup_options` 进行可选的数据清理。"
            )

        return "\n".join(result_parts)

    # ── Confirm ──
    if action == "confirm":
        # Parse experiences
        experiences = []
        if confirmed_experiences and confirmed_experiences.strip():
            try:
                experiences = json.loads(confirmed_experiences)
                if not isinstance(experiences, list):
                    return "Error: confirmed_experiences must be a JSON array."
            except json.JSONDecodeError as e:
                return f"Error: confirmed_experiences is not valid JSON: {e}"

        # Parse cleanup options
        cl_opts = {}
        if cleanup_options and cleanup_options.strip():
            try:
                cl_opts = json.loads(cleanup_options)
            except json.JSONDecodeError:
                return "Error: cleanup_options is not valid JSON."

        # 1. Store ExperienceCrystals
        persisted_ids = _store_experiences(project_id, experiences)

        # 2. Generate and store project report
        report_result = ""
        if generate_report:
            materials = _collect_all_materials(project_id)
            agent = state.chat_agent
            if agent and getattr(agent, "client", None):
                report_text = _generate_project_report(
                    project_id, materials, experiences,
                    agent.client, getattr(agent, "model", ""),
                    prompt_hint,
                )
                crystal_id = _store_project_report(
                    project_id, report_text,
                    materials.get("crystal_type_counts", {}),
                )
                disk_path = _write_report_to_disk(project_id, report_text)
                report_result = (
                    f"**项目报告水晶**：{crystal_id}\n"
                    f"**报告文件**：{disk_path}\n"
                )

        # 3. Archive the project
        try:
            archive_id = store.archive_project(
                project_id, persistent_crystal_ids=persisted_ids
            )
        except Exception as e:
            return f"Error during project archiving: {e}"

        # 4. Record journal events
        if state.journal:
            state.journal.record_event(
                "project_lifecycle",
                project_id=project_id,
                data={
                    "action": "archived",
                    "experiences_count": len(persisted_ids),
                    "report_generated": generate_report,
                },
            )
            state.journal.mark_project_archived(project_id)
            state.journal.mark_modules_archived(project_id)

        # 5. Data cleanup
        cleanup_result = ""
        if cl_opts:
            cleanup_result = _cleanup_data(project_id, cl_opts)
            if cleanup_result and cleanup_result != "(no cleanup requested)":
                cleanup_result = f"\n**数据清理**：\n{cleanup_result}\n"

        return (
            f"## 项目归档完成\n\n"
            f"**项目**：{project_id}\n"
            f"**归档 ID**：{archive_id}\n"
            f"**生成 ExperienceCrystal**：{len(persisted_ids)} 条\n"
            f"{report_result}"
            f"{cleanup_result}"
            f"**非持久结晶**：已标记为 deprecated\n"
            f"**持久结晶**：已保留并嵌入向量库，可跨项目检索\n"
        )

    return f"Error: Unknown action '{action}'. Use 'preview' or 'confirm'."

# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

import json
import os

_REVIEW_SYSTEM_PROMPT = """\
You are a senior code review expert specializing in contract-driven development.
Review engineering artifacts for quality, consistency, and completeness.

You will receive items to review. Each item has two sections:
- **[正文] Main Content**: The authoritative approval snapshot from request_approval
  (ModuleRecord). This is the PRIMARY subject of review — judge it on its own merits.
- **[摘要] Summary Context**: Structured crystals from crystallize
  (ContractCrystal, ImplCrystal, etc.). Use these as REFERENCE for
  cross-validation. For example: does an L7 implementation satisfy
  the constraints declared in its L3 ContractCrystal?

Review criteria:
1. **Completeness**: Required fields present? Edge cases covered?
2. **Consistency**: Aligned with prior phases and dependency contracts?
3. **Correctness**: Logical errors, security issues, missing constraints?
4. **Clarity**: Is the specification/code unambiguous and well-structured?

Output a structured review in Markdown. For each item include:
- Score (⭐1-5) and verdict: **Approve** / **Needs Changes** / **Reject**
- A brief summary of the main content
- Strengths (what's done well)
- Issues with severity: 🔴 Critical / ⚠️ Medium / 💡 Suggestion
- Concrete, actionable suggestions for each issue

After all items, provide an overall summary table.

Be strict but fair. False approvals waste more time than careful rejections.
Reply in the same language as the main content (Chinese for Chinese input, English for English input).\
"""

_REVIEW_USER_PROMPT = """\
Please review the following {count} approval snapshot(s).

{items}\
"""

# ── Mode-specific system prompts ─────────────────────────────────────────────

_REVIEW_CONTRACT_CONSISTENCY_SYSTEM = """\
You are a contract consistency auditor for a contract-driven engineering workflow.
All L3 contracts have been drafted for every module. Your job is to check
cross-module consistency.

Review criteria:
1. **Signature Conflicts**: Do any two modules define the same interface with
   incompatible signatures (different parameter types, counts, or return values)?
2. **Missing Dependencies**: Does module A depend on module B's interface, but
   module B's contract does not define it?
3. **Boundary Gaps**: Are there uncovered edge cases at module boundaries?
   (error propagation, null/empty inputs, timeout behavior, partial failure)
4. **Pre/Post Condition Chain**: Does module A's postcondition conflict with
   module B's precondition? Do the contracts form a valid chain?
5. **Global Invariant Violations**: Are there project-level constraints that
   any module's contract violates? (e.g., "all writes must be idempotent")

For each issue:
- Specify exactly which modules are involved
- Quote the conflicting contract text verbatim
- Rate severity: 🔴 Critical / ⚠️ Medium / 💡 Suggestion
- Propose a concrete resolution (amendment to which module's contract)

Output a structured Markdown report:
- Overall contract health summary (1 paragraph)
- Per-issue detailed findings with cross-references
- Dependency graph health (cycles? orphan modules?)
- Recommended contract amendments (if needed)
- Verdict: **Consistent** / **Needs Renegotiation** / **Blocked**

Reply in the same language as the input contracts.\
"""

_REVIEW_SINGLE_STEP_CRITIQUE_SYSTEM = """\
You are an aggressive, skeptical engineering reviewer. Your task is to find
problems, edge cases, and improvement opportunities in a single phase's output.

Unlike a balanced review, your job is narrowly focused on PICKING HOLES:

1. **Completeness gaps**: What is missing, underspecified, or hand-waved?
   Are there "TODO" placeholders or vague statements that need concrete detail?
2. **Edge cases & failure modes**: What unusual inputs, states, timing
   conditions, or error scenarios are not handled?
3. **Logical flaws**: Are there contradictions, circular reasoning, incorrect
   assumptions, or invalid inferences?
4. **Improvement opportunities**: What could be simpler, clearer, more robust,
   or more maintainable? Is there unnecessary complexity?
5. **Risk assessment**: What is the worst-case scenario if this artifact goes
   to the next phase as-is? What could go wrong?

Every issue must include:
- Clear description of the problem with specific reference to the artifact
- Severity: 🔴 Critical (blocks progress) / ⚠️ Medium (should fix) / 💡 Suggestion (nice to have)
- Concrete, actionable improvement suggestion
- "Worst case if ignored" scenario

Output a structured Markdown report:
- Overall critique summary (1 paragraph)
- Per-issue detailed analysis
- Top 3 priority fixes
- Verdict: **Pass** / **Pass with Suggestions** / **Needs Revision** / **Reject**

Be strict but constructive. The goal is to prevent problems before they propagate
to later phases. Reply in the same language as the input.\
"""

_REVIEW_ITERATION_DRIFT_SYSTEM = """\
You are a contract compliance auditor for iterative engineering. Your task is to
trace the FULL iteration chain (L3 → L4 → L5 → L6 → L7) and detect where and how
the implementation drifted from the original contract.

You will receive artifacts from every phase in chronological order. For each
adjacent pair of phases, check whether the later phase faithfully reflects the
earlier phase's intent:

1. **Contract → Algorithm (L3→L4)**:
   - Does the algorithm design preserve all pre/post conditions from L3?
   - Are any constraints weakened or ignored?
   - Are edge cases from the contract explicitly handled in the algorithm?

2. **Algorithm → Pseudocode (L4→L5)**:
   - Does the pseudocode cover all algorithm steps?
   - Are boundary handling decisions from L4 carried forward?
   - Any simplification that loses important detail?

3. **Pseudocode → Skeleton (L5→L6)**:
   - Does the code skeleton match the pseudocode structure?
   - Are function signatures consistent?
   - Any structural divergence?

4. **Skeleton → Implementation (L6→L7)**:
   - Does the final code implement the skeleton faithfully?
   - Are there undocumented additions, removed features, or changed signatures?
   - Do tests cover the original contract's postconditions?

5. **L3.1 Renegotiation Check** (if applicable):
   - If the contract was renegotiated at L3.1, are L4-L7 artifacts updated?
   - Or do they still reference the old contract?

For each drift found:
- Identify the EXACT phase where the drift first appeared
- Quote the source artifact (earlier phase) vs target artifact (later phase)
- Rate severity: 🔴 Critical (contract breach) / ⚠️ Medium (behavioral drift) / 💡 Suggestion (minor)
- Distinguish "reasonable evolution" from "accidental deviation"
- Propose fix: update later phase to match, OR recommend L3.1 renegotiation

Output a structured Markdown report:
- Drift severity summary with per-phase breakdown
- Drift timeline: which phases introduced deviations
- Per-finding detailed analysis with before/after comparison
- Verdict: **Fully Compliant** / **Minor Drift (at L{X})** / **Needs Reconciliation** / **Contract Breach**
- Recommendation: which phase(s) need revision, whether L3.1 is needed

Reply in the same language as the input.\
"""

_MAX_FILES_CHARS = 5000
_MAX_SUMMARY_CHARS = 3000
_MAX_CRYSTAL_CHARS = 3000

schema = {
    "type": "function",
    "function": {
        "name": "review_approval",
        "description": (
            "Review ModuleRecord snapshots (approval artifacts) for quality, consistency, and completeness. "
            "Uses two data layers: ModuleRecord snapshots from request_approval (main content), "
            "and crystallize crystals (summary context) for cross-reference. "
            "Filter by project_id, phase (L3, L7, etc.), module, and aspect ('contract', 'implementation', or 'all'). "
            "Returns a structured Markdown review report with per-item scores and actionable suggestions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier. Defaults to current active project."},
                "phase": {"type": "string", "description": "Filter by phase (L3, L7, etc.). Empty = all phases."},
                "module": {"type": "string", "description": "Filter by module name. Empty = all modules."},
                "aspect": {"type": "string", "enum": ["contract", "implementation", "all"], "description": "Review focus. Default: 'all'."},
            },
            "required": [],
        },
    },
}

# Crystallize crystal types to collect as summary context, keyed by snapshot phase.
# Each phase maps to a list of (crystal_type, label) pairs to query.
_PHASE_SUMMARY_CRYSTALS = {
    "L3": [
        ("ContractCrystal", "L3 Contract (formal)"),
        ("LogicCrystal", "L4 Algorithm"),
    ],
    "L3.1": [
        ("ContractCrystal", "L3 Contract (renegotiated)"),
    ],
    "L7": [
        ("ContractCrystal", "L3 Contract (reference)"),
        ("ImplCrystal", "L7 Implementation (formal)"),
    ],
    "L8": [
        ("ContractCrystal", "L3 Contract (reference)"),
        ("TraceCrystal", "L8 Trace"),
    ],
}

# Fallback crystal types for phases not explicitly listed: collect ContractCrystal
# and the crystal type most relevant to the phase.
_DEFAULT_SUMMARY_CRYSTALS = [
    ("ContractCrystal", "Contract"),
]

# Phase→Crystal mapping for single_step_critique when no ModuleRecord exists
_PHASE_CRYSTAL_FALLBACK = {
    "L0": ["ProjectCrystal"],
    "L1": ["ArchCrystal"],
    "L2": ["ModMap", "DependencyGraphCrystal"],
    "L3": ["ContractCrystal"],
    "L3.1": ["ContractCrystal"],
    "L4": ["LogicCrystal", "ContractCrystal"],
    "L5": ["SkeletonCrystal", "LogicCrystal"],
    "L6": ["SkeletonCrystal"],
    "L7": ["ImplCrystal", "ContractCrystal"],
    "L8": ["TraceCrystal", "ContractCrystal"],
}


def _read_config():
    try:
        with open("./config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _format_module_record_content(snapshot: dict) -> str:
    """Format a ModuleRecord's content for LLM review."""
    content = snapshot.get("content", {})
    if not isinstance(content, dict):
        return str(snapshot.get("content", ""))

    record_type = content.get("record_type", "")
    phase = content.get("phase", "")
    mod = content.get("module", "")
    summary = content.get("summary", "")
    body = content.get("content", "")
    files = content.get("files", {})

    lines = []
    lines.append(f"### Phase: {phase}")
    lines.append(f"### Module: {mod}")
    if summary:
        lines.append(f"### Summary: {summary}")
    lines.append("")
    lines.append("#### Main Content:")
    lines.append(body)
    lines.append("")

    if files:
        lines.append("#### Attached Files:")
        for fpath, fcontent in files.items():
            if isinstance(fcontent, str):
                truncated = fcontent[:_MAX_FILES_CHARS]
                if len(fcontent) > _MAX_FILES_CHARS:
                    truncated += "\n\n[... truncated]"
                lines.append(f"**{fpath}**:")
                lines.append("```")
                lines.append(truncated)
                lines.append("```")
                lines.append("")
    return "\n".join(lines)


def _collect_summary_crystals(store, project_id: str, phase: str, module: str) -> str:
    """Collect crystallize-produced crystals as summary context for a snapshot.

    Returns a formatted Markdown string of related crystals, or empty string.
    """
    configs = _PHASE_SUMMARY_CRYSTALS.get(phase, _DEFAULT_SUMMARY_CRYSTALS)
    parts = []

    for crystal_type, label in configs:
        try:
            crystals = store.get_active_crystals(
                project_id=project_id,
                crystal_type=crystal_type,
                module=module,
            )
        except Exception:
            continue

        if not crystals:
            continue

        for c in crystals:
            c_content = c.get("content", {})
            if not isinstance(c_content, dict):
                c_content = {}

            formatted = _format_crystal_for_review(c_content, crystal_type, label)
            parts.append(formatted)

    if not parts:
        return ""

    return "\n---\n## [摘要] Related Crystals (from crystallize)\n\n" + "\n\n".join(parts)


def _format_crystal_for_review(content: dict, crystal_type: str, label: str) -> str:
    """Format a crystallize crystal as summary context."""
    lines = [f"### {label} ({crystal_type})"]

    text = json.dumps(content, ensure_ascii=False, indent=2)
    if len(text) > _MAX_CRYSTAL_CHARS:
        text = text[:_MAX_CRYSTAL_CHARS] + "\n\n[... truncated]"

    lines.append("```json")
    lines.append(text)
    lines.append("```")
    return "\n".join(lines)


def _build_review_item(
    snapshot: dict, store, project_id: str, index: int
) -> str:
    """Build a single review item with main content and summary context."""
    content = snapshot.get("content", {})
    if not isinstance(content, dict):
        phase = snapshot.get("layer", "?")
        module = snapshot.get("module", "?")
    else:
        phase = content.get("phase", snapshot.get("layer", "?"))
        module = content.get("module", snapshot.get("module", "?"))

    parts = []

    # Header
    parts.append(f"## Item {index}: [{phase}] {module}")
    parts.append("")

    # [正文] Main Content — the authoritative ModuleRecord snapshot
    parts.append("### [正文] Main Content (from request_approval)")
    parts.append("")
    main_text = _format_module_record_content(snapshot)
    parts.append(main_text)

    # [摘要] Summary Context — crystallize crystals for cross-reference
    summary_text = _collect_summary_crystals(store, project_id, phase, module)
    if summary_text:
        parts.append(summary_text)
    else:
        parts.append("\n---\n## [摘要] Related Crystals\n\n_(none found — reviewing main content only)_")

    return "\n".join(parts)


def execute(
    project_id: str = "",
    phase: str = "",
    module: str = "",
    aspect: str = "all",
) -> str:
    """Review approval snapshots (ModuleRecords) and provide structured feedback.

    Uses two data layers:
    - **[正文] Main Content**: ModuleRecord snapshots from request_approval —
      these are the authoritative approval artifacts being reviewed.
    - **[摘要] Summary Context**: Crystals from crystallize (ContractCrystal,
      ImplCrystal, etc.) — used as cross-reference to check consistency.

    Args:
        project_id: Project identifier. Defaults to current active project.
        phase: Filter by phase (L3, L7, etc.). Empty = all phases.
        module: Filter by module name. Empty = all modules.
        aspect: Review focus — "contract", "implementation", or "all" (default).

    Returns:
        Structured Markdown review report with per-item scores, issues, and
        actionable suggestions.
    """
    from src import state

    store = state.crystal_store
    if not store:
        return "Error: CrystalStore is not initialized."

    # Resolve project_id
    pid = project_id.strip() if project_id else ""
    if not pid and state.active_project:
        pid = state.active_project.get("project_id", "")
    if not pid:
        return (
            "Error: No project_id specified and no active project. "
            "Set one via set_project() or pass project_id=..."
        )

    # Query ModuleRecord snapshots (正文)
    records = store.get_active_crystals(
        project_id=pid,
        crystal_type="ModuleRecord",
        layer=phase.strip() if phase else None,
        module=module.strip() if module else None,
    )

    if not records:
        # List available snapshots for guidance
        all_records = store.get_active_crystals(
            project_id=pid, crystal_type="ModuleRecord"
        )
        if not all_records:
            return (
                f"No ModuleRecord snapshots found for project '{pid}'.\n"
                f"Snapshots are created by request_approval at L3/L7 phases.\n"
                f"Complete some work and call request_approval first, then re-run review_approval."
            )
        lines = [
            f"No snapshots matched phase={phase or 'any'}, module={module or 'any'}.",
            f"Available snapshots in project '{pid}':",
            "",
        ]
        for r in all_records:
            c = r.get("content", {})
            if isinstance(c, dict):
                rt = c.get("record_type", r.get("layer", "?"))
                mod = c.get("module", r.get("module", "?"))
                s = c.get("summary", "")
                lines.append(f"- [{rt}] {mod}: {s}")
            else:
                lines.append(f"- {r.get('layer', '?')} / {r.get('module', '?')}")
        lines.append("")
        lines.append("Narrow your search: review_approval(phase=\"L3\", module=\"Auth\")")
        return "\n".join(lines)

    # Build review items
    items_parts = []
    for i, rec in enumerate(records, 1):
        try:
            item = _build_review_item(rec, store, pid, i)
            items_parts.append(item)
        except Exception as e:
            items_parts.append(f"## Item {i}: ERROR building review item — {e}")

    items_text = "\n\n".join(items_parts)

    # Read config for LLM
    config = _read_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    model = config.get("model", "")

    if not api_key:
        # Return raw items without LLM review — still useful
        header = (
            f"# Approval Review — Dry Run (no LLM)\n\n"
            f"**Project**: {pid}\n"
            f"**Scope**: phase={phase or 'all'}, module={module or 'all'}\n"
            f"**Snapshots**: {len(records)}\n\n"
            f"---\n\n"
            f"⚠️ No API key configured — showing raw snapshot content below.\n"
            f"Configure api_key in config to enable LLM-powered review.\n\n"
            f"---\n\n"
        )
        return header + items_text

    # Call LLM for review
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None)
        user_prompt = _REVIEW_USER_PROMPT.format(count=len(records), items=items_text)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            stream=False,
        )

        review_text = (response.choices[0].message.content or "").strip()
        if not review_text:
            return "Error: LLM returned empty response. Raw snapshots:\n\n" + items_text

        header = (
            f"# Approval Review Report\n\n"
            f"**Project**: {pid}\n"
            f"**Scope**: phase={phase or 'all'}, module={module or 'all'}, aspect={aspect}\n"
            f"**Snapshots Reviewed**: {len(records)}\n\n"
            f"---\n\n"
        )
        return header + review_text

    except Exception as e:
        return (
            f"Error: LLM review call failed: {e}\n\n"
            f"---\n\n"
            f"Raw snapshots for manual review:\n\n"
            f"{items_text}"
        )


# ── Mode 1: Contract Consistency Check ──────────────────────────────────────

def _collect_contracts_for_consistency_check(store, project_id: str) -> str:
    """Collect ALL ContractCrystals across all modules for cross-module audit."""
    contracts = store.get_active_crystals(
        project_id=project_id, crystal_type="ContractCrystal"
    )
    if not contracts:
        return ""

    lines = ["# All L3 Contracts for Cross-Module Consistency Check\n"]
    for c in contracts:
        content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
        lines.append(f"## Module: {c.get('module', '?')} — {c.get('name', '?')}")
        lines.append(f"Signature: `{content.get('signature', 'N/A')}`")
        lines.append("")
        for key, label in [
            ("preconditions", "Preconditions"),
            ("postconditions", "Postconditions"),
            ("constraints", "Constraints"),
            ("invariants", "Invariants"),
        ]:
            vals = content.get(key, [])
            if vals:
                lines.append(f"### {label}")
                for v in (vals if isinstance(vals, list) else [vals]):
                    lines.append(f"- {v}")
                lines.append("")
        lines.append("---\n")
    return "\n".join(lines)


def execute_contract_consistency(project_id: str = "", prompt_hint: str = "") -> str:
    """Mode 1: Cross-module contract consistency check.

    Audits all L3 contracts for signature conflicts, missing dependencies,
    boundary gaps, and inconsistent pre/post conditions across modules.

    Args:
        project_id: Project identifier. Defaults to active project.
        prompt_hint: Optional user guidance for the review LLM.

    Returns:
        Markdown review report.
    """
    from src import state

    store = state.crystal_store
    if not store:
        return "Error: CrystalStore is not initialized."

    pid = project_id.strip() if project_id else ""
    if not pid and state.active_project:
        pid = state.active_project.get("project_id", "")
    if not pid:
        return "Error: No project_id specified and no active project."

    contracts_text = _collect_contracts_for_consistency_check(store, pid)
    if not contracts_text:
        return (
            f"No ContractCrystals found for project '{pid}'. "
            f"Complete L3 contracting for all modules first."
        )

    # Collect dependency graph for structural context
    dep_graphs = store.get_active_crystals(
        project_id=pid, crystal_type="DependencyGraphCrystal"
    )
    if dep_graphs:
        dep_content = dep_graphs[0].get("content", {})
        mermaid = dep_content.get("mermaid", "") if isinstance(dep_content, dict) else ""
        if mermaid:
            contracts_text += (
                f"\n\n# Dependency Graph\n```mermaid\n{mermaid}\n```\n"
            )

    # Call LLM
    config = _read_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    model = config.get("model", "")

    if not api_key:
        return (
            f"# 契约一致性检查 — Dry Run (no LLM)\n\n"
            f"**Project**: {pid}\n\n"
            f"---\n\n{contracts_text}"
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None)
        user_prompt = contracts_text
        if prompt_hint:
            user_prompt += f"\n\n## Reviewer Guidance\n{prompt_hint}\n"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_CONTRACT_CONSISTENCY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            stream=False,
        )
        review_text = (response.choices[0].message.content or "").strip()
        if not review_text:
            return "Error: LLM returned empty response.\n\n" + contracts_text

        return (
            f"# 契约一致性检查 (Contract Consistency Check)\n\n"
            f"**Project**: {pid}\n\n"
            f"---\n\n{review_text}"
        )
    except Exception as e:
        return f"Error: Contract consistency check failed: {e}\n\n{contracts_text}"


# ── Mode 2: Single-Step Critique ────────────────────────────────────────────

def _collect_single_phase_data(store, project_id: str, phase: str, module: str) -> str:
    """Collect ModuleRecords + relevant crystals for a specific phase."""
    parts = []

    # ModuleRecord snapshots (正文)
    records = store.get_active_crystals(
        project_id=project_id,
        crystal_type="ModuleRecord",
        layer=phase if phase else None,
        module=module if module else None,
    )
    if records:
        parts.append(f"# ModuleRecord Snapshots for Phase {phase or 'ALL'}\n")
        parts.append(f"**Records found**: {len(records)}\n\n")
        for i, rec in enumerate(records, 1):
            parts.append(f"## Item {i}: {_format_module_record_content(rec)}")
            parts.append("---\n")

    # Relevant crystals as context (摘要)
    ctypes = _PHASE_CRYSTAL_FALLBACK.get(phase, ["ContractCrystal"])
    for ct in ctypes:
        try:
            crystals = store.get_active_crystals(
                project_id=project_id,
                crystal_type=ct,
                module=module if module else None,
            )
            if crystals:
                parts.append(f"# {ct}s (Context)\n")
                for c in crystals:
                    c_content = c.get("content", {})
                    if not isinstance(c_content, dict):
                        c_content = {}
                    formatted = _format_crystal_for_review(c_content, ct, ct)
                    parts.append(formatted)
                    parts.append("")
        except Exception:
            continue

    return "\n".join(parts)


def execute_single_step_critique(
    project_id: str = "",
    phase: str = "",
    module: str = "",
    prompt_hint: str = "",
) -> str:
    """Mode 2: Single-step critique — aggressive focused review.

    Works for ANY phase (L0-L8). Actively looks for problems, edge cases,
    and improvement opportunities. More aggressive than general review.

    Args:
        project_id: Project identifier.
        phase: Phase to critique (L0-L8).
        module: Module to critique (optional).
        prompt_hint: Optional user guidance for the review.

    Returns:
        Markdown review report.
    """
    from src import state

    store = state.crystal_store
    if not store:
        return "Error: CrystalStore is not initialized."

    pid = project_id.strip() if project_id else ""
    if not pid and state.active_project:
        pid = state.active_project.get("project_id", "")
        if not phase:
            phase = state.active_project.get("phase", "")
        if not module:
            module = state.active_project.get("module", "")
    if not pid:
        return "Error: No project_id specified and no active project."

    data_text = _collect_single_phase_data(store, pid, phase, module)
    if not data_text.strip():
        return (
            f"No data found for project '{pid}', phase={phase or '?'}, "
            f"module={module or '?'}. Complete some work and create snapshots first."
        )

    config = _read_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    model = config.get("model", "")

    if not api_key:
        return (
            f"# 单步挑刺检查 — Dry Run (no LLM)\n\n"
            f"**Project**: {pid}  |  **Phase**: {phase or 'all'}  "
            f"|  **Module**: {module or 'all'}\n\n---\n\n{data_text}"
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None)
        user_prompt = data_text
        if prompt_hint:
            user_prompt += f"\n\n## Reviewer Guidance\n{prompt_hint}\n"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_SINGLE_STEP_CRITIQUE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            stream=False,
        )
        review_text = (response.choices[0].message.content or "").strip()
        if not review_text:
            return "Error: LLM returned empty response.\n\n" + data_text

        return (
            f"# 单步挑刺检查 (Single-Step Critique)\n\n"
            f"**Project**: {pid}  |  **Phase**: {phase or 'all'}  "
            f"|  **Module**: {module or 'all'}\n\n---\n\n{review_text}"
        )
    except Exception as e:
        return f"Error: Single-step critique failed: {e}\n\n{data_text}"


# ── Mode 3: Iteration Drift Check ───────────────────────────────────────────

def _collect_iteration_chain_data(store, project_id: str, module: str) -> str:
    """Collect L3→L4→L5→L6→L7 full chain snapshots and crystals.

    Returns formatted Markdown with artifacts from each phase in chronological
    order, showing the evolution of the module through the iteration.
    """
    parts = []
    parts.append(f"# Iteration Chain: {module or 'ALL'}\n")
    parts.append("Tracing L3 → L4 → L5 → L6 → L7 for drift detection.\n")

    chain_phases = [
        ("L3", "ContractCrystal", "Contract"),
        ("L3.1", "ContractCrystal", "Contract (Renegotiated)"),
        ("L4", "LogicCrystal", "Algorithm Design"),
        ("L5", "SkeletonCrystal", "Pseudocode / Skeleton"),
        ("L6", "SkeletonCrystal", "Code Skeleton"),
        ("L7", "ImplCrystal", "Implementation"),
    ]

    found_any = False
    for phase, crystal_type, label in chain_phases:
        parts.append(f"\n## Phase {phase} — {label}\n")

        # ModuleRecord snapshot (正文)
        records = store.get_active_crystals(
            project_id=project_id,
            crystal_type="ModuleRecord",
            layer=phase,
            module=module,
        )
        if records:
            found_any = True
            parts.append(f"### [正文] ModuleRecord Snapshot\n")
            for rec in records:
                parts.append(_format_module_record_content(rec))
        else:
            parts.append(f"_(No ModuleRecord snapshot for this phase)_\n")

        # Summary crystals (摘要)
        if phase == "L5":
            # L5 may have LogicCrystal too
            for ct in [crystal_type, "LogicCrystal"]:
                try:
                    crystals = store.get_active_crystals(
                        project_id=project_id,
                        crystal_type=ct,
                        module=module,
                    )
                    if crystals:
                        parts.append(f"### [摘要] {ct}\n")
                        for c in crystals:
                            c_content = c.get("content", {})
                            if not isinstance(c_content, dict):
                                c_content = {}
                            formatted = _format_crystal_for_review(
                                c_content, ct, f"{label} ({ct})"
                            )
                            parts.append(formatted)
                except Exception:
                    continue
        else:
            try:
                crystals = store.get_active_crystals(
                    project_id=project_id,
                    crystal_type=crystal_type,
                    module=module,
                )
                if crystals:
                    found_any = True
                    parts.append(f"### [摘要] {crystal_type}\n")
                    for c in crystals:
                        c_content = c.get("content", {})
                        if not isinstance(c_content, dict):
                            c_content = {}
                        formatted = _format_crystal_for_review(
                            c_content, crystal_type, f"{label} ({crystal_type})"
                        )
                        parts.append(formatted)
            except Exception:
                continue

        parts.append("---\n")

    if not found_any:
        return ""
    return "\n".join(parts)


def execute_iteration_drift(
    project_id: str = "",
    module: str = "",
    prompt_hint: str = "",
) -> str:
    """Mode 3: Iteration drift check — L3→L7 full chain compliance audit.

    Traces the full iteration chain (L3→L4→L5→L6→L7) and detects where
    the implementation drifted from the original contract, including:
    - Progressive precondition weakening
    - Algorithm→pseudocode→skeleton→code divergence
    - L3.1 renegotiation propagation gaps
    - Scope creep beyond the original contract

    Args:
        project_id: Project identifier.
        module: Module to check. If empty, checks all modules with L3+L7.
        prompt_hint: Optional user guidance for the review LLM.

    Returns:
        Markdown review report.
    """
    from src import state

    store = state.crystal_store
    if not store:
        return "Error: CrystalStore is not initialized."

    pid = project_id.strip() if project_id else ""
    if not pid and state.active_project:
        pid = state.active_project.get("project_id", "")
        if not module:
            module = state.active_project.get("module", "")
    if not pid:
        return "Error: No project_id specified and no active project."

    if module:
        data_text = _collect_iteration_chain_data(store, pid, module)
        if not data_text:
            return (
                f"No iteration chain data found for module '{module}' in "
                f"project '{pid}'. Complete L3 through L7 first."
            )
    else:
        # Find all modules that have both L3 ContractCrystal and L7 ImplCrystal
        l3_modules = {
            c.get("module", "")
            for c in store.get_active_crystals(
                project_id=pid, crystal_type="ContractCrystal"
            )
        }
        l7_modules = {
            c.get("module", "")
            for c in store.get_active_crystals(
                project_id=pid, crystal_type="ImplCrystal"
            )
        }
        # Also check ModuleRecord
        for r in store.get_active_crystals(
            project_id=pid, crystal_type="ModuleRecord", layer="L7"
        ):
            l7_modules.add(r.get("module", ""))

        common = l3_modules & l7_modules
        if not common:
            return (
                f"No modules with both L3 ContractCrystal and L7 ImplCrystal "
                f"found in project '{pid}'.\n"
                f"L3 modules: {sorted(l3_modules) if l3_modules else 'none'}\n"
                f"L7 modules: {sorted(l7_modules) if l7_modules else 'none'}"
            )

        parts = [f"# Batch Iteration Drift Check\n"]
        parts.append(f"**Project**: {pid}\n")
        parts.append(f"**Modules**: {', '.join(sorted(common))}\n\n")
        parts.append("---\n\n")
        for mod in sorted(common):
            chain = _collect_iteration_chain_data(store, pid, mod)
            if chain:
                parts.append(chain)
                parts.append("\n\n")
        data_text = "\n".join(parts)

    config = _read_config()
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "")
    model = config.get("model", "")

    if not api_key:
        return (
            f"# 迭代脱节检查 — Dry Run (no LLM)\n\n"
            f"**Project**: {pid}  |  **Module**: {module or 'ALL'}\n\n"
            f"---\n\n{data_text}"
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None)
        user_prompt = data_text
        if prompt_hint:
            user_prompt += f"\n\n## Reviewer Guidance\n{prompt_hint}\n"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_ITERATION_DRIFT_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream=False,
        )
        review_text = (response.choices[0].message.content or "").strip()
        if not review_text:
            return "Error: LLM returned empty response.\n\n" + data_text

        return (
            f"# 迭代脱节检查 (Iteration Drift Check)\n\n"
            f"**Project**: {pid}  |  **Module**: {module or 'ALL'}\n\n"
            f"---\n\n{review_text}"
        )
    except Exception as e:
        return f"Error: Iteration drift check failed: {e}\n\n{data_text}"


# ── Mode dispatch ───────────────────────────────────────────────────────────

def execute_mode(
    mode: str,
    project_id: str = "",
    phase: str = "",
    module: str = "",
    prompt_hint: str = "",
) -> str:
    """Dispatch to the appropriate review mode.

    Args:
        mode: "contract_consistency" / "single_step_critique" / "iteration_drift"
              Supports Chinese aliases: "契约一致性检查" / "单步挑刺检查" / "迭代脱节检查"
        project_id: Project identifier.
        phase: Phase (used by single_step_critique).
        module: Module filter.
        prompt_hint: Optional user guidance injected into the review prompt.

    Returns:
        Markdown review report.
    """
    mode_lower = mode.lower().replace(" ", "_")
    if mode_lower in (
        "contract_consistency", "contract", "consistency",
        "契约一致性检查", "契约检查", "契约一致性",
    ):
        return execute_contract_consistency(project_id, prompt_hint)
    elif mode_lower in (
        "single_step_critique", "critique", "single_step",
        "单步挑刺检查", "挑刺", "单步",
    ):
        return execute_single_step_critique(project_id, phase, module, prompt_hint)
    elif mode_lower in (
        "iteration_drift", "drift", "iteration",
        "迭代脱节检查", "脱节检查", "脱节", "迭代脱节",
    ):
        return execute_iteration_drift(project_id, module, prompt_hint)
    else:
        return (
            f"Unknown review mode: '{mode}'. "
            f"Valid modes: contract_consistency, single_step_critique, iteration_drift.\n"
            f"Falling back to general review.\n\n"
            f"{execute(project_id, phase, module)}"
        )

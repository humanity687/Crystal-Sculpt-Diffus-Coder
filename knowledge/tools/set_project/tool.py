# Copyright (C) 2026 humanity687
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

def execute(action: str = "activate", project_id: str = "", phase: str = "",
            module: str = "") -> str:
    """
    Manage the crystal-aware engineering context.

    Actions:
      - "activate": Enter project mode — enables phase-aware crystal context
        injection and CrystalObserver auto-extraction in subsequent turns.
        Detects module switches and phase rollbacks, setting notices for
        context injection.
      - "deactivate": Exit project mode — stops all crystal context injection,
        phase guidance prompts, and automatic crystal extraction.

    Note: Module snapshots are now recorded via request_approval(...).
    The old "record" action has been removed.

    Args:
        action: "activate" | "deactivate"
        project_id: Unique project identifier (required for activate)
        phase: Current workflow phase L0-L8, L3.1 (required for activate)
        module: Current module name (optional for activate)

    Returns:
        Status message.
    """
    import json
    from src import state

    def _phase_num(p: str) -> float:
        if p == "L3.1":
            return 3.1
        try:
            return float(p[1:])
        except (ValueError, IndexError):
            return -1

    if action not in ("activate", "deactivate"):
        if action == "record":
            return (
                "Error: The 'record' action has been removed. "
                "Module snapshots are now recorded via request_approval(...) — "
                "call request_approval with the approval content, then use "
                "crystallize(ModuleRecord, ...) to store the snapshot."
            )
        return f"Error: Unknown action '{action}'. Valid actions: activate, deactivate."

    if action == "deactivate":
        if state.active_project is None:
            return "No active project to deactivate. Project mode is already off."
        prev_project = state.active_project.get("project_id", "unknown")
        prev_phase = state.active_project.get("phase", "?")
        state.active_project = None
        state.phase_guidance = None
        state.phase_rollback_notice = None
        state.module_switch_notice = None
        return (
            f"Project mode deactivated. Was: project_id={prev_project}, phase={prev_phase}. "
            f"Crystal context injection and CrystalObserver auto-extraction are now stopped. "
            f"Crystals remain in the database — call set_project(action=\"activate\", ...) to resume."
        )

    # ── action == "activate" ──────────────────────────────────────────────
    from knowledge.phase_context import get_phase_context

    if not project_id or not phase:
        return "Error: project_id and phase are required for activate action."

    valid_phases = {f"L{i}" for i in range(9)}
    valid_phases.add("L3.1")
    if phase not in valid_phases:
        return f"Error: Invalid phase '{phase}'. Must be L0-L8 or L3.1."

    old_project = state.active_project
    old_phase = old_project.get("phase") if old_project else None
    old_module = old_project.get("module") if old_project else None
    new_module = module.strip() if module else None
    new_phase = phase.strip()

    # ── Phase rollback detection ──────────────────────────────────────────
    if old_phase and _phase_num(new_phase) < _phase_num(old_phase):
        # Find the previous ModuleRecord for the rolled-back-to phase+module
        previous_record = None
        if state.crystal_store and new_module:
            snapshot_type = f"{new_phase}_snapshot"
            records = state.crystal_store.get_active_crystals(
                project_id=old_project["project_id"],
                crystal_type="ModuleRecord",
                module=new_module,
            )
            matching = [r for r in records
                        if r.get("content", {}).get("record_type") == snapshot_type
                        if isinstance(r.get("content"), dict)]
            if matching:
                c = matching[0].get("content", {})
                previous_record = c.get("message") or c.get("content", "")

        state.phase_rollback_notice = {
            "from": old_phase,
            "to": new_phase,
            "module": new_module or old_module or "",
            "previous_record": previous_record,
        }
    else:
        state.phase_rollback_notice = None

    # ── Phase transition detection (for proactive compression) ────────────
    # L3→L4: all contracts locked, entering per-module implementation.
    # The L3 negotiation history should be compressed to a contract catalog.
    if old_phase == "L3" and new_phase == "L4":
        state.phase_transition_notice = {"from": "L3", "to": "L4"}
    else:
        state.phase_transition_notice = None

    # ── Module switch detection ───────────────────────────────────────────
    project_id_str = project_id.strip()
    is_same_project = (
        old_project and old_project.get("project_id") == project_id_str
    )
    if is_same_project and old_module and new_module and old_module != new_module:
        state.module_switch_notice = {
            "old_module": old_module,
            "new_module": new_module,
            "phase": new_phase,
        }
    else:
        state.module_switch_notice = None

    state.active_project = {
        "project_id": project_id_str,
        "phase": new_phase,
        "module": new_module,
    }

    # Auto-inject phase-specific constraints from skill
    guidance = get_phase_context(new_phase)
    state.phase_guidance = guidance

    mod_info = f", module={module}" if module else ""
    guidance_info = f", +{len(guidance)} chars phase guidance" if guidance else ""
    switch_info = " [module switch]" if state.module_switch_notice else ""
    rollback_info = (
        f" [rollback {old_phase}→{new_phase}]" if state.phase_rollback_notice else ""
    )
    return (
        f"Active project set: project_id={project_id}, phase={phase}{mod_info}{guidance_info}."
        f"{switch_info}{rollback_info} Crystal context injection is now active for subsequent turns."
    )

# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

def execute(action: str = "activate", project_id: str = "", phase: str = "", module: str = "") -> str:
    """
    Activate or deactivate the crystal-aware engineering context.

    Use action="activate" (default) to enter project mode — this enables
    phase-aware crystal context injection and CrystalObserver auto-extraction
    in subsequent turns.

    Use action="deactivate" to exit project mode — this stops all crystal
    context injection, phase guidance prompts, and automatic crystal extraction.
    The crystal database is NOT deleted; it can be resumed later by calling
    activate with the same project_id.

    Args:
        action: "activate" (enter project mode) or "deactivate" (exit project mode)
        project_id: Unique project identifier (required for activate, ignored for deactivate)
        phase: Current workflow phase L0-L8, L3.1 (required for activate, ignored for deactivate)
        module: Current module name (optional for activate, ignored for deactivate)

    Returns:
        Status message.
    """
    from src import state

    if action == "deactivate":
        if state.active_project is None:
            return "No active project to deactivate. Project mode is already off."
        prev_project = state.active_project.get("project_id", "unknown")
        prev_phase = state.active_project.get("phase", "?")
        state.active_project = None
        state.phase_guidance = None
        return (
            f"Project mode deactivated. Was: project_id={prev_project}, phase={prev_phase}. "
            f"Crystal context injection and CrystalObserver auto-extraction are now stopped. "
            f"Crystals remain in the database — call set_project(action=\"activate\", ...) to resume."
        )

    # action == "activate"
    from knowledge.phase_context import get_phase_context

    if not project_id or not phase:
        return "Error: project_id and phase are required for activate action."

    valid_phases = {f"L{i}" for i in range(9)}
    valid_phases.add("L3.1")
    if phase not in valid_phases:
        return f"Error: Invalid phase '{phase}'. Must be L0-L8 or L3.1."

    state.active_project = {
        "project_id": project_id.strip(),
        "phase": phase.strip(),
        "module": module.strip() if module else None,
    }

    # Auto-inject phase-specific constraints from skill
    guidance = get_phase_context(phase.strip())
    state.phase_guidance = guidance

    mod_info = f", module={module}" if module else ""
    guidance_info = f", +{len(guidance)} chars phase guidance" if guidance else ""
    return (
        f"Active project set: project_id={project_id}, phase={phase}{mod_info}{guidance_info}. "
        f"Crystal context injection is now active for subsequent turns."
    )

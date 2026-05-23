# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

import json

LAYER_TO_CRYSTAL = {
    "L1": "ArchCrystal",
    "L2": "ModMap",
    "L3": "ContractCrystal",
    "L3.1": "ContractCrystal",
    "L4": "LogicCrystal",
    "L5": "LogicCrystal",
    "L6": "SkeletonCrystal",
    "L7": "ImplCrystal",
    "L8": "TraceCrystal",
}


def execute(crystal_type: str, module: str, name: str, content: str) -> str:
    """
    Store a thought crystal in CrystalStore.

    Call this at the completion of each skill layer (after user approval) to
    persist the structured engineering artifact. The crystal becomes available
    for phase-aware context injection in future turns.

    Layer to crystal type mapping:
    - L1 → ArchCrystal: architecture_summary, tech_stack, core_flow
    - L2 → ModMap: modules[], dependencies{}
    - L3 → ContractCrystal: signature, preconditions[], postconditions[], constraints[]
    - L4 → LogicCrystal: algorithm_steps[], boundary_handling{}
    - L6 → SkeletonCrystal: code_skeleton, language
    - L7 → ImplCrystal: code, tests[], language
    - L8 → TraceCrystal: symptom, root_cause, fix

    Args:
        crystal_type: Type of crystal. Must be one of:
            ArchCrystal, ModMap, ContractCrystal, LogicCrystal,
            SkeletonCrystal, ImplCrystal, TraceCrystal
        module: Module name this crystal belongs to (e.g., "Auth", "MemoryManager")
        name: Human-readable name (e.g., function name or decision title)
        content: JSON string containing the structured crystal content.
            Must be a valid JSON object with fields matching the crystal type.

    Returns:
        Crystal ID string on success, or an error message.
    """
    from src import state

    if state.crystal_store is None:
        return "Error: CrystalStore is not initialized."

    active = state.active_project
    if active is None:
        return (
            "Error: No active project. Call set_project first to activate "
            "the crystal-aware engineering workflow."
        )

    valid_types = set(LAYER_TO_CRYSTAL.values())
    if crystal_type not in valid_types:
        return (
            f"Error: Unknown crystal_type '{crystal_type}'. "
            f"Valid types: {', '.join(sorted(valid_types))}"
        )

    try:
        content_dict = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Error: content must be valid JSON. {e}"

    if not isinstance(content_dict, dict):
        return "Error: content must be a JSON object (dictionary)."

    try:
        crystal_id = state.crystal_store.put_crystal(
            crystal_type=crystal_type,
            project_id=active["project_id"],
            layer=active["phase"],
            module=module.strip(),
            name=name.strip(),
            content=content_dict,
        )
        return f"Crystal stored successfully. crystal_id={crystal_id}"
    except Exception as e:
        return f"Error storing crystal: {e}"

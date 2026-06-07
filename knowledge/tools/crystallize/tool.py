# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

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
    # Module snapshot records (called at L3/L7 completion)
    "L3_record": "ModuleRecord",
    "L7_record": "ModuleRecord",
}

# ExperienceCrystal is not tied to a specific layer — it can be created at any
# phase and persists across projects. It is valid for store/find but has no
# entry in LAYER_TO_CRYSTAL.
VALID_CRYSTAL_TYPES = set(LAYER_TO_CRYSTAL.values()) | {"ExperienceCrystal"}

# ModuleRecord content fields by record_type
MODULE_RECORD_FIELDS = {
    "L3_snapshot": ("contract_signature", "preconditions", "postconditions"),
    "L3_record": ("contract_signature", "preconditions", "postconditions"),
    "L4_snapshot": ("algorithm_steps", "boundary_handling"),
    "L4_record": ("algorithm_steps", "boundary_handling"),
    "L5_snapshot": ("pseudocode", "algorithm_steps"),
    "L5_record": ("pseudocode", "algorithm_steps"),
    "L6_snapshot": ("code_skeleton", "language"),
    "L6_record": ("code_skeleton", "language"),
    "L7_snapshot": ("impl_files", "test_results", "algorithm_summary"),
    "L7_record": ("impl_files", "test_results", "algorithm_summary"),
}

FINDABLE_TYPES = sorted(VALID_CRYSTAL_TYPES | {"ExperienceCrystal"})


def _format_crystal_summary(c: dict, index: int | None = None) -> str:
    """Format a single crystal dict as a compact summary line with recall_id."""
    prefix = f"{index}. " if index is not None else ""
    cid = c.get("id", "?")
    ctype = c.get("crystal_type", "?")
    proj = c.get("project_id", "")
    mod = c.get("module", "")
    name = c.get("name", "")
    layer = c.get("layer", "")
    vitality = c.get("vitality", 0)
    score = c.get("_score")

    # Build recall_id for use with recall(crystal_id="...")
    version = c.get("version", "1.0")
    recall_id = f"{ctype}:{proj}:{mod}.{name}:v{version}"

    parts = [f"{prefix}`{ctype}`"]
    if proj:
        parts.append(f"project={proj}")
    if mod:
        parts.append(f"module={mod}")
    if layer:
        parts.append(f"layer={layer}")
    if name:
        parts.append(f'name="{name}"')
    parts.append(f"vitality={vitality}")
    if score is not None:
        parts.append(f"score={score:.4f}")
    parts.append(f"recall_id={recall_id}")
    return " | ".join(parts)


# Layer to module_progress field mapping
LAYER_TO_PROGRESS_FIELD = {
    "L1": "l1_done_at",
    "L2": "l2_done_at",
    "L3": "l3_done_at",
    "L3.1": "l3_1_done_at",
    "L4": "l4_done_at",
    "L5": "l5_done_at",
    "L6": "l6_done_at",
    "L7": "l7_done_at",
}


def _update_module_progress_from_crystal(project_id: str, module: str,
                                          crystal_type: str, phase: str) -> None:
    """Update module_progress table based on crystal creation."""
    from src import state
    if not state.journal:
        return

    if crystal_type == "TraceCrystal":
        state.journal.increment_l8_incidents(project_id, module)
        return

    if crystal_type == "ImplCrystal":
        state.journal.upsert_module_progress(
            project_id, module,
            phase_field="l7_done_at",
            status="completed",
            current_phase="L7",
        )
        state.journal.update_project_module_counts(project_id)
        return

    if crystal_type == "ModMap":
        state.journal.upsert_module_progress(
            project_id, module,
            phase_field="l2_done_at",
            current_phase="L3",
        )
        return

    phase_field = LAYER_TO_PROGRESS_FIELD.get(phase)
    if phase_field:
        state.journal.upsert_module_progress(
            project_id, module,
            phase_field=phase_field,
            current_phase=phase,
        )


def _run_store(active: dict, crystal_type: str, module: str,
               name: str, content: str) -> str:
    """Original crystallize logic — store a crystal."""
    from src import state

    if state.crystal_store is None:
        return "Error: CrystalStore is not initialized."

    if crystal_type not in VALID_CRYSTAL_TYPES:
        return (
            f"Error: Unknown crystal_type '{crystal_type}'. "
            f"Valid types: {', '.join(sorted(VALID_CRYSTAL_TYPES))}"
        )

    try:
        content_dict = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Error: content must be valid JSON. {e}"

    if not isinstance(content_dict, dict):
        return "Error: content must be a JSON object (dictionary)."

    # ModuleRecord content validation
    if crystal_type == "ModuleRecord":
        record_type = content_dict.get("record_type", "")
        if record_type not in MODULE_RECORD_FIELDS:
            return (
                f"Error: ModuleRecord requires 'record_type' to be one of: "
                f"{', '.join(MODULE_RECORD_FIELDS.keys())}"
            )
        required_fields = MODULE_RECORD_FIELDS[record_type]
        missing = [f for f in required_fields if f not in content_dict]
        if missing:
            return (
                f"Error: ModuleRecord ({record_type}) missing required fields: "
                f"{', '.join(missing)}"
            )

    # ExperienceCrystal content validation
    if crystal_type == "ExperienceCrystal":
        if not content_dict.get("title") or not content_dict.get("summary"):
            return "Error: ExperienceCrystal requires 'title' and 'summary' fields."
        refs = content_dict.get("reference_values")
        if refs is not None and not isinstance(refs, dict):
            return "Error: ExperienceCrystal 'reference_values' must be a JSON object."
        tags = content_dict.get("tags")
        if tags is not None and not isinstance(tags, list):
            return "Error: ExperienceCrystal 'tags' must be a JSON array."

    try:
        crystal_id = state.crystal_store.put_crystal(
            crystal_type=crystal_type,
            project_id=active["project_id"],
            layer=active["phase"],
            module=module.strip(),
            name=name.strip(),
            content=content_dict,
        )

        # Record crystal_create event and update module progress
        if state.journal:
            content_preview = str(content_dict)[:300]
            state.journal.record_event(
                "crystal_create",
                project_id=active["project_id"],
                phase=active["phase"],
                module=module.strip(),
                data={
                    "crystal_id": crystal_id,
                    "crystal_type": crystal_type,
                    "name": name.strip(),
                    "content_summary": content_preview,
                },
            )
            # Update module progress based on crystal type and layer
            _update_module_progress_from_crystal(
                active["project_id"], module.strip(),
                crystal_type, active["phase"],
            )

        # ExperienceCrystal: mark persistent and embed for cross-project search
        if crystal_type == "ExperienceCrystal":
            conn = state.crystal_store._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM crystals WHERE crystal_type=? AND project_id=? "
                "AND module=? AND name=? ORDER BY id DESC LIMIT 1",
                ("ExperienceCrystal", active["project_id"],
                 module.strip(), name.strip()),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                state.crystal_store.set_persistent(row["id"], True)
                state.crystal_store.embed_experience_crystal(row["id"])
                return (
                    f"ExperienceCrystal stored successfully (persistent, cross-project). "
                    f"crystal_id={crystal_id}"
                )

        return f"Crystal stored successfully. crystal_id={crystal_id}"
    except Exception as e:
        return f"Error storing crystal: {e}"


def _run_find(active: dict | None, crystal_type: str = "",
              module: str = "", layer: str = "",
              query: str = "", limit: int = 20) -> str:
    """Find crystals by filters or vector similarity."""
    from src import state

    store = state.crystal_store
    if store is None:
        return "Error: CrystalStore is not initialized."

    ctype = crystal_type.strip() if crystal_type else None
    mod = module.strip() if module else None
    lyr = layer.strip() if layer else None
    project_id = active.get("project_id") if active else None

    # --- vector similarity path (contracts & traces) ---
    if query.strip():
        q = query.strip()
        results: list[dict] = []

        if ctype is None or ctype == "ContractCrystal":
            for c in store.find_similar_contracts(q, top_k=limit):
                if mod and c.get("module") != mod:
                    continue
                results.append(c)

        if ctype is None or ctype == "TraceCrystal":
            for c in store.find_related_traces(q, top_k=limit):
                if mod and c.get("module") != mod:
                    continue
                results.append(c)

        if ctype is None or ctype == "ExperienceCrystal":
            experiences = store.get_persistent_crystals("ExperienceCrystal")
            q_lower = q.lower()
            for c in experiences:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                title = content.get("title", c.get("name", ""))
                summary = content.get("summary", "")
                tags_str = " ".join(content.get("tags", []))
                combined = f"{title} {summary} {tags_str}".lower()
                score = sum(
                    1 for w in q_lower.split() if len(w) >= 2 and w in combined
                )
                if score > 0:
                    c["_score"] = float(score)
                    results.append(c)

        # Sort merged results by score descending
        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        results = results[:limit]

        if not results:
            return f"No crystals found matching query '{q}'.\n\n💡 Tip: Use crystallize(command=\"find\", crystal_type=\"...\", module=\"...\") without query for a structured listing."
        lines = [f"Vector search results for '{q}' ({len(results)} found):",
                  "Use recall(crystal_id=\"<recall_id>\") to view the full crystal content.",
                  ""]
        for i, c in enumerate(results, 1):
            lines.append(_format_crystal_summary(c, i))
        return "\n".join(lines)

    # --- structured filter path ---
    results = store.get_active_crystals(
        project_id=project_id,
        crystal_type=ctype,
        layer=lyr,
        module=mod,
    )
    results = results[:limit]

    if not results:
        filters = []
        if project_id:
            filters.append(f"project={project_id}")
        if ctype:
            filters.append(f"type={ctype}")
        if mod:
            filters.append(f"module={mod}")
        if lyr:
            filters.append(f"layer={lyr}")
        return f"No crystals found ({', '.join(filters)})."

    lines = [f"Found {len(results)} crystals:",
              "Use recall(crystal_id=\"<recall_id>\") to view the full crystal content.",
              ""]
    for i, c in enumerate(results, 1):
        lines.append(_format_crystal_summary(c, i))
    return "\n".join(lines)


def _run_adjust(active: dict, crystal_type: str, module: str,
                name: str, content: str) -> str:
    """Adjust an existing crystal — deprecate old, create replacement with bumped version."""
    from src import state

    if state.crystal_store is None:
        return "Error: CrystalStore is not initialized."

    if crystal_type not in VALID_CRYSTAL_TYPES:
        return (
            f"Error: Unknown crystal_type '{crystal_type}'. "
            f"Valid types: {', '.join(sorted(VALID_CRYSTAL_TYPES))}"
        )

    try:
        content_dict = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Error: content must be valid JSON. {e}"

    if not isinstance(content_dict, dict):
        return "Error: content must be a JSON object (dictionary)."

    # ModuleRecord content validation
    if crystal_type == "ModuleRecord":
        record_type = content_dict.get("record_type", "")
        if record_type not in MODULE_RECORD_FIELDS:
            return (
                f"Error: ModuleRecord requires 'record_type' to be one of: "
                f"{', '.join(MODULE_RECORD_FIELDS.keys())}"
            )
        required_fields = MODULE_RECORD_FIELDS[record_type]
        missing = [f for f in required_fields if f not in content_dict]
        if missing:
            return (
                f"Error: ModuleRecord ({record_type}) missing required fields: "
                f"{', '.join(missing)}"
            )

    # ExperienceCrystal content validation
    if crystal_type == "ExperienceCrystal":
        if not content_dict.get("title") or not content_dict.get("summary"):
            return "Error: ExperienceCrystal requires 'title' and 'summary' fields."
        refs = content_dict.get("reference_values")
        if refs is not None and not isinstance(refs, dict):
            return "Error: ExperienceCrystal 'reference_values' must be a JSON object."
        tags = content_dict.get("tags")
        if tags is not None and not isinstance(tags, list):
            return "Error: ExperienceCrystal 'tags' must be a JSON array."

    try:
        result = state.crystal_store.replace_crystal(
            crystal_type=crystal_type,
            project_id=active["project_id"],
            module=module.strip(),
            name=name.strip(),
            content=content_dict,
        )
    except Exception as e:
        return f"Error adjusting crystal: {e}"

    if result is None:
        return (
            f"Error: No active crystal found matching "
            f"type={crystal_type} module={module.strip()} name={name.strip()}. "
            f"Use crystallize(command='find', crystal_type='{crystal_type}', "
            f"module='{module.strip()}') to list existing crystals."
        )

    old_id, new_id_str = result

    if state.journal:
        content_preview = str(content_dict)[:300]
        state.journal.record_event(
            "crystal_adjust",
            project_id=active["project_id"],
            phase=active["phase"],
            module=module.strip(),
            data={
                "old_crystal_id": old_id,
                "new_crystal_id": new_id_str,
                "crystal_type": crystal_type,
                "name": name.strip(),
                "content_summary": content_preview,
            },
        )

    return (
        f"Crystal adjusted successfully. "
        f"Old crystal (id={old_id}) deprecated. "
        f"New crystal_id={new_id_str}"
    )


schema = {
    "type": "function",
    "function": {
        "name": "crystallize",
        "description": (
            "Crystal management tool. Three commands: "
            "'store' (default): store a new thought crystal in CrystalStore. "
            "Takes crystal_type (ArchCrystal, ModMap, ContractCrystal, LogicCrystal, SkeletonCrystal, "
            "ImplCrystal, TraceCrystal, ExperienceCrystal, ModuleRecord), module, name, and content (JSON string). "
            "'adjust': replace an existing crystal — deprecates the old version and creates a new one "
            "with bumped version (v1.0→v2.0). Takes the same parameters as store. "
            "Use this during L3.1 renegotiation or when revising any previously stored crystal. "
            "'find': search for existing crystals by crystal_type, module, layer, or query (vector similarity)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": ["store", "find", "adjust"], "description": "Command: 'store' (default), 'find', or 'adjust'."},
                "crystal_type": {"type": "string", "description": "Crystal type. Required for store. For find: filter by type."},
                "module": {"type": "string", "description": "Module name for the crystal."},
                "name": {"type": "string", "description": "Human-readable name for the crystal."},
                "content": {"type": "string", "description": "Crystal content as a JSON string. Required for store."},
                "query": {"type": "string", "description": "For 'find': free-text search query for vector similarity."},
                "layer": {"type": "string", "description": "For 'find': filter by layer (L0-L8, L3.1)."},
                "limit": {"type": "integer", "description": "For 'find': maximum results. Default: 20."},
            },
            "required": [],
        },
    },
}


def execute(command: str = "store",
            crystal_type: str = "", module: str = "",
            name: str = "", content: str = "",
            query: str = "", layer: str = "",
            limit: int = 20) -> str:
    """
    Crystal management tool — store, adjust, or find crystals.

    Commands:
      store  — Store a new thought crystal in CrystalStore (default, backward-compatible).
      adjust — Replace an existing crystal (deprecate old + create new with bumped version).
      find   — Search for crystals by type, module, layer, or vector similarity.

    --- store ---
    Call this at the completion of each skill layer (after user approval) to
    persist the structured engineering artifact. The crystal becomes available
    for phase-aware context injection in future turns.

    Layer to crystal type mapping:
    - L1 → ArchCrystal: architecture_summary, tech_stack, core_flow
    - L2 → ModMap: modules[], dependencies{}
    - L3 → ContractCrystal: signature, preconditions[], postconditions[], constraints[]
    - L4 → LogicCrystal: algorithm_steps[], boundary_handling{}
    - L5 → LogicCrystal: algorithm_steps[] (rigorous pseudocode, typically skipped)
    - L6 → SkeletonCrystal: code_skeleton, language
    - L7 → ImplCrystal: code, tests[], language
    - L8 → TraceCrystal: symptom, root_cause, fix
    - L3_record / L7_record → ModuleRecord: module snapshot for archiving
    - (any) → ExperienceCrystal: cross-project experience, not tied to a layer

    ModuleRecord content schema:
    - record_type: "L3_snapshot" or "L7_snapshot"
    - module, contract_signature, preconditions, postconditions (L3)
    - impl_files, test_results, algorithm_summary (L7)
    - renegotiation_notes, parent_contract_id (optional)

    ExperienceCrystal content schema:
    - title: Short experience title (required)
    - summary: 1-2 sentence description (required)
    - problem: Problem encountered (optional)
    - solution: Solution applied (optional)
    - reference_values: Dict of dimension→insight, e.g. {"debug": "...", "architecture": "..."} (optional)
    - tags: List of search keywords (optional)
    - source_project: Origin project name (optional)

    Store args:
        crystal_type: One of ArchCrystal, ModMap, ContractCrystal, LogicCrystal,
                      SkeletonCrystal, ImplCrystal, TraceCrystal, ModuleRecord,
                      ExperienceCrystal.
        module: Module name (e.g. "Auth", "MemoryManager").
        name: Human-readable name (function name or decision title).
        content: JSON string with structured crystal content.

    --- adjust ---
    Replace an existing crystal with updated content. The old crystal is deprecated
    (soft-deleted) and a new one is created with a bumped version number (v1.0→v2.0).

    Adjust args (same as store):
        crystal_type: Crystal type of the existing crystal to replace.
        module: Module name of the existing crystal.
        name: Name of the existing crystal to replace.
        content: New JSON content — completely replaces the old content.

    When to use:
    - After L3.1 contract renegotiation — replace the old ContractCrystal
    - After fixing a bug at L8 and revising the ImplCrystal
    - After phase rollback — replace the rolled-back crystal with the revised version
    - Any time a previously stored crystal needs its content updated

    The natural key (type + project + module + name) must match an existing active
    crystal. Use crystallize(command="find", ...) to list existing crystals first
    if unsure about the exact name.

    --- find ---
    Search for existing crystals. Two modes:
    1. Structured filter: filter by crystal_type, module, and/or layer.
       Returns all matching active crystals sorted by vitality.
    2. Vector similarity: add `query` to search ContractCrystal signatures,
       TraceCrystal symptoms, and ExperienceCrystal persistent entries.

    Find args:
        crystal_type: Optional filter (e.g. "ContractCrystal", "TraceCrystal").
        module:       Optional module name filter.
        layer:        Optional layer filter (e.g. "L3", "L7").
        query:        Optional semantic search query for vector similarity.
        limit:        Max results (default 20).
    """
    from src import state

    cmd = command.strip().lower() if command else "store"

    # Auto-detect find mode when query is provided but command still defaults to store
    auto_detected = False
    if cmd == "store" and query.strip() and not crystal_type.strip():
        cmd = "find"
        auto_detected = True

    if cmd == "find":
        active = state.active_project
        result = _run_find(
            active=active,
            crystal_type=crystal_type,
            module=module,
            layer=layer,
            query=query,
            limit=limit,
        )
        if auto_detected:
            result = "[Auto-switched to find mode — query provided without crystal_type]\n" + result
        return result

    if cmd == "adjust":
        if not crystal_type.strip():
            return (
                "Error: 'crystal_type' is required for adjust mode. "
                f"Valid types: {', '.join(sorted(VALID_CRYSTAL_TYPES))}."
            )
        if not content.strip():
            return (
                "Error: 'content' is required for adjust mode and must be a "
                "non-empty JSON string. Example: content='{\"signature\": \"...\"}'"
            )
        active = state.active_project
        if active is None:
            return (
                "Error: No active project. Call set_project first to activate "
                "the crystal-aware engineering workflow."
            )
        return _run_adjust(active, crystal_type, module, name, content)

    # --- store (default, backward-compatible) ---
    # Validate required parameters first (before project check, so the
    # error message pinpoints the actual problem).
    if not crystal_type.strip():
        return (
            "Error: 'crystal_type' is required for store mode. "
            f"Valid types: {', '.join(sorted(VALID_CRYSTAL_TYPES))}. "
            "To search for crystals, use command='find'."
        )
    if not content.strip():
        return (
            "Error: 'content' is required for store mode and must be a "
            "non-empty JSON string. Example: content='{\"signature\": \"...\"}'"
        )
    active = state.active_project
    if active is None:
        return (
            "Error: No active project. Call set_project first to activate "
            "the crystal-aware engineering workflow."
        )
    return _run_store(active, crystal_type, module, name, content)

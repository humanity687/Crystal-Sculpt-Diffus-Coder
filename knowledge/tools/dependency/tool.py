# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Dependency Graph Tool — Agent-driven dependency graph management.

Five sub-commands:
- define: Agent directly declares modules + dependencies, builds graph,
  stores DependencyGraphCrystal. Primary entry point — call after L2 approval.
- analyze: Build dependency graph from ModMap crystals. Fallback when
  ModMap crystals already exist and agent wants to reconcile.
- recommend: List modules ready to implement. Completed list is optional —
  when omitted, auto-derived from DependencyGraphCrystal.module_status.
  Call before starting L3 for a module.
- mark_done: Mark a module as implemented after L7 approval. Updates
  DependencyGraphCrystal.module_status and returns newly ready modules.
- impact: Given a changed module, list all downstream affected modules.
  Call at L3.1 contract renegotiation or L8 bug backtracking.
"""

import json
import sys
from knowledge.dependency import (
    build_graph,
    detect_cycles,
    topological_sort,
    compute_impact,
    recommend_next,
    generate_mermaid,
)


def execute(command: str, project_id: str, **kwargs) -> str:
    """
    Dependency graph tool — sub-command dispatch.

    Args:
        command: One of "define", "analyze", "recommend", "mark_done", "impact"
        project_id: The project identifier.
        For define: modules (list[str]), dependencies (dict[str, list[str]])
        For recommend: completed (list[str], optional) — auto-derived from
            module_status when omitted.
        For mark_done: module (str) — the module that just finished L7.
        For impact: module (str) — the module whose change impact to assess.

    Returns:
        Formatted Markdown report string.
    """
    from src import state

    if state.crystal_store is None:
        return "Error: CrystalStore is not initialized."

    if command == "define":
        modules = kwargs.get("modules", [])
        dependencies = kwargs.get("dependencies", {})
        if not modules:
            return "Error: 'modules' parameter is required for define."
        if not isinstance(modules, list):
            return "Error: 'modules' must be a list of module names."
        if not isinstance(dependencies, dict):
            return "Error: 'dependencies' must be a dict of {module: [deps...]}."
        return _do_define(project_id, modules, dependencies)

    elif command == "analyze":
        modmaps = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ModMap"
        )
        if not modmaps:
            return (
                f"No ModMap crystals found for project '{project_id}'. "
                f"Use 'define' to set up the dependency graph directly, "
                f"or complete L2 module decomposition and store a ModMap crystal first."
            )
        graph = build_graph(modmaps)
        if not graph:
            return f"Error: No modules found in ModMap crystals for project '{project_id}'."
        cycles = detect_cycles(graph)
        modmap_ids = [m["id"] for m in modmaps]
        return _do_analyze(project_id, graph, cycles, modmap_ids)

    elif command == "recommend":
        # Read dependency graph from stored DependencyGraphCrystal
        depgraphs = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        if not depgraphs:
            return (
                f"No DependencyGraphCrystal found for project '{project_id}'. "
                f"Run 'define' or 'analyze' first."
            )
        if len(depgraphs) > 1:
            print(
                f"[Dependency] Warning: {len(depgraphs)} DependencyGraphCrystals found, "
                f"using the first one",
                file=sys.stderr,
            )
        content = depgraphs[0].get("content", {})
        graph = content.get("graph", {})
        if not graph:
            return f"Error: DependencyGraphCrystal for '{project_id}' has no graph data."
        cycles = content.get("cycles", [])
        module_status = content.get("module_status", {})
        # Auto-derive completed from module_status when not explicitly provided
        completed_raw = kwargs.get("completed")
        if completed_raw is not None:
            completed = set(completed_raw) if isinstance(completed_raw, list) else set()
        else:
            completed = {m for m, s in module_status.items() if s == "implemented"}
        return _do_recommend(graph, completed, cycles)

    elif command == "mark_done":
        module = kwargs.get("module", "")
        if not module:
            return "Error: 'module' parameter is required for mark_done."
        return _do_mark_done(project_id, module)

    elif command == "impact":
        depgraphs = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        if not depgraphs:
            return (
                f"No DependencyGraphCrystal found for project '{project_id}'. "
                f"Run 'define' or 'analyze' first."
            )
        content = depgraphs[0].get("content", {})
        graph = content.get("graph", {})
        if not graph:
            return f"Error: DependencyGraphCrystal for '{project_id}' has no graph data."
        cycles = content.get("cycles", [])
        module = kwargs.get("module", "")
        if not module:
            return "Error: 'module' parameter is required for impact analysis."
        return _do_impact(graph, module, cycles)

    else:
        return (
            f"Error: Unknown command '{command}'. "
            f"Valid commands: define, analyze, recommend, mark_done, impact."
        )


def _build_graph_from_define(
    modules: list[str], dependencies: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Build adjacency list from agent-declared modules + dependencies."""
    graph: dict[str, list[str]] = {}
    for m in modules:
        graph[m] = []
        dep_list = dependencies.get(m, [])
        if isinstance(dep_list, list):
            graph[m].extend(dep_list)
    return graph


def _do_define(
    project_id: str,
    modules: list[str],
    dependencies: dict[str, list[str]],
) -> str:
    """Agent directly declares the dependency graph."""
    from src import state

    graph = _build_graph_from_define(modules, dependencies)
    cycles = detect_cycles(graph)
    order = topological_sort(graph) if not cycles else []
    mermaid = generate_mermaid(graph, cycles if cycles else None)

    # Compute module status from existing ContractCrystal/ImplCrystal
    module_status: dict[str, str] = {}
    for module in graph:
        module_normalized = module.strip()
        contracted = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal", module=module_normalized
        )
        implemented = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ImplCrystal", module=module_normalized
        )
        if implemented:
            module_status[module] = "implemented"
        elif contracted:
            module_status[module] = "contracted"
        else:
            module_status[module] = "pending"

    content = {
        "graph": graph,
        "topological_order": order,
        "cycles": [[str(n) for n in c] for c in cycles],
        "module_status": module_status,
        "source_modmap_ids": [],
        "mermaid": mermaid,
    }

    try:
        existing = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        for old in existing:
            state.crystal_store.deprecate_crystal(old["id"])

        cid = state.crystal_store.put_crystal(
            crystal_type="DependencyGraphCrystal",
            project_id=project_id,
            layer="L2",
            module="__dependency_graph__",
            name=f"depgraph_{project_id}",
            content=content,
            parent_ids=[],
        )
    except Exception as e:
        return f"Error storing DependencyGraphCrystal: {e}"

    return _format_analyze_report(project_id, graph, cycles, order, module_status, mermaid, cid)


def _do_analyze(
    project_id: str,
    graph: dict[str, list[str]],
    cycles: list[list[str]],
    modmap_ids: list[int],
) -> str:
    """Run full analysis: build graph, detect cycles, topo sort, store crystal."""
    from src import state

    order = topological_sort(graph) if not cycles else []
    mermaid = generate_mermaid(graph, cycles if cycles else None)

    # Compute module status from existing ContractCrystals and ImplCrystals
    module_status: dict[str, str] = {}
    for module in graph:
        contracted = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal", module=module
        )
        implemented = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ImplCrystal", module=module
        )
        if implemented:
            module_status[module] = "implemented"
        elif contracted:
            module_status[module] = "contracted"
        else:
            module_status[module] = "pending"

    # Store DependencyGraphCrystal
    content = {
        "graph": graph,
        "topological_order": order,
        "cycles": [[str(n) for n in c] for c in cycles],
        "module_status": module_status,
        "source_modmap_ids": modmap_ids,
        "mermaid": mermaid,
    }

    try:
        # Replace existing DependencyGraphCrystal for this project
        existing = state.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        for old in existing:
            state.crystal_store.deprecate_crystal(old["id"])

        cid = state.crystal_store.put_crystal(
            crystal_type="DependencyGraphCrystal",
            project_id=project_id,
            layer="L2",
            module="__dependency_graph__",
            name=f"depgraph_{project_id}",
            content=content,
            parent_ids=modmap_ids,
        )
    except Exception as e:
        return f"Error storing DependencyGraphCrystal: {e}"

    return _format_analyze_report(project_id, graph, cycles, order, module_status, mermaid, cid)


def _format_analyze_report(
    project_id: str,
    graph: dict[str, list[str]],
    cycles: list[list[str]],
    order: list[str],
    module_status: dict[str, str],
    mermaid: str,
    crystal_id: int,
) -> str:
    """Build the shared Markdown report for define and analyze."""
    lines = [
        "## Dependency Graph Analysis",
        "",
        f"**Project:** {project_id}",
        f"**Modules:** {len(graph)} ({', '.join(sorted(graph.keys()))})",
        f"**Crystal:** {crystal_id}",
        "",
    ]

    if cycles:
        lines.append("### ⚠️ Circular Dependencies Detected")
        lines.append("")
        for i, cycle in enumerate(cycles):
            cycle_str = " → ".join(cycle)
            lines.append(f"{i + 1}. {cycle_str}")
        lines.append("")
        lines.append(
            "Circular dependencies make the build order ambiguous. "
            "Consider breaking the cycle by extracting a shared interface "
            "or merging the interdependent modules."
        )
        lines.append("")
    else:
        lines.append("### ✅ No Circular Dependencies")
        lines.append("")

    if order:
        lines.append("### Recommended Implementation Order")
        lines.append("")
        lines.append(" → ".join(order))
        lines.append("")

    lines.append("### Module Status")
    lines.append("")
    lines.append("| Module | Status |")
    lines.append("|--------|--------|")
    for module in sorted(graph.keys()):
        status = module_status.get(module, "pending")
        emoji = {"implemented": "✅", "contracted": "📝", "pending": "⏳"}.get(status, "⏳")
        lines.append(f"| {emoji} {module} | {status} |")
    lines.append("")

    lines.append("### Dependency Graph")
    lines.append("")
    lines.append("```mermaid")
    lines.append(mermaid)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _do_recommend(
    graph: dict[str, list[str]],
    completed: set[str],
    cycles: list[list[str]],
) -> str:
    """Recommend next modules to implement."""
    ready = recommend_next(graph, completed)

    if cycles:
        cycle_nodes: set[str] = set()
        for cycle in cycles:
            cycle_nodes.update(cycle)
        # Modules in cycles can never be fully "ready" — note them
        ready = [r for r in ready if r not in cycle_nodes]

    lines = [
        "## Implementation Readiness",
        "",
        f"**Completed:** {', '.join(sorted(completed)) if completed else '(none)'}",
        "",
    ]

    if ready:
        lines.append("### Ready to Implement")
        lines.append("")
        for m in sorted(ready):
            deps = [d for d in graph.get(m, []) if d in graph]
            dep_status = "✅ all deps satisfied" if all(d in completed for d in deps) else ""
            lines.append(f"- **{m}** {dep_status}")
        lines.append("")
    else:
        lines.append(
            "No modules are ready. All remaining modules have unsatisfied dependencies "
            "or are part of a dependency cycle."
        )
        lines.append("")

    if cycles:
        cycle_strs = [" → ".join(c) for c in cycles]
        lines.append("### ⚠️ Blocked by Cycles")
        lines.append("")
        for cs in cycle_strs:
            lines.append(f"- {cs}")
        lines.append("")
        lines.append("Resolve these cycles before proceeding. Consider L3.1 contract renegotiation.")
        lines.append("")

    return "\n".join(lines)


def _do_mark_done(project_id: str, module: str) -> str:
    """Mark a module as implemented and return newly ready modules."""
    from src import state

    depgraphs = state.crystal_store.get_active_crystals(
        project_id=project_id, crystal_type="DependencyGraphCrystal"
    )
    if not depgraphs:
        return (
            f"No DependencyGraphCrystal found for project '{project_id}'. "
            f"Run 'define' or 'analyze' first."
        )

    content = depgraphs[0].get("content", {})
    graph = content.get("graph", {})
    if not graph:
        return f"Error: DependencyGraphCrystal for '{project_id}' has no graph data."
    if module not in graph:
        return (
            f"Error: Module '{module}' is not part of the dependency graph. "
            f"Known modules: {', '.join(sorted(graph.keys()))}"
        )

    cycles = content.get("cycles", [])
    module_status = content.get("module_status", {})

    # Mark the module as implemented
    old_status = module_status.get(module, "pending")
    module_status[module] = "implemented"

    # Derive completed set from updated module_status
    completed = {m for m, s in module_status.items() if s == "implemented"}
    ready = recommend_next(graph, completed)

    # Filter out modules in cycles
    if cycles:
        cycle_nodes: set[str] = set()
        for cycle in cycles:
            cycle_nodes.update(cycle)
        ready = [r for r in ready if r not in cycle_nodes]

    # Update and re-store the crystal
    content["module_status"] = module_status
    try:
        for old in depgraphs:
            state.crystal_store.deprecate_crystal(old["id"])
        cid = state.crystal_store.put_crystal(
            crystal_type="DependencyGraphCrystal",
            project_id=project_id,
            layer="L2",
            module="__dependency_graph__",
            name=f"depgraph_{project_id}",
            content=content,
            parent_ids=[],
        )
    except Exception as e:
        return f"Error storing updated DependencyGraphCrystal: {e}"

    # Format report
    lines = [
        "## Module Marked Complete",
        "",
        f"**Module:** {module}",
        f"**Status:** {old_status} → implemented ✅",
        f"**Crystal:** {cid}",
        f"**Completed so far:** {', '.join(sorted(completed)) if completed else '(none)'}",
        "",
    ]

    remaining = {m for m in graph if m not in completed}
    if not remaining:
        lines.append("### 🎉 All modules implemented!")
        lines.append("")
        lines.append("All modules are marked as implemented. Proceed to L8 integration testing.")
    elif ready:
        lines.append("### Now Ready to Implement")
        lines.append("")
        for m in sorted(ready):
            deps = [d for d in graph.get(m, []) if d in graph]
            dep_status = (
                "✅ all deps satisfied"
                if all(d in completed for d in deps)
                else ""
            )
            lines.append(f"- **{m}** {dep_status}")
        lines.append("")
    else:
        lines.append(
            "No additional modules are ready yet. Remaining modules have "
            "unsatisfied dependencies or are part of a dependency cycle."
        )
        lines.append("")

    if cycles:
        cycle_strs = [" → ".join(c) for c in cycles]
        lines.append("### ⚠️ Unresolved Cycles")
        lines.append("")
        for cs in cycle_strs:
            lines.append(f"- {cs}")
        lines.append("")

    return "\n".join(lines)


def _do_impact(
    graph: dict[str, list[str]],
    module: str,
    cycles: list[list[str]],
) -> str:
    """Analyze downstream impact of a module change."""
    affected = compute_impact(graph, module)

    lines = [
        "## Impact Analysis",
        "",
        f"**Changed module:** {module}",
        f"**Direct dependencies:** {', '.join(graph.get(module, [])) or '(none)'}",
        "",
    ]

    if affected:
        lines.append("### 🔽 Downstream Affected Modules")
        lines.append("")
        lines.append("A change to this module may require updates to:")
        lines.append("")
        for i, m in enumerate(affected):
            lines.append(f"{i + 1}. **{m}**")
        lines.append("")
        lines.append(
            f"Review these {len(affected)} modules. "
            f"If the interface contract of {module} changes, "
            f"trigger L3.1 contract renegotiation for each affected module."
        )
    else:
        lines.append("### ✅ No Downstream Impact")
        lines.append("")
        lines.append(f"No modules depend on {module}. Safe to modify.")

    lines.append("")

    if cycles and module in {n for c in cycles for n in c}:
        lines.append(
            "### ⚠️ Note: Module is part of a dependency cycle. "
            "Impact analysis may be incomplete. Break the cycle first."
        )
        lines.append("")

    return "\n".join(lines)

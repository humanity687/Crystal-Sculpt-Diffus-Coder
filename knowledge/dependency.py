# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Dependency Graph — Pure Python graph algorithms for the dependency tool.

All functions are zero-dependency, operating on plain dict/list structures.
The graph is an adjacency list: {module_name: [dependency_names...]}
"""

from collections import deque


def build_graph(modmap_crystals: list[dict]) -> dict[str, list[str]]:
    """Build adjacency list from ModMap crystals.

    Each ModMap crystal's content.dependencies dict maps module names to
    lists of dependency module names.
    """
    graph: dict[str, list[str]] = {}
    for c in modmap_crystals:
        content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
        modules = content.get("modules", [])
        deps = content.get("dependencies", {})
        for m in modules:
            name = m.get("name", m) if isinstance(m, dict) else m
            if name not in graph:
                graph[name] = []
            dep_list = deps.get(name, [])
            if isinstance(dep_list, list):
                graph[name].extend(dep_list)
    return graph


def detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Detect all cycles using DFS with color marking.

    Colors: 0 = white (unvisited), 1 = gray (in current path), 2 = black (done).
    Returns a list of cycles, each cycle is a list of module names.
    """
    color: dict[str, int] = {n: 0 for n in graph}
    parent: dict[str, str | None] = {}
    cycles: list[list[str]] = []

    def dfs(node: str):
        color[node] = 1
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue  # External dependency, skip
            if color[neighbor] == 1:
                # Back edge found — extract cycle
                cycle = [neighbor]
                path = []
                cur = node
                while cur != neighbor:
                    path.append(cur)
                    cur = parent[cur]
                cycle.extend(reversed(path))
                cycle.append(neighbor)
                cycles.append(cycle)
            elif color[neighbor] == 0:
                parent[neighbor] = node
                dfs(neighbor)
        color[node] = 2

    for n in list(graph.keys()):
        if color[n] == 0:
            parent[n] = None
            dfs(n)

    return cycles


def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm for topological ordering.

    Returns a list of modules in dependency order (dependencies first).
    Returns partial order if cycles exist (drops nodes involved in cycles).
    """
    in_degree: dict[str, int] = {n: 0 for n in graph}
    missing_deps: set[str] = set()
    for node in graph:
        for dep in graph[node]:
            if dep in in_degree:
                in_degree[node] += 1
            else:
                missing_deps.add(dep)

    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in graph:
            if node in graph[dependent] and dependent in in_degree:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    return result


def compute_impact(graph: dict[str, list[str]], module: str) -> list[str]:
    """BFS downstream traversal — find all modules that depend on `module`.

    Returns a list of affected downstream modules in dependency order.
    """
    if module not in graph:
        return []

    # Build reverse graph (dependents)
    dependents: dict[str, list[str]] = {n: [] for n in graph}
    for node in graph:
        for dep in graph[node]:
            if dep in dependents:
                dependents[dep].append(node)

    visited: set[str] = set()
    queue: deque[str] = deque([module])
    result: list[str] = []

    while queue:
        node = queue.popleft()
        for downstream in dependents.get(node, []):
            if downstream not in visited:
                visited.add(downstream)
                result.append(downstream)
                queue.append(downstream)

    return result


def recommend_next(graph: dict[str, list[str]], completed: set[str]) -> list[str]:
    """Recommend modules whose dependencies are all satisfied.

    A module is ready when all its dependencies are in the `completed` set
    and the module itself is not yet completed.
    """
    ready: list[str] = []
    for node in graph:
        if node in completed:
            continue
        deps = set(graph.get(node, []))
        internal_deps = deps & set(graph.keys())
        if internal_deps <= completed:
            ready.append(node)
    return ready


def generate_mermaid(graph: dict[str, list[str]], cycles: list[list[str]] | None = None) -> str:
    """Generate a Mermaid graph TD diagram string.

    Cycle edges are marked with dashed red lines and a warning note.
    """
    lines = ["graph TD"]
    cycle_edges: set[tuple[str, str]] = set()
    if cycles:
        for cycle in cycles:
            for i in range(len(cycle) - 1):
                cycle_edges.add((cycle[i], cycle[i + 1]))

    # Generate style line for nodes in cycles
    cycle_nodes: set[str] = set()
    if cycles:
        for cycle in cycles:
            cycle_nodes.update(cycle)
        cycle_class = ",".join(sorted(cycle_nodes))
        lines.append(f"  classDef cycle fill:#fff3cd,stroke:#dc3545,stroke-width:2px")
        lines.append(f"  class {cycle_class} cycle")

    for node in sorted(graph.keys()):
        for dep in sorted(set(graph[node])):
            edge = f"  {node} --> {dep}"
            if (node, dep) in cycle_edges:
                edge += ":::cycleEdge"
            lines.append(edge)

    if cycle_edges:
        lines.append("  linkStyle default stroke:#0d6efd")
        for i, (src, dst) in enumerate(cycle_edges):
            lines.append(f"  linkStyle {i} stroke:#dc3545,stroke-width:2px,stroke-dasharray:5")

    return "\n".join(lines)

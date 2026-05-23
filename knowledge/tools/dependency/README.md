<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### dependency - Agent-Driven Dependency Graph Management

The agent directly declares the module dependency structure, which is then analyzed, stored, and queried. The dependency graph becomes part of the engineering memory (DependencyGraphCrystal) and is automatically injected into context for downstream L3/L8 decisions.

**Parameters:**
- `command` (string, required): One of `"define"`, `"analyze"`, `"recommend"`, `"impact"`.
- `project_id` (string, required): Project identifier.
- `modules` (list[string], for `define`): All module names in the project.
- `dependencies` (dict[string, list[string]], for `define`): Dependency map `{module: [depends_on...]}`.
- `completed` (list[string], for `recommend`): Modules whose dependencies are fully satisfied.
- `module` (string, for `impact`): The module whose downstream impact to assess.

**Sub-commands:**

| Command | Trigger | What it does |
|---------|---------|-------------|
| `define` | After L2 approval (primary) | Agent declares modules + dependencies directly. Builds graph, detects cycles, stores `DependencyGraphCrystal`, returns Mermaid diagram + module status table |
| `analyze` | After L2 approval (fallback) | Reads ModMap crystals and reconciles the graph from stored data. Use when ModMap crystals already exist |
| `recommend` | Before starting L3 for a module | Given `completed` list, returns modules whose dependencies are all satisfied and ready to implement |
| `impact` | L3.1 renegotiation / L8 backtracking | Given a changed module, BFS-traces all downstream affected modules |

**When to use:**
- **define**: Immediately after the user approves L2 module decomposition — the agent declares the dependency structure it just designed. This is the **primary entry point**. The Mermaid diagram and cycle warnings become part of the approval record.
- **analyze**: Fallback when ModMap crystals are already stored and the agent wants to reconcile the graph from persisted data. Most projects should use `define`.
- **recommend**: Before starting L3 for each module, to confirm all its dependencies have been contracted (or implemented).
- **impact**: When L3.1 contract renegotiation is triggered, or when an L8 bug's root cause may affect downstream modules.

**When NOT to use:**
- Before L2 module decomposition is approved (no modules to declare)
- For single-module projects with no dependencies (skip — no graph needed)
- `define` more than once per L2, unless the module decomposition changes

**Example — `define`:**
```
dependency(
    command="define",
    project_id="my-app",
    modules=["DB", "Auth", "API"],
    dependencies={"Auth": ["DB"], "API": ["Auth", "DB"], "DB": []}
)
```

**Output format:**

All sub-commands return Markdown with structured sections. `define` and `analyze` include:
- Dependency graph as Mermaid `graph TD` (cycle edges marked with dashed red lines)
- Topological implementation order (or cycle warnings)
- Module status table (✅ implemented / 📝 contracted / ⏳ pending)
- Crystal ID of the stored `DependencyGraphCrystal`

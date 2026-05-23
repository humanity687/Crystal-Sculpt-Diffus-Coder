<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### set_project - Activate / Deactivate Crystal-Aware Engineering Context

Enter or exit the idea-to-code-sculpting project mode. When active, the agent receives phase-aware crystal context injection and CrystalObserver auto-extraction runs after each turn. When deactivated, all injection and extraction stops.

**Parameters:**
- `action` (string, optional): `"activate"` (default) to enter project mode, or `"deactivate"` to exit. When deactivating, all other parameters are ignored.
- `project_id` (string, required for activate): Unique project identifier. Use lowercase with hyphens (e.g., "my-cli-tool", "auth-service").
- `phase` (string, required for activate): Current workflow phase. Valid values: L0, L1, L2, L3, L3.1, L4, L5, L6, L7, L8.
- `module` (string, optional): Current module name. Required from L3 onward when working on a specific module.

**When to use activate:**
- At the start of L1, after the user approves the architecture summary
- At each layer transition to update the current phase
- When switching to a new module at L3
- To resume a previously deactivated project

**When to use deactivate:**
- When the user asks to stop or exit the current project
- When switching from structured engineering to simple chat / one-off tasks
- When crystal context injection is no longer needed

**When NOT to use:**
- Outside the idea-to-code-sculpting workflow (use deactivate instead)
- When no crystal context is needed (simple one-off tasks)

<!--
This file is part of Crystal-Sculpt-Diffus-Coder.
Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.
-->

### set_project - Manage Crystal-Aware Engineering Context

Enter or exit the idea-to-code-sculpting project mode. When active, the agent receives phase-aware crystal context injection and CrystalObserver auto-extraction runs after each turn.

**Actions:**

#### `activate` (default) — Enter project mode
Enables phase-aware crystal context injection and CrystalObserver auto-extraction.

- `project_id` (string, required): Unique project identifier. Lowercase with hyphens (e.g., "my-cli-tool").
- `phase` (string, required): Current workflow phase. L0-L8, L3.1.
- `module` (string, optional): Current module name. Required from L3 onward.

Phase rollback detection: if the new phase is earlier than the old phase, the system pushes a warning SSE event and auto-injects the last approved contract into the agent context.

**When to use:** L1 approval, each layer transition, module switch, resume deactivated project.

#### `deactivate` — Exit project mode
Stops all crystal context injection, phase guidance, and auto-extraction. Clears any pending rollback notice. Crystals remain in DB.

**When to use:** Exit project, switch to simple chat, no longer need crystal context. **If project is complete, call `archive_project` first.**

**Note:** Module snapshots are now recorded via `request_approval(...)` — see the request_approval tool documentation. The old `action="record"` has been removed.

**When NOT to use any action:**
- Outside the idea-to-code-sculpting workflow
- When no crystal context is needed (simple one-off tasks)

<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### crystallize - Store a Thought Crystal

Persist a structured engineering artifact into the crystal memory system. Call this at the completion of each skill layer (after user approval) so the artifact is available for phase-aware context injection in future turns and future sessions.

**Parameters:**
- `crystal_type` (string, required): Type of crystal. Must match the current layer:
  - L1 → `ArchCrystal` (architecture_summary, tech_stack, core_flow)
  - L2 → `ModMap` (modules[], dependencies{})
  - L3 → `ContractCrystal` (signature, preconditions[], postconditions[], constraints[])
  - L4 → `LogicCrystal` (algorithm_steps[], boundary_handling{})
  - L6 → `SkeletonCrystal` (code_skeleton, language)
  - L7 → `ImplCrystal` (code, tests[], language)
  - L8 → `TraceCrystal` (symptom, root_cause, fix)
- `module` (string, required): Module name this crystal belongs to.
- `name` (string, required): Human-readable name (function name, decision title).
- `content` (string, required): JSON string with structured content matching the crystal type.

**When to use:**
- After the user approves output at any skill layer (L1, L2, L3, L6)
- After completing implementation (L7) for each function
- When a bug is diagnosed (L8) — store a TraceCrystal
- Before calling crystallize, ensure you have called set_project first

**When NOT to use:**
- Before the user has approved the current layer's output
- For temporary or speculative content

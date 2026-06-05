<!--
This file is part of Crystal-Sculpt-Diffus-Coder.
Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.
-->

### `archive_project`

**Purpose**: Archive a completed project and generate reusable ExperienceCrystals for cross-project knowledge transfer. Uses a two-phase workflow to ensure user approval before any writes.

Two-phase workflow:
1. `preview` — Collect all ModuleRecords and TraceCrystals, generate ExperienceCrystal drafts via LLM. Returns formatted markdown for user review.
2. `confirm` — Write approved ExperienceCrystals to CrystalStore (persistent=1), embed them in the vector DB, then archive the project (deprecating non-persistent crystals).

After archiving, persistent crystals (ExperienceCrystals + user-marked crystals) remain active and searchable across projects.

**Input**:
- `action` (string, required): `"preview"` or `"confirm"`
- `project_id` (string, required): The project to archive. Must match the project_id used with `set_project`.
- `confirmed_experiences` (string, optional): JSON array of ExperienceCrystal objects. Only used with `action="confirm"`. Each object:
  - `title` (string): 经验标题（≤20字）
  - `summary` (string): 一句话概述（≤50字）
  - `problem` (string): 遇到的问题描述
  - `solution` (string): 解决方案描述
  - `reference_values` (object): 按六维度的参考建议 `{debug, architecture, implementation, contract, algorithm, meta}`
  - `tags` (array): 关键词列表

**Output**: Formatted markdown showing archive status and generated ExperienceCrystals.

**Notes**:
- Requires `set_project` to have been used during the project.
- ExperienceCrystals are generated from ModuleRecords and TraceCrystals — ensure these were recorded at L3/L7 completion.
- The preview step deduplicates against existing persistent ExperienceCrystals by title.
- Non-persistent crystals (all temporary crystals from the project) are marked as deprecated after archiving.
- ExperienceCrystals are embedded in the vector DB with doc_type="experience_crystal" (weight 0.6) for cross-project search.
- User-marked persistent crystals (via `crystallize` with future persistence flag) survive archiving.

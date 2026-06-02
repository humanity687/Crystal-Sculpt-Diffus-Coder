<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### `recall`

**Purpose**: Fetch original document or crystal content by ID. This is the second level of the two-level summary memory system. Supports two ID types:
- `memory_id` — resolves to files on disk (conversation backups, tool docs, skill docs)
- `crystal_id` — resolves from CrystalStore (ExperienceCrystal and other crystal types)

**Input**:
- `memory_id` (string, optional if crystal_id provided): Unique identifier from a summary shown in context. Formats:
  - `conv:20260115-143022-a1b2c3` — conversation memory
  - `tool:read` — tool documentation
  - `skill:idea-to-code-sculpting` — skill documentation
- `crystal_id` (string, optional if memory_id provided): Crystal identifier from CrystalStore. Format:
  - `ExperienceCrystal:proj:module.name:v1.0` — experience crystal
- `query` (string, optional): Keyword to locate specific paragraphs within the document
- `lines` (string, optional): Line range like "10-30" or "50" for precise line-level retrieval (file-based IDs only)
- `dim` (string, optional): Dimension filter. Valid values:
  - `architecture` — system architecture, module partitioning
  - `contract` — interface definitions, data formats
  - `algorithm` — flow logic, computation steps
  - `implementation` — code details, language features
  - `debug` — error investigation, root cause analysis
  - `meta` — planning, progress management
  - For `memory_id`: extracts matching dimension summary from vector DB
  - For `crystal_id` (ExperienceCrystal): returns only the matching reference_value

**Output**: The full or filtered document content with a metadata header showing source, character count, token estimate, and line count.

**Security**: Only accesses files under `knowledge/`. Returns an error for any path outside this directory.

**Notes**:
- Default return limit: 8000 characters. Content beyond this is truncated with a marker.
- When `query` is provided, the best matching paragraph plus context (one paragraph before/after) is returned.
- When both `lines` and `query` are provided, `lines` is applied first, then `query` searches within that range.
- The `memory_id` is obtained from the `search()` results shown in context — the model should NOT guess or invent IDs.

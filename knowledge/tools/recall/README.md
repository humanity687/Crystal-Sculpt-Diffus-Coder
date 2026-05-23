<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### `recall`

**Purpose**: Fetch original document content by memory_id. This is the second level of the two-level summary memory system. When the model sees a summary reference in context (e.g., `→ recall(memory_id="conv:xxx")`), it calls this tool to retrieve the full text.

**Input**:
- `memory_id` (string, required): Unique identifier from a summary shown in context. Formats:
  - `conv:20260115-143022-a1b2c3` — conversation memory
  - `tool:read` — tool documentation
  - `skill:idea-to-code-sculpting` — skill documentation
- `query` (string, optional): Keyword to locate specific paragraphs within the document
- `lines` (string, optional): Line range like "10-30" or "50" for precise line-level retrieval

**Output**: The full or filtered document content with a metadata header showing source, character count, token estimate, and line count.

**Security**: Only accesses files under `knowledge/`. Returns an error for any path outside this directory.

**Notes**:
- Default return limit: 8000 characters. Content beyond this is truncated with a marker.
- When `query` is provided, the best matching paragraph plus context (one paragraph before/after) is returned.
- When both `lines` and `query` are provided, `lines` is applied first, then `query` searches within that range.
- The `memory_id` is obtained from the `search()` results shown in context — the model should NOT guess or invent IDs.

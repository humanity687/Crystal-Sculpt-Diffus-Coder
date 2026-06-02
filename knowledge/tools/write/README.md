<!--
Copyright (C) 2026 xhdlphzr
This file is part of FranxAgent.
FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.
-->

### `write` — Propose file content changes (proposal-review-overwrite mode)

- **Purpose**: Compute and preview file modifications before applying them. The write tool
  **does NOT write to disk** — it returns the proposed new file content. The frontend
  displays a code review panel where the user can inspect diffs, edit the code, and
  approve the changes. On approval the frontend writes the file via `/api/write_file`.



- **Input**:
    ```json
    {
        "path": "/absolute/path/to/file.py",
        "mode": "overwrite",
        "content": "...",
        "new_content": "...",
        "start_line": 54,
        "end_line": 57
    }
    ```
    - `path`: **string, required**. Absolute path to the target file.
    - `mode`: **string, optional, default `"overwrite"`**. One of:
        - `"overwrite"` — Create a new file or fully replace an existing one.
        - `"edit"` — Delete a line range then insert new content at that position.
        - `"replace"` — Find exact text and replace it (with safety guard against duplicates).
        - `"insert"` — Insert content after a specific line without deleting anything.
    - `content`: **string, required for `overwrite`**. The complete new file content.
    - `start_line` / `end_line`: **int, required for `edit`**. The line range to delete
      (1-based, inclusive). The new content is inserted at `start_line`.
    - `new_content`: **string, required for `edit` and `insert`**. The text to insert.
    - `old_string` / `new_string`: **string, required for `replace`**. The exact text to
      find and its replacement. Case-sensitive, whitespace-sensitive.
    - `expected_replacements`: **int, optional, default 1**. Safety guard for `replace` mode.
      If the number of `old_string` occurrences in the file doesn't match this value,
      the operation is rejected. Increase this value when intentionally replacing multiple
      occurrences.
    - `after_line`: **int, required for `insert`**. Line number to insert after
      (0 = insert at the very beginning of the file).

- **Output**: A string with two parts separated by `---FILE_CONTENT---`:
    - **First part** (stored in agent message history):
        - `edit` / `replace` / `insert`: A unified diff showing only the changed region (±2 context lines).
        - `overwrite`: An AST structure summary of the new file content.
    - **Second part** (sent to frontend for review): The complete proposed file content.

- **Mode selection guide**:
    | Scenario | Mode | Notes |
    |----------|------|-------|
    | Create new file | `overwrite` | Auto-creates parent dirs on approval |
    | Completely rewrite a file | `overwrite` | Returns AST structure for agent reference |
    | Replace a function body | `edit` | Delete old lines, insert new implementation |
    | Rename a variable everywhere | `replace` | Use `expected_replacements=N` if replacing N occurrences |
    | Fix a typo in one location | `replace` | Default `expected_replacements=1` ensures uniqueness |
    | Add a new import | `insert` | Insert after existing imports with `after_line` |
    | Add shebang or header | `insert` | Use `after_line=0` to prepend |
    | Add a new function at end | `insert` | Use `after_line=<last_line>` |

- **Workflow**:
    1. AI calls `read` first to get the current file state and line numbers.
    2. AI calls `write` with the proposed changes — the tool computes the result (no disk write).
    3. The backend sends the full proposed content to the frontend for review.
    4. The user inspects the diff, optionally edits the code, then approves or rejects.
    5. On approval, the frontend writes the file. The agent stores only the diff/err in history.

- **Critical rules**:
    - **Always `read` before `write`** — all line numbers and `old_string` values must come from the most recent `read` result. Never predict or infer them.
    - **For `edit` mode**: use the ORIGINAL file's line numbers (before your edit). The tool handles line shifting internally.
    - **For `replace` mode**: if `expected_replacements` doesn't match the actual occurrence count, the operation is rejected. Either adjust the count or make `old_string` more specific.
    - **This tool does NOT write to disk** — all writes happen on the frontend after user approval.

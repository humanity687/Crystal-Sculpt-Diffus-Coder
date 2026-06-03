<!--
This file is part of Crystal-Sculpt-Diffus-Coder.
Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.
-->

### `read` - Read File Content or Project Structure

- **Purpose**: Read file content (with three modes), scan project structure, or analyze media files.
- **Input**:
```json
{
    "path": "/absolute/path/to/file.py",
    "mode": "all",
    "offset": 1,
    "limit": 2000,
    "show_structure": false
}
```
    - `path`: **string, required**. Absolute path to the file or directory.
    - `mode`: **string, optional, default `"all"`**. Reading mode:
        - `"all"` — Read whole file or a segment from `offset` with `limit` lines.
        - `"lines"` — Read a precise line range (`start_line` to `end_line`, inclusive).
        - `"find"` — Search file content for a string or regex, return match blocks with context.
    - `offset`: **int, optional, default 1**. Start line number (1-based). Only for `all` mode.
    - `limit`: **int, optional, default 2000**. Max lines to return. Output includes `[PARTIAL view]` marker when truncated. Only for `all` mode.
    - `show_structure`: **bool, optional, default false**. When true, prepend tree-sitter AST structure summary (classes, functions, imports with line ranges). Only for `all` and `lines` modes.
    - `start_line`: **int, required for `lines` mode**. First line to read (1-based, inclusive).
    - `end_line`: **int, required for `lines` mode**. Last line to read (inclusive). Clamped to file length if beyond EOF.
    - `query`: **string, required for `find` mode**. Search keyword or regex pattern.
    - `is_regex`: **bool, optional, default false**. Treat `query` as regex when true.
    - `context_lines`: **int, optional, default 2**. Lines of context above and below each match. Only for `find` mode.
    - `max_matches`: **int, optional, default 20**. Max match blocks to return. Surplus matches noted in header. Only for `find` mode.
- **Output**:
    - **Code / text files**: Content with line numbers (`{num:6d}| {content}`). May include `[PARTIAL view]` marker when truncated.
    - **`find` mode**: Structured match blocks with `>` marking matched lines and surrounding context.
    - **`show_structure=true`**: Prepends an AST skeleton section (node types, names, line ranges) before the content.
    - **Document files** (PDF, Word, Excel, PowerPoint, CSV): Converted Markdown text via MarkItDown.
    - **Image/Video files**: AI-generated description via ETT (multimodal).
    - **Directory**: Structure map of all code files with their AST skeletons.
    - Error messages for missing files, permission errors, or invalid parameters.
- **Recommended usage**:
    - **First exploration**: `read(file_path="...", limit=200)` — quickly see file header.
    - **Precise code block**: `read(file_path="...", mode="lines", start_line=100, end_line=150)` — read before editing.
    - **Find function/pattern**: `read(file_path="...", mode="find", query="def authenticate")` — safe grep alternative with context.
    - **Edit verification**: re-read the edited range with `lines` mode after applying changes.
    - **AST overview**: add `show_structure=true` when you need to understand file organization.
- **Notes**: This tool is read-only and will not modify any files. All output lines are numbered for use with the `write` tool's edit mode. Single lines over 2000 characters are truncated with a marker.

# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Write Tool — Proposal Mode

The write tool does NOT write to disk. It computes the new file content that
would result from applying the AI's changes, generates a unified diff, and
returns both separated by `---FILE_CONTENT---`.

The frontend sends the full content (after separator) to the code review panel.
The agent stores only the diff/structure (before separator) in message history.

Modes:
  - overwrite: create or fully replace a file
  - edit:      delete a line range then insert new content at that position
  - replace:   exact string replacement with expected_replacements safety check
  - insert:    insert content after a specified line
"""

import difflib
from pathlib import Path


# ---------------------------------------------------------------------------
#  Diff helpers
# ---------------------------------------------------------------------------

def _unified_diff(original: str, modified: str, path: str) -> str:
    """Generate a compact unified diff (n=2 context lines)."""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    if original_lines and not original_lines[-1].endswith("\n"):
        original_lines[-1] += "\n"
    if modified_lines and not modified_lines[-1].endswith("\n"):
        modified_lines[-1] += "\n"

    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=2,
    )
    return "".join(diff)


def _format_result(agent_part: str, full_content: str) -> str:
    """Combine agent-facing result and frontend content with separator."""
    return agent_part + "\n\n---FILE_CONTENT---\n" + full_content


def _code_structure(code: str, path: str) -> str | None:
    """Parse code structure via tree-sitter (same as read tool).

    Supports Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, C#,
    HTML, CSS.  Returns a tree-sitter skeleton or None for unsupported types.
    """
    try:
        from knowledge.tools.read import _parse_structure
        return _parse_structure(Path(path), code)
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  execute
# ---------------------------------------------------------------------------

schema = {
    "type": "function",
    "function": {
        "name": "write",
        "description": (
            "Propose a file modification. Does NOT write to disk — the proposal is shown "
            "to the user for review in a side-by-side diff panel. Four modes: "
            "'overwrite' (create/replace file, needs content), "
            "'edit' (delete line range then insert, needs start_line/end_line/new_content), "
            "'replace' (find old_string and replace with new_string, uses expected_replacements as safety guard), "
            "'insert' (insert new_content after after_line, 0=file start)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path to write to."},
                "mode": {"type": "string", "enum": ["overwrite", "edit", "replace", "insert"], "description": "Edit mode. Default: 'overwrite'."},
                "content": {"type": "string", "description": "For 'overwrite' mode: complete new file content."},
                "start_line": {"type": "integer", "description": "For 'edit' mode: first line to delete (1-based, inclusive)."},
                "end_line": {"type": "integer", "description": "For 'edit' mode: last line to delete (1-based, inclusive)."},
                "new_content": {"type": "string", "description": "For 'edit' or 'insert' mode: content to insert."},
                "old_string": {"type": "string", "description": "For 'replace' mode: exact string to find and replace."},
                "new_string": {"type": "string", "description": "For 'replace' mode: replacement string."},
                "expected_replacements": {"type": "integer", "description": "For 'replace' mode: expected match count (safety guard). Default: 1."},
                "after_line": {"type": "integer", "description": "For 'insert' mode: line number to insert after (0 = beginning of file)."},
            },
            "required": ["path"],
        },
    },
}


def execute(
    path: str,
    mode: str = "overwrite",
    # overwrite
    content: str = "",
    # edit
    start_line: int = 0,
    end_line: int = 0,
    new_content: str = "",
    # replace
    old_string: str = "",
    new_string: str = "",
    expected_replacements: int = 1,
    # insert
    after_line: int = 0,
) -> str:
    """Compute the result of a file modification without writing to disk.

    Returns a string with two parts separated by `---FILE_CONTENT---`:
      - First part (for agent history): unified diff or AST structure
      - Second part (for frontend review): the complete modified file content

    Modes:
      - "overwrite": create or fully replace. Requires: content.
      - "edit": delete [start_line, end_line] then insert new_content.
          Requires: start_line, end_line, new_content.
      - "replace": find old_string and replace with new_string.
          Uses expected_replacements (default 1) as safety guard.
          Requires: old_string, new_string.
      - "insert": insert new_content after after_line (0 = file start).
          Requires: after_line, new_content.
    """
    p = Path(path).expanduser().resolve()

    # Read original file
    try:
        original_content = p.read_text(encoding="utf-8")
        original_lines = original_content.split("\n") if original_content else []
    except FileNotFoundError:
        original_content = None
        original_lines = []
    except PermissionError:
        return f"Error: Cannot read file: Permission denied - {path}"

    # ======================================================================
    #  overwrite
    # ======================================================================
    if mode == "overwrite":
        if not content:
            return "Error: 'content' parameter is required for overwrite mode"

        if original_content is not None:
            diff = _unified_diff(original_content, content, path)
            agent_part = f"```diff\n{diff}```"
        else:
            new_lines = content.count("\n") + (0 if content.endswith("\n") else 1)
            new_bytes = len(content.encode("utf-8"))
            agent_part = f"New file: {new_lines} lines, {new_bytes} bytes"

        # Append code structure summary (tree-sitter, multi-language)
        structure = _code_structure(content, path)
        if structure:
            agent_part += f"\n\n```structure\n{structure}\n```"

        return _format_result(agent_part, content)

    # ======================================================================
    #  All modes below require an existing file
    # ======================================================================
    if original_content is None:
        return f"Error: File not found: {path}. Use mode='overwrite' to create a new file."

    total_lines = len(original_lines)

    # ======================================================================
    #  edit
    # ======================================================================
    if mode == "edit":
        if start_line < 1 or end_line < start_line:
            return (
                f"Error: start_line ({start_line}) and end_line ({end_line}) "
                f"must be >= 1 and start_line <= end_line"
            )
        if start_line > total_lines:
            return (
                f"Error: start_line ({start_line}) exceeds file length "
                f"({total_lines} lines)"
            )

        # Fall back to content if new_content is empty (model sometimes uses
        # "content" instead of "new_content" for edit/insert modes)
        effective_new = new_content if new_content else content

        actual_end = min(end_line, total_lines)
        clamp_note = ""
        if end_line > total_lines:
            clamp_note = f" (end_line clamped from {end_line} to {total_lines})"
        start_idx = start_line - 1
        end_idx = actual_end  # slicing, exclusive upper bound

        new_lines = (
            original_lines[:start_idx]
            + effective_new.split("\n")
            + original_lines[end_idx:]
        )
        result_content = "\n".join(new_lines)

        diff = _unified_diff(original_content, result_content, path)
        agent_part = f"```diff\n{diff}```{clamp_note}"
        return _format_result(agent_part, result_content)

    # ======================================================================
    #  replace
    # ======================================================================
    if mode == "replace":
        if not old_string:
            return "Error: 'old_string' parameter is required for replace mode"

        count = original_content.count(old_string)
        if count == 0:
            return (
                f"Error: old_string not found in file. "
                f"The provided text does not appear anywhere in {path}. "
                f"Re-read the file to get the exact current content, then retry."
            )
        if count != expected_replacements:
            return (
                f"Error: expected {expected_replacements} occurrence(s) of old_string, "
                f"but found {count}. Adjust expected_replacements or provide a more "
                f"specific old_string that matches the intended location."
            )

        result_content = original_content.replace(old_string, new_string, 1)
        diff = _unified_diff(original_content, result_content, path)
        agent_part = f"```diff\n{diff}```"
        return _format_result(agent_part, result_content)

    # ======================================================================
    #  insert
    # ======================================================================
    if mode == "insert":
        effective_new = new_content if new_content else content
        if not effective_new:
            return "Error: 'new_content' (or 'content') parameter is required for insert mode"
        if after_line < 0 or after_line > total_lines:
            return (
                f"Error: after_line ({after_line}) must be between "
                f"0 and {total_lines}"
            )

        insert_lines = effective_new.split("\n")
        if after_line == 0:
            new_lines = insert_lines + original_lines
        elif after_line == total_lines:
            new_lines = original_lines + insert_lines
        else:
            new_lines = (
                original_lines[:after_line]
                + insert_lines
                + original_lines[after_line:]
            )

        result_content = "\n".join(new_lines)
        diff = _unified_diff(original_content, result_content, path)
        agent_part = f"```diff\n{diff}```"
        return _format_result(agent_part, result_content)

    return f"Error: Unknown mode '{mode}'. Supported: overwrite, edit, replace, insert."

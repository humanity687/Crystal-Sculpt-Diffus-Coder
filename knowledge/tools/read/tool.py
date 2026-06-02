# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
File Content Reading Tool
Allows the AI to read the content of a specified file or project structure.

Modes:
  - all:   read whole file or from offset with limit (default)
  - lines: read a precise line range
  - find:  search file content for a query string or regex
"""

import re
from pathlib import Path
import json
import base64
import time
from openai import OpenAI
from markitdown import MarkItDown

# tree-sitter core
from tree_sitter import Language, Parser

# Language grammars
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_rust as tsrust
import tree_sitter_go as tsgo
import tree_sitter_javascript as tsjs
import tree_sitter_html as tshtml
import tree_sitter_css as tscss
import tree_sitter_typescript as tstypescript
import tree_sitter_c_sharp as tscs

# Language registry: suffix -> (Language, target_node_types)
LANGUAGES = {
    ".py": (
        Language(tspython.language()),
        [
            "function_definition",
            "class_definition",
            "import_statement",
            "import_from_statement",
        ],
    ),
    ".pyw": (
        Language(tspython.language()),
        [
            "function_definition",
            "class_definition",
            "import_statement",
            "import_from_statement",
        ],
    ),
    ".js": (
        Language(tsjs.language()),
        [
            "function_declaration",
            "class_declaration",
            "import_statement",
            "export_statement",
            "lexical_declaration",
            "variable_declaration",
        ],
    ),
    ".jsx": (
        Language(tsjs.language()),
        [
            "function_declaration",
            "class_declaration",
            "import_statement",
            "export_statement",
        ],
    ),
    ".ts": (
        Language(tstypescript.language_typescript()),
        [
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "import_statement",
            "export_statement",
            "abstract_class_declaration",
            "lexical_declaration",
        ],
    ),
    ".tsx": (
        Language(tstypescript.language_tsx()),
        [
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "import_statement",
            "export_statement",
        ],
    ),
    ".rs": (
        Language(tsrust.language()),
        [
            "function_item",
            "impl_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "use_declaration",
            "mod_item",
        ],
    ),
    ".go": (
        Language(tsgo.language()),
        [
            "function_declaration",
            "method_declaration",
            "type_declaration",
            "import_declaration",
        ],
    ),
    ".java": (
        Language(tsjava.language()),
        [
            "class_declaration",
            "method_declaration",
            "interface_declaration",
            "import_declaration",
            "constructor_declaration",
        ],
    ),
    ".c": (
        Language(tsc.language()),
        [
            "function_definition",
            "struct_specifier",
            "enum_specifier",
            "preproc_include",
            "type_definition",
        ],
    ),
    ".h": (
        Language(tsc.language()),
        [
            "function_definition",
            "struct_specifier",
            "enum_specifier",
            "preproc_include",
            "type_definition",
        ],
    ),
    ".cpp": (
        Language(tscpp.language()),
        [
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "namespace_definition",
            "preproc_include",
            "template_declaration",
        ],
    ),
    ".hpp": (
        Language(tscpp.language()),
        [
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "namespace_definition",
            "preproc_include",
            "template_declaration",
        ],
    ),
    ".cc": (
        Language(tscpp.language()),
        [
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "namespace_definition",
            "preproc_include",
            "template_declaration",
        ],
    ),
    ".cs": (
        Language(tscs.language()),
        [
            "class_declaration",
            "method_declaration",
            "interface_declaration",
            "namespace_declaration",
            "using_directive",
            "struct_declaration",
            "enum_declaration",
        ],
    ),
    ".html": (Language(tshtml.language()), ["element"]),
    ".htm": (Language(tshtml.language()), ["element"]),
    ".css": (Language(tscss.language()), ["rule_set"]),
}

# Directories to skip during project scanning
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    "env",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "egg-info",
}

# Maximum characters per output line before truncation
MAX_LINE_CHARS = 2000


def _extract_name(node) -> str:
    """Extract the name of an AST node using tree-sitter fields"""
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8")

    for child in node.children:
        if child.type in ("identifier", "type_identifier", "field_identifier"):
            return child.text.decode("utf-8")
    return ""


def _parse_structure(path: Path, content: str) -> str | None:
    """Parse code file structure, return skeleton summary"""
    suffix = path.suffix.lower()
    if suffix not in LANGUAGES:
        return None

    lang, target_types = LANGUAGES[suffix]
    parser = Parser(lang)

    tree = parser.parse(content.encode("utf-8"))

    lines = []

    def walk(node, depth=0):
        if node.type in target_types:
            start = node.start_point.row + 1
            end = node.end_point.row + 1
            name = _extract_name(node)
            display_name = f" {name}" if name else ""
            prefix = "  " * depth + ("├─ " if depth > 0 else "")
            lines.append(f"{prefix}[{node.type}]{display_name} (L{start}-L{end})")
            for child in node.children:
                walk(child, depth + 1)
        else:
            for child in node.children:
                walk(child, depth)

    walk(tree.root_node)
    return "\n".join(lines) if lines else None


def _scan_project(directory: Path) -> str:
    """Scan project directory, return structure map of all code files"""
    lines = []

    for file in sorted(directory.rglob("*")):
        if any(part in SKIP_DIRS or part.startswith(".") for part in file.parts):
            continue
        if not file.is_file():
            continue
        if file.suffix.lower() not in LANGUAGES:
            continue

        try:
            content = _read_with_encoding(file)[0]
            structure = _parse_structure(file, content)
            if structure:
                rel = file.relative_to(directory)
                lines.append(f"### {rel}")
                lines.append(structure)
                lines.append("")
        except Exception:
            continue

    return "\n".join(lines) if lines else "No parseable code files found"


# ---------------------------------------------------------------------------
#  Encoding helpers
# ---------------------------------------------------------------------------

def _read_with_encoding(file_path: Path) -> tuple:
    """Read file with automatic encoding detection. Returns (text, encoding)."""
    raw = file_path.read_bytes()

    # Try UTF-8 first (most common)
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    # Detect with charset-normalizer
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw).best()
        if result:
            return str(result), result.encoding
    except Exception:
        pass

    # Last-resort fallback (never fails)
    return raw.decode("latin-1"), "latin-1"


# ---------------------------------------------------------------------------
#  Output formatting
# ---------------------------------------------------------------------------

def _format_lines(
    lines: list[str],
    start_num: int = 1,
    partial_info: str | None = None,
) -> str:
    """Format lines with line numbers and optional truncation markers.

    Args:
        lines: The text lines to format.
        start_num: Line number for the first line (1-based).
        partial_info: If set, prepend this as a header marker.
    """
    width = max(6, len(str(start_num + len(lines))))
    out = []
    if partial_info:
        out.append(partial_info)
    for i, line in enumerate(lines):
        num = start_num + i
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "... [line truncated]"
        out.append(f"{num:{width}d}| {line}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
#  find mode
# ---------------------------------------------------------------------------

def _find_in_file(
    lines: list[str],
    query: str,
    is_regex: bool = False,
    context_lines: int = 2,
    max_matches: int = 20,
) -> str:
    """Search file content, return match blocks with context and line numbers.

    Overlapping context blocks are merged.
    """
    # Find matching line indices (0-based)
    matches = []
    for idx, line in enumerate(lines):
        if is_regex:
            try:
                if re.search(query, line):
                    matches.append(idx)
            except re.error as e:
                return f"Error: Invalid regular expression — {e}"
        else:
            if query in line:
                matches.append(idx)

    if not matches:
        return f'(No matches found for "{query}")'

    total = len(matches)
    truncated = total > max_matches
    if truncated:
        matches = matches[:max_matches]

    # Build context ranges, merging overlaps
    ranges = []
    for m in matches:
        start = max(0, m - context_lines)
        end = min(len(lines) - 1, m + context_lines)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    header = f'--- Matches for "{query}" ---'
    if truncated:
        header += f"\n({total} matches found, showing first {max_matches})"

    out = [header]
    for r_start, r_end in ranges:
        out.append("")
        for idx in range(r_start, r_end + 1):
            marker = ">" if idx in matches else " "
            num = idx + 1
            text = lines[idx]
            if len(text) > MAX_LINE_CHARS:
                text = text[:MAX_LINE_CHARS] + "... [line truncated]"
            out.append(f" {marker} {num:6d}| {text}")

    out.append("")
    out.append("[End of find results]")
    return "\n".join(out)


# ---------------------------------------------------------------------------
#  Core read logic
# ---------------------------------------------------------------------------

def _read_file(
    file_path: Path,
    mode: str = "all",
    offset: int = 1,
    limit: int = 2000,
    show_structure: bool = False,
    start_line: int | None = None,
    end_line: int | None = None,
    query: str | None = None,
    is_regex: bool = False,
    context_lines: int = 2,
    max_matches: int = 20,
) -> str:
    """Read a file with the given mode and parameters."""
    content, encoding = _read_with_encoding(file_path)
    all_lines = content.split("\n")
    total_lines = len(all_lines)

    # --- find mode ---
    if mode == "find":
        if not query:
            return "Error: 'query' parameter is required for find mode"
        return _find_in_file(
            all_lines,
            query=query,
            is_regex=is_regex,
            context_lines=context_lines,
            max_matches=max_matches,
        )

    # --- lines mode ---
    if mode == "lines":
        if start_line is None or end_line is None:
            return "Error: 'start_line' and 'end_line' are required for lines mode"
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            return f"Error: end_line ({end_line}) must be >= start_line ({start_line})"
        if start_line > total_lines:
            return f"Error: start_line ({start_line}) exceeds file length ({total_lines} lines)"

        actual_end = min(end_line, total_lines)
        selected = all_lines[start_line - 1 : actual_end]
        partial_info = None
        if end_line > total_lines:
            partial_info = f"[PARTIAL view — requested lines {start_line}-{end_line}, file has only {total_lines} lines]"

        result_parts = []

        # Optional structure
        if show_structure:
            structure = _parse_structure(file_path, content)
            if structure:
                result_parts.append(f"structure\n{structure}\n")

        result_parts.append(_format_lines(selected, start_num=start_line, partial_info=partial_info))
        return "\n".join(result_parts)

    # --- all mode (default) ---
    if offset < 1:
        offset = 1
    if offset > total_lines:
        return f"Error: offset ({offset}) exceeds file length ({total_lines} lines)"

    selected = all_lines[offset - 1 : offset - 1 + limit]
    actual_last = offset - 1 + len(selected)
    partial_info = None
    if actual_last < total_lines:
        partial_info = f"[PARTIAL view — showing lines {offset}-{actual_last} of {total_lines} total]"

    result_parts = []

    # Optional structure
    if show_structure:
        structure = _parse_structure(file_path, content)
        if structure:
            result_parts.append(f"structure\n{structure}\n")

    result_parts.append(_format_lines(selected, start_num=offset, partial_info=partial_info))
    return "\n".join(result_parts)


# ---------------------------------------------------------------------------
#  ETT (multimodal) helpers
# ---------------------------------------------------------------------------

def _get_config():
    """Read ett tool configuration from config.json"""
    config_path = Path(__file__).parent.parent.parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError("config.json not found")
    with open(config_path, "r", encoding="utf-8") as f:
        full_config = json.load(f)
    tool_cfg = full_config.get("tools", {}).get("ett", {})
    return {
        "api_key": tool_cfg.get("api_key", full_config.get("api_key")),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": tool_cfg.get("model", "glm-4.6v-flash"),
        "temperature": tool_cfg.get("temperature", full_config.get("temperature", 0.8)),
        "thinking": tool_cfg.get("thinking", full_config.get("thinking", False)),
        "max_retries": tool_cfg.get("max_retries", 5),
    }


def _encode_local_file(path: str) -> str:
    """Convert local file to data URL"""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = Path(path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return f"data:{mime};base64,{data}"


def ett(urls: str) -> str:
    cfg = _get_config()
    prompt = "Please describe the following content in detail"
    ftype = None
    if urls.endswith((".jpg", ".png", ".gif", ".jpeg")):
        ftype = "image_url"
    if urls.endswith((".mp4", ".webm")):
        ftype = "video_url"
    if ftype is None:
        return "Error: unsupported file type. Supported: jpg, png, gif, jpeg, mp4, webm."
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    # Parse URLs
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    processed_urls = []
    for url in url_list:
        if url.startswith(("http://", "https://")):
            processed_urls.append(url)
        else:
            try:
                print(
                    "Encoding local file to base64, large files may take time please wait..."
                )
                data_url = _encode_local_file(url)
                processed_urls.append(data_url)
            except Exception as e:
                return f"Failed to process local file: {e}"

    # Build content structure
    content = []
    for u in processed_urls:
        if ftype == "image_url":
            content.append({"type": "image_url", "image_url": {"url": u}})
        elif ftype == "video_url":
            content.append({"type": "video_url", "video_url": {"url": u}})
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]

    max_retries = cfg["max_retries"]
    base_delay = 2

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=cfg["temperature"],
                stream=False,
                timeout=60.0,
                extra_body={"thinking": {"type": "disabled"}}
                if not cfg["thinking"]
                else None,
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            if (
                any(
                    code in error_msg for code in ["429", "500", "timed out", "timeout"]
                )
                or "rate" in error_msg.lower()
                or "too many" in error_msg.lower()
            ):
                if attempt < max_retries - 1:
                    wait = base_delay * (2**attempt)
                    print(f"Temporary API error, retry after {wait} seconds...")
                    time.sleep(wait)
                    continue
                else:
                    return "Analysis failed: API busy or timeout, please try again later. Copy content as text or screenshot to retry."
            else:
                return f"Analysis failed: {e}"

    return "Analysis failed: Maximum retries exceeded, please try again later."


# ---------------------------------------------------------------------------
#  Public entry point
# ---------------------------------------------------------------------------

def execute(
    path: str,
    mode: str = "all",
    offset: int = 1,
    limit: int = 2000,
    show_structure: bool = False,
    start_line: int | None = None,
    end_line: int | None = None,
    query: str | None = None,
    is_regex: bool = False,
    context_lines: int = 2,
    max_matches: int = 20,
) -> str:
    """Read file content or project structure.

    Modes:
      - "all" (default): read whole file or from offset with limit.
          Accepts: offset, limit, show_structure.
      - "lines": read a precise line range.
          Accepts: start_line, end_line, show_structure.
      - "find": search file content for a string or regex.
          Accepts: query, is_regex, context_lines, max_matches.

    Directories are scanned for project structure.
    Document files (.pdf, .docx, etc.) are converted via MarkItDown.
    Image/video files are analyzed via ETT (multimodal).
    """
    try:
        p = Path(path).expanduser().resolve()

        if not p.exists():
            return f"Error: File not found: {path}"

        # Directory: scan project structure
        if p.is_dir():
            return _scan_project(p)

        # Document files: convert via MarkItDown
        if p.suffix.lower() in (
            ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".doc", ".ppt", ".csv",
        ):
            try:
                return MarkItDown().convert(str(p)).text_content
            except Exception as e:
                return f"Failed to convert file to Markdown: {e}"

        # Image/Video files: analyze via ETT
        if p.suffix.lower() in (".jpg", ".png", ".gif", ".mp4", ".webm", ".jpeg"):
            return ett(str(p))

        # Text file: use mode-based reading
        return _read_file(
            p,
            mode=mode,
            offset=offset,
            limit=limit,
            show_structure=show_structure,
            start_line=start_line,
            end_line=end_line,
            query=query,
            is_regex=is_regex,
            context_lines=context_lines,
            max_matches=max_matches,
        )

    except PermissionError:
        return f"Error: Cannot read file: Permission denied - {path}"
    except Exception as e:
        return f"Error: {str(e)}"

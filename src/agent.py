# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Agent Module - Core Implementation of AI Agent
Provides the FranxAgent class, responsible for interacting with AI models, tool calling, and memory management
"""

import os
import json
import sys
import atexit
import uuid
import threading
from pathlib import Path
from openai import OpenAI

# Add project root to path to import the knowledge module
sys.path.insert(0, str(Path(__file__).parent.parent))
from knowledge import tool_functions, tools_metadata, search, cleanup_mcp_clients
from src import state

# User guide: explains how to call tools correctly (fixed content, not dependent on knowledge base)
USER_GUIDE = r"""
## 📌 Tool Calling Convention

**Important: You can only use a tool named `tools`.** All functionality is invoked through this tool, with the specific built-in tool specified by the `tool_name` parameter.

When you decide to use a tool, return the `tools` tool in the standard function-calling format. For example, to get the current time, you should return:

```json
{
    "tool_calls": [{
        "id": "call_unique_id",
        "type": "function",
        "function": {
            "name": "tools",
            "arguments": "{\"tool_name\": \"time\", \"arguments\": {}}"
        }
    }]
}
```

For tools that require parameters, `arguments` must be a JSON object containing all required fields. For example, to read a file:

```json
{
    "tool_calls": [{
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "tools",
            "arguments": "{\"tool_name\": \"read\", \"arguments\": {\"path\": \"C:\\\\Users\\\\Example\\\\document.txt\"}}"
        }
    }]
}
```

---

## 🧠 Tool Usage Principles
- **Least privilege**: Only use the tools necessary to complete the task; do not misuse `command` for file operations (use `read`/`write` instead).
- **Accurate calling**: Ensure parameters are correct, especially file path formats (use backslashes on Windows; raw strings or double backslashes are recommended).
- **Error handling**: If a tool returns an error, analyze the cause - you may need to adjust parameters or ask the user.
- **User intent first**: Always choose tools and operations based on the user's request.
- **Do not directly use `time`, `read`, etc. as tool names; they must be called through the `tools` tool.**
- **Use tools, not skills**: Any heading marked with “skill” is not a tool you can call; it is content you should learn.

## 🔨Common Tools
### `read` - Read File Content or Project Structure
- **Purpose**: Call this tool when the user requests to view the content of a file, analyze data within a file, obtain information from a file to complete subsequent tasks, or understand the structure of a project.
- **Input**:
```json
{
    "path": "Full path of the file or directory"
}
```
    - `path`: **string**, required. The path can be an absolute path, or a relative path based on the current working directory. Pass a directory path to scan the project structure.
- **Output**:
    - **Code files** (py, js, ts, rs, go, java, c, cpp, cs, etc.): Returns a `structure` section (AST skeleton with node types, names, and line ranges) followed by a `content` section (full file with line numbers). Use the structure to navigate, and the line numbers to locate exact positions for the `write` tool's edit mode.
    - **Non-code text files**: Returns file content with line numbers.
    - **Document files** (PDF, Word, Excel, PowerPoint, CSV): Returns converted text content.
    - **Image/Video files**: Returns an AI-generated description.
    - **Directory**: Returns a structure map of all code files in the project, showing classes, functions, imports, and their line ranges.
    - An error message will be returned if the path does not exist or cannot be read.
- **Notes**: This tool is read-only and will not modify any files. Ensure the path is correct; confirm the file location via other methods if necessary.

### `write` — Propose file content changes (proposal-review-overwrite mode)
- **Purpose**: Used when the AI wants to create a new file, write content to an existing file, or modify a file. The write tool **no longer performs any file operations**. Instead, it returns the AI's suggested complete file content as a string. The frontend displays this in a code review panel where the user can inspect diffs, edit the code, and approve the changes.
- **Input**:
    ```json
    {
        "path": "Full path of the file",
        "content": "Complete file content after modifications",
        "mode": "overwrite" or "append" or "edit",
        "start_line": 0,
        "end_line": 0
    }
    ```
    - `path`: **string**, required, full path of the target file.
    - `content`: **string**, required, the AI's suggested complete file content after all modifications. The frontend will diff this against the current file on disk.
    - `mode`: **string**, optional, default is "overwrite". Available values:
        - `"overwrite"`: Replace entire file.
        - `"append"`: Insert content **after** the line specified by `start_line` (if `start_line > 0`), otherwise append to the end of the file. `end_line` is ignored.
        - `"edit"`: Replace lines from `start_line` to `end_line` (both inclusive, 1-based). Use with `read` tool's line numbers for precise editing.
    - `start_line`: **integer**, required in edit and append mode (for append only when inserting after a specific line). Start line number (1-based, inclusive). If `start_line <= 0` in append mode, content is appended to the end.
    - `end_line`: **integer**, required in edit mode. End line number (1-based, inclusive).
- **Output**: The AI's suggested complete file content as a plain string (not a dictionary).
- **Workflow**:
    1. The AI calls the `write` tool with the proposed file content.
    2. The backend returns the content string to the frontend without touching the disk.
    3. The frontend opens a code review panel showing the diff between the original file and the AI's proposal.
    4. The user can switch to edit mode, modify the code, then approve the changes.
    5. On approval, the frontend writes the file and sends the final content back to the AI so it stays in sync.
- **Notes**:
    - This tool does NOT execute any file operations. All disk writes are performed by the frontend after user approval.
    - **Append mode with `start_line`**:  
      Example: A file contains lines `1: a` `2: b`. Calling `write` with `mode="append"`, `start_line=1`, `content="X"` results in:  
      ```
      a
      X
      b
      ```
      If `start_line >= total_lines`, content is inserted after the last line (equivalent to appending).
    - **Edit mode**: Always use `read` first to get the current line numbers, then specify the exact range to replace.
    - **Critical Rule for `edit` mode — Line Number Adherence (READ ONLY, NEVER PREDICT)**:
        - **ALL `start_line` and `end_line` values MUST come exclusively from the most recent `read` operation.** You are FORBIDDEN from predicting, calculating, or inferring line numbers based on the content of the edit itself.
        - **Original file only:** When deleting or replacing lines, use the line numbers of the ORIGINAL file BEFORE your edit. Example: If `read` shows lines 50-60 and you are replacing lines 54-57 with a 6-line block, you MUST use `start_line=54, end_line=57`. Using `54-59` (post-edit calculation) is a serious violation.
        - **No "drift" correction:** Do NOT try to adjust line numbers to compensate for how the edit will shift subsequent lines. That shift is handled internally; your job is to provide the exact current coordinates.
        - **Check your work:** Before calling `write` with `edit` mode, explicitly state in your plan: "I am replacing lines X to Y as they appear in the most recent `read` operation."

### `command` - Execute System Commands (With Administrator Privileges)
- **Purpose**: Use this tool when users need to run programs, execute scripts, manage system services, install software, or perform other command-line tasks. This tool has **administrator privileges**, enabling most system-level operations.
- **Input**:
```json
{
    "command": "Full command string to execute"
}
```
- `command`: **string** (required; pass the complete system command string)
- **Output**: Standard output and standard error output of the command. An error code and error message will be returned if the command fails to execute.
- **⚠️ Critical Restriction - File Deletion Handling**:
Direct execution of any file or directory deletion commands (such as `del`, `rm`, `rmdir`, `shred`, etc.) with this tool is **strictly prohibited**. If the user requests file deletion, you must:
1. **Do not use the `command` tool to perform deletion operations.**
2. Replace it with a move operation to send files to the system recycle bin (or a designated secure directory, e.g., `C:\Users\Username\To-Delete`). Examples:
    - On Windows: Use `move <file path> <recycle bin path>`. For safe recycling via PowerShell: `Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('<file>','OnlyErrorDialogs','SendToRecycleBin')`. For simplicity, define a fixed secure folder such as `C:\To-Delete` and use the `move` command.
    - On Linux/macOS: Use commands like `mv <file> ~/.Trash/` or `gio trash <file>`.
3. After completing the move operation, record the moved file information via the `write` tool (e.g., write to a log file) for user recovery later.
- **Other Security Rules**:
    - Do not execute commands that may damage the system, compromise privacy, or violate user intent.
    - Never run high-risk operations (e.g., disk formatting, registry modification) regardless of user consent.
    - Use standard command syntax and avoid complex options with potential side effects.

**Usage Principle**: Prioritize safe, compliant commands for user requests. Confirm permissions and risks with users if uncertain. Replace all deletion actions with file moves and record logs strictly.

### `search` - Web Search
- **Purpose**: Search internet information to obtain real-time data, news, encyclopedia content and more.
- **Input**:
    - `query`: **string**, required, search keyword
    - `max_results`: **integer**, optional, number of returned results (default: 5)
- **Output**: Formatted list of search results; each item contains a title, summary and link.
- **Notes**:
    - Completely free, no API Key required.
    - Real-time search results, consistent with DuckDuckGo used in browsers.
    - Please use reasonably, avoid sending a large number of requests in a short period of time.

### add_skill - Add a Skill

Add a skill as a Markdown file and immediately indexes it into the knowledge base for real-time retrieval. Use this when you've completed a complex task and want to remember the solution for future use.

**Parameters:**
- `name` (string, required): Skill name, used as filename. Use lowercase with underscores (e.g., "nginx_setup", "python_venv").
- `content` (string, required): Skill content in Markdown format. Should include: title, scenario, step-by-step solution, and notes.

**When to use:**
- After completing a multi-step task that is worth remembering
- When the user asks you to remember something
- When you discover a reusable solution

**When NOT to use:**
- For simple one-off questions
- For information already covered by existing skills

Now you can start helping the user. Remember: **Safety first - for delete operations, always use move instead of direct deletion.**

<!--
This is part of FranxAgent
Copyright (C) 2026 xhdlphzr
See the file COPYING for copying conditions.
-->

## Coding Process (Skill)

A universal workflow for turning ideas into reliable, maintainable code, using FranxAgent's tools. This process emphasises understanding, deliberate planning, traceability, and quality assurance.

### 1. Understand the Landscape
- Read the project structure first: `read("./project-root")` — build a mental model of the modules, their responsibilities, and how they communicate.
- Read specific files: `read("./src/agent.py")` — get the AST skeleton and line-numbered content.
- Navigate by structure, pinpoint by line numbers. Understand function signatures, class hierarchies, and imports before deciding what to read in detail.
- If you cannot explain the problem and your approach to a colleague in a couple of sentences, you are not ready to write code yet.

### 2. Read Source Code
- Start from the project skeleton and use function and class names from `read`'s output as stepping stones to trace where they are defined and called.
- Structure first, details second. The skeleton tells you what exists and where; read only the full content you actually need.
- When reading a dependency or library source, find the main module file first (`__init__.py`, or `module.go` in Go), then drill into specific functions based on the public API.
- Pay attention to type signatures, interface abstractions, and import relationships — they reveal architectural intent more reliably than comments.
- If a function is unclear, look up: what class does it belong to? Who calls it? What external state does it depend on?

### 3. Plan and Decompose
- Define the precise change list: which files, which functions, which line ranges.
- Use line numbers from `read`'s output as your edit targets — never rely on memory.
- **Before drafting a fix, diagnose the root cause first**:
    - **Do not guess. Verify.** If the code behaves unexpectedly, use debug logs, breakpoints, or manual tests to confirm exactly which line, which function, or which data flow step is at fault.
    - **Ask "why".** Why was this code written this way? What problem was it originally solving? Will my change break its original intent?
    - **Confirm the root cause before touching anything.** Do not attempt a single edit until you are certain of the true cause. Every invalid modification increases entropy and makes subsequent debugging harder.
- For complex tasks, use an extra `read` snapshot as scratch paper to draft a side-by-side comparison of old and new code.
- Identify the dependency order: which building blocks (type definitions, data structures, helper functions) must exist before the main logic can be assembled.
- A good plan lets a reviewer foresee the code diff just by reading it.

### 4. Edit Surgically
- Use `write` in `edit` mode with `line_start` and `line_end` from `read`'s output.
- **The Unbreakable Law of Line Numbers (for `edit` mode only, must NEVER be violated)**:
    - **Do NOT calculate!** Your `start_line` and `end_line` MUST be the exact original line numbers from the most recent `read` operation, copied verbatim without any addition or subtraction.
    - **Do NOT predict drift!** Do not think about "if I add a few lines here, the line numbers later will shift." That is the system's concern, not yours.
    - **Burn this example into memory:** If `read` shows the lines you need to replace are 54 through 57, then you fill in `54` and `57`. Never ever fill in `59` or any number you derived yourself.
    - **Pre-execution check:** Before calling `edit` mode, you MUST recite this mantra: "I am using line numbers [X, Y], which are the original line numbers from my last `read` operation."
- Replace only the lines that need changing — keep diffs readable and `git blame` coherent.
- When adding new functions or classes, use `edit` to insert at the correct position between neighbours, not appended at the end of the file.
- Make exactly one logical change per edit. Re-`read` immediately afterwards to refresh line numbers and avoid line drift.
- For greenfield files, use `write` in `overwrite` mode.
- **Principle of Minimal Change (do not touch code that already works)**:
    - **Only change the code directly responsible for the problem.** If a line, a function, or a module is unrelated to the current bug, leave it alone.
    - **Do not refactor verified stable code.** Even seemingly harmless operations like "renaming a variable while I'm here" or "tidying up the structure a bit" can introduce new, unknown problems, robbing you of reliable reference points during debugging.
    - **Before every edit, ask yourself:** "Can the problem be solved without changing this line?" If yes, do not change it.
    - **Prefer the solution with the smallest diff.** When two approaches both solve the problem, choose the one that touches fewer files, fewer functions, and fewer lines.

### 5. Comments, Documentation, and Copyright Headers
- **All comments, docstrings, and Doxygen tags (e.g., @brief, @param, @returns) must be written in English.**
- Public classes and functions must carry **Doxygen-formatted** documentation comments. Example:
    ```cpp
    /**
     * @brief Brief description of the function.
     * @param param_name Description of the parameter.
     * @returns Description of the return value.
     * @throws std::runtime_error When something goes wrong.
     */
    ```
- **How to handle copyright headers correctly**:
    *   First, check the license file at the project root: `read("./COPYING")` or `read("./LICENSE")`.
    *   If the license file contains a **"How to Apply These Terms to Your New Programs"** section (or similar instructions), follow those instructions and add the prescribed copyright header to **every source file**.
    *   **Meanwhile, observe how existing files in the project handle this.** If the most established, core files in the project do not have a copyright header, it is a strong signal that the project does not require one.
    *   If the license file does **not** have a "How to Apply" section (common for permissive licenses like MIT or BSD), there is **no requirement** to add a long-form copyright header to each source file. Keeping the full `LICENSE` or `COPYING` file at the project root is sufficient. In this case, a simple SPDX identifier (e.g., `// SPDX-License-Identifier: MIT`) at the top of a file is a good addition but not a hard requirement.

### 6. Verify Incrementally
- After each edit, immediately `read` the modified file to confirm changes landed correctly: are the line numbers aligned? Is the logic correct?
- Run relevant tests with `command`. If no tests exist, write a minimal reproducible script that exercises the changed behaviour and execute it.
- When a bug appears, do not guess. Re-`read` the affected code and its context before modifying anything. Debugging from memory is unreliable.
- Fix the root cause, not the symptom. Patching around symptoms breeds technical debt.

### 7. Clean Up and Capture
- Delete all temporary debug prints, commented-out old code, and hardcoded test values.
- Re-read the final version of each modified file in full, checking for consistency: naming, error handling, and log levels.
- If the change produces reusable knowledge, call `add_skill` to save it for future reference.

### Core Principles
- **Understand, then plan, then write** — the order is non-negotiable
- **Diagnose the root cause before touching code** — find the true source, avoid ineffective edits
- **Minimal change** — only touch what is directly responsible for the problem; never refactor stable code alongside a bugfix
- **A detailed plan prevents over half of all rework**
- **Edit by line, not by file** — surgical precision beats wholesale rewriting
- **One change, one verify** — small, traceable, reversible steps
- **Structure first, details second** — use the AST skeleton to navigate, then dive into specifics
- **Trace the chain** — understand module collaboration through types and function signatures
- **Fix causes, not symptoms** — patches are temporary; solutions are permanent
- **Document with Doxygen** — generate API references automatically from your comments
- **Respect the project's licensing conventions** — check the license file and existing code to decide if copyright headers are needed
"""


class FranxAgent:
    """
    AI Agent Class
    """

    def __init__(
        self,
        key: str,
        url: str,
        model: str,
        settings="You are a helpful AI assistant.",
        temperature=0.8,
        thinking=False,
        knowledge_k=1,
        crystal_store=None,
        crystal_observer=None,
    ):
        """
        Initialize the agent
        """
        self.client = OpenAI(api_key=key, base_url=url)
        self.model = model
        self.user_settings = settings
        self.temperature = temperature
        self.thinking = thinking
        self.knowledge_k = knowledge_k  # Number of knowledge fragments to retrieve
        self.crystal_store = crystal_store  # Shared CrystalStore instance
        self.crystal_observer = crystal_observer  # Auto-extraction observer

        # Unified tool functions (include built-in + MCP)
        self.tool_functions = tool_functions
        self.tools_metadata = tools_metadata
        self.tools = self.tools_metadata

        # Thread safety: ensure only one input() call per instance at a time
        self._input_lock = threading.Lock()

        # Message metadata and archive policy (v2 memory system)
        self.message_meta: dict[int, dict] = {}
        self.module_archive_policy: dict[str, bool] = {}
        self.pending_completion: dict | None = None
        self._crystal_inactive_warned = False  # Only warn once per session

        raw = [{}]
        if os.path.exists("messages.json"):
            with open("messages.json", "r", encoding="utf-8") as f:
                raw = json.load(f)
        if isinstance(raw, dict) and "messages" in raw:
            self.messages = raw["messages"]
            self.message_meta = {int(k): v for k, v in raw.get("_meta", {}).items()}
            self.module_archive_policy = raw.get("_archive_policy", {})
        elif isinstance(raw, list):
            self.messages = raw
            self.message_meta = {}
        else:
            self.messages = [{}]

        # Fixed base system prompt (contains USER_GUIDE and user settings)
        self.base_system_prompt = f"{USER_GUIDE}\n\n---\n\n{self.user_settings}"
        # Persistent message history: first message is always the base system prompt
        self.messages[0] = {"role": "system", "content": self.base_system_prompt}

        # Register cleanup of MCP clients on exit
        atexit.register(cleanup_mcp_clients)

        def _safe_save():
            try:
                self._save_messages()
            except Exception as e:
                print(
                    f"[FranxAgent] Failed to save messages on exit: {e}",
                    file=sys.stderr,
                )

        atexit.register(_safe_save)

    def _save_messages(self):
        """Save current message history + metadata to messages.json atomically."""
        tmp_path = "./messages.json.tmp"
        data = {
            "messages": self.messages,
            "_meta": {str(k): v for k, v in self.message_meta.items()},
            "_archive_policy": self.module_archive_policy,
        }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, "./messages.json")

    # Approval conclusion patterns for auto-tagging approval messages
    _APPROVAL_PATTERNS = [
        "符合你的预期吗",
        "符合预期吗",
        "是否批准",
        "这个划分合理吗",
        "处理流程符合预期吗",
        "代码结构和命名符合预期吗",
        "我理解得对吗",
        "有遗漏或偏差吗",
        "是否继续",
        "能否批准",
    ]

    # User confirmation patterns for module completion
    # Must be explicit archiving intent — short/generic words excluded to prevent false positives
    _CONFIRM_PATTERNS = [
        "确认归档", "可以归档", "归档吧", "归档这个模块",
        "archive", "archive module",
    ]

    def _build_meta(self, role: str, content: str) -> dict | None:
        """Build message metadata from active_project state and content patterns."""
        if not state.active_project:
            return None

        ap = state.active_project
        meta = {
            "skill_layer": ap.get("phase"),
            "module": ap.get("module"),
            "project_id": ap.get("project_id"),
            "is_approval": False,
            "chain_id": None,
        }

        # Detect approval messages: assistant messages matching approval patterns
        if role == "assistant" and content:
            for pat in self._APPROVAL_PATTERNS:
                if pat in content:
                    meta["is_approval"] = True
                    break

        # Chain ID: generate on L3 approval, inherit for same module
        if meta["is_approval"] and meta["skill_layer"] == "L3" and meta["module"]:
            meta["chain_id"] = f"{meta['project_id']}/{meta['module']}/L3-L7"
        elif meta["module"] and meta["project_id"]:
            # Inherit chain_id from the most recent L3 approval for this module
            for idx in sorted(self.message_meta.keys(), reverse=True):
                prev = self.message_meta.get(idx)
                if prev and prev.get("chain_id") == f"{meta['project_id']}/{meta['module']}/L3-L7":
                    meta["chain_id"] = prev["chain_id"]
                    break

        return meta

    def _append_message(self, role: str, content: str, **extra) -> int:
        """Append message with auto-tagging. Returns message index."""
        idx = len(self.messages)
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        meta = self._build_meta(role, content)
        if meta:
            self.message_meta[idx] = meta
        return idx

    def _clean_orphan_tool_messages(self):
        """Remove tool messages without a matching assistant tool_call and vice versa."""
        # Collect all tool_call IDs from assistant messages
        assistant_call_ids = set()
        for msg in self.messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    assistant_call_ids.add(tc["id"])

        # Collect all tool_call_ids from tool messages
        tool_message_ids = set()
        for msg in self.messages:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    tool_message_ids.add(cid)

        # Valid IDs must appear in BOTH sets (bidirectional match)
        valid_ids = assistant_call_ids & tool_message_ids

        new_messages = []
        for msg in self.messages:
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                # Keep only tool_calls that have a matching tool result
                filtered = [tc for tc in msg["tool_calls"] if tc["id"] in valid_ids]
                new_msg = msg.copy()
                if filtered:
                    new_msg["tool_calls"] = filtered
                else:
                    # Strip invalid tool_calls but keep the message (preserve text content)
                    new_msg.pop("tool_calls", None)
                new_messages.append(new_msg)
            elif role == "tool":
                if msg.get("tool_call_id") in valid_ids:
                    new_messages.append(msg)
                # else discard orphan tool message (no matching assistant tool_call)
            else:
                new_messages.append(msg)
        self.messages = new_messages

    def _build_context(self, msg: str, relevant: list[str]) -> list[dict]:
        """Assemble the message list sent to the model (without persistent history)."""
        messages = [
            {"role": "system", "content": self.base_system_prompt}
        ]

        # Inject phase-specific constraints from skill (set by set_project tool)
        if state.phase_guidance:
            messages.append({"role": "system", "content": state.phase_guidance})

        # Inject engineering crystal state (phase-aware, from CrystalStore)
        if self.crystal_store and state.active_project:
            ctx = self.crystal_store.working_context(
                project_id=state.active_project["project_id"],
                phase=state.active_project["phase"],
                module=state.active_project.get("module"),
            )
            if ctx:
                print(
                    f"[CrystalStore] Injecting {len(ctx)} chars of engineering state "
                    f"(project={state.active_project['project_id']}, "
                    f"phase={state.active_project['phase']})",
                    file=sys.stderr,
                )
                messages.append({"role": "system", "content": ctx})
            else:
                print(
                    f"[CrystalStore] No relevant crystals for "
                    f"phase={state.active_project['phase']}, module={state.active_project.get('module')}",
                    file=sys.stderr,
                )
        elif self.crystal_store:
            total = len(self.crystal_store.get_active_crystals())
            if total > 0 and not self._crystal_inactive_warned:
                print(
                    f"[CrystalStore] {total} crystals available but inactive "
                    f"(no active_project set — activate via skill approval)",
                    file=sys.stderr,
                )
                self._crystal_inactive_warned = True

        # RAG knowledge retrieval (two-level summary memory system)
        if relevant:
            knowledge_text = "\n".join(relevant)
            messages.append({
                "role": "system",
                "content": f"## 📚 相关记忆摘要\n\n{knowledge_text}",
            })

        # Attach persistent message history (skip index 0 = base system prompt)
        messages.extend(self.messages[1:])
        return messages

    def _get_relevant_knowledge(self, msg: str) -> list[str]:
        """Retrieve knowledge fragments. Phase-aware when CrystalStore is active.

        Two-level summary memory format:
          Each result string includes a memory_id reference so the model can
          call recall(memory_id="...") to fetch full original content.
        """
        if not self.crystal_store or not state.active_project:
            if self.crystal_store and state.active_project is None:
                total = len(self.crystal_store.get_active_crystals())
                if total > 0 and not self._crystal_inactive_warned:
                    print(
                        f"[CrystalStore] {total} crystals on disk but inactive "
                        f"(set active_project to enable phase-aware retrieval)",
                        file=sys.stderr,
                    )
                    self._crystal_inactive_warned = True
            return self._format_search_results(search(msg, k=self.knowledge_k))

        phase = state.active_project["phase"]
        module = state.active_project.get("module", "")

        if phase in ("L3",):
            contracts = self.crystal_store.find_similar_contracts(msg, top_k=3)
            traces = self.crystal_store.find_related_traces(module or msg, top_k=2)
            print(
                f"[CrystalStore] Phase {phase}: found {len(contracts)} similar contracts + "
                f"{len(traces)} related traces",
                file=sys.stderr,
            )
            results = []
            for c in contracts:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                results.append(
                    f"[ContractCrystal v{c['vitality']}] {c['project_id']}/{c['module']}.{c['name']}: "
                    f"signature={content.get('signature', 'N/A')}"
                )
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                results.append(
                    f"[TraceCrystal] {t['name']}: root_cause={content.get('root_cause', 'N/A')}"
                )
            if not results:
                results = self._format_search_results(search(msg, k=self.knowledge_k))
            else:
                # Merge with search results for broader context
                results.extend(self._format_search_results(search(msg, k=2)))
            return results

        if phase in ("L6", "L7"):
            traces = self.crystal_store.find_related_traces(module or msg, top_k=3)
            print(
                f"[CrystalStore] Phase {phase}: found {len(traces)} related traces",
                file=sys.stderr,
            )
            if traces:
                results = []
                for t in traces:
                    content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                    results.append(
                        f"[TraceCrystal] {t['name']}: "
                        f"symptom={content.get('symptom', 'N/A')}, "
                        f"fix={content.get('fix', 'N/A')}"
                    )
                results.extend(self._format_search_results(search(msg, k=2)))
                return results

        return self._format_search_results(search(msg, k=self.knowledge_k))

    def _format_search_results(self, results: list[dict]) -> list[str]:
        """Format structured search results with memory_id for recall tool.

        Each result becomes a markdown bullet with memory_id reference
        so the model can call recall(memory_id="...") for full details.
        """
        formatted = []
        for r in results:
            mid = r.get("memory_id")
            icon = r.get("icon", "📄")
            title = r.get("title", "")
            text = r.get("text", "")

            # Truncate text for context efficiency — full text via recall
            summary = text[:200] if len(text) > 200 else text

            if mid:
                line = (
                    f"- **{mid}** | {icon}"
                    f"{('：' + title) if title else ''}\n"
                    f"  {summary}\n"
                    f"  → 使用 `recall(memory_id=\"{mid}\")` 查看原文"
                )
            else:
                # Legacy entries without memory_id
                line = (
                    f"- {icon}"
                    f"{('：' + title) if title else ''}\n"
                    f"  {summary}"
                )
            formatted.append(line)
        return formatted

    def input(self, msg: str):
        """
        Process user messages, supporting streaming output of AI replies
        - Persist user message in history
        - Dynamically retrieve knowledge and add as a temporary system message (not persisted)
        - When the model returns text, yield it character by character
        - When the model needs to call a tool, execute the tool synchronously and print the tool call info to stdout (can be redirected)
        - Loop until no tool calls remain
        """
        # Remember the history length before this round starts
        original_len = len(self.messages)

        # Acquire the per-agent lock to prevent concurrent input() calls
        self._input_lock.acquire()
        try:
            # 1. Persist the current user message
            self._append_message("user", msg)

            # 1.5 Detect pending completion confirmation from previous turn
            if self._detect_completion_confirmation(msg):
                self._archive_completed_modules()
            elif self.pending_completion:
                # User didn't confirm — clear pending (assume rework needed)
                pending_mod = self.pending_completion["module"]
                print(
                    f"[Archive] Module {pending_mod} completion NOT confirmed, "
                    f"clearing pending marker",
                    file=sys.stderr,
                )
                self.pending_completion = None

            # 2. Retrieve relevant knowledge for this query (phase-aware when CrystalStore is active)
            relevant = self._get_relevant_knowledge(msg)

            # 3. Build the initial message list for this API call
            api_messages = self._build_context(msg, relevant)

            # Make a working copy that we will update during the tool call loop
            current_api_messages = api_messages.copy()

            max_iterations = 50
            iteration = 0
            while True:
                iteration += 1
                if iteration > max_iterations:
                    yield f"\n\n[Agent stopped after {max_iterations} tool-call iterations to prevent infinite loop.]\n"
                    self._append_message("assistant", f"[Stopped after {max_iterations} iterations]")
                    self._save_messages()
                    return
                try:
                    # Call the model (based on thinking configuration)
                    if self.thinking:
                        stream = self.client.chat.completions.create(
                            model=self.model,
                            messages=current_api_messages,
                            temperature=self.temperature,
                            tools=self.tools,
                            tool_choice="auto",
                            stream=True,
                            extra_body={"thinking": {"type": "enabled"}},
                        )
                    else:
                        stream = self.client.chat.completions.create(
                            model=self.model,
                            messages=current_api_messages,
                            temperature=self.temperature,
                            tools=self.tools,
                            tool_choice="auto",
                            stream=True,
                            extra_body={"thinking": {"type": "disabled"}},
                        )

                    full_content = ""  # Accumulate complete response
                    full_reasoning = ""  # Accumulate reasoning (if enabled)
                    tool_calls_data = {}  # Store tool call data

                    # Process streaming response
                    for chunk in stream:
                        delta = chunk.choices[0].delta

                        # Process text content
                        if delta.content:
                            full_content += delta.content
                            yield delta.content

                        if (
                            hasattr(delta, "reasoning_content")
                            and delta.reasoning_content
                        ):
                            full_reasoning += delta.reasoning_content

                        # Process tool calls (incremental)
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in tool_calls_data:
                                    # Initialize tool call object
                                    tool_calls_data[idx] = {
                                        "id": tc.id,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if tc.function.name:
                                    tool_calls_data[idx]["function"]["name"] += (
                                        tc.function.name
                                    )
                                if tc.function.arguments:
                                    tool_calls_data[idx]["function"]["arguments"] += (
                                        tc.function.arguments
                                    )

                    # Build complete assistant message
                    assistant_message = {
                        "role": "assistant",
                        "content": full_content,
                        "tool_calls": [dict(tc) for tc in tool_calls_data.values()]
                        if tool_calls_data
                        else None,
                    }
                    if self.thinking and full_reasoning:
                        assistant_message["reasoning_content"] = full_reasoning
                    # Append to both current API messages and persistent history
                    current_api_messages.append(assistant_message)

                    # If no tool calls, finish
                    if not tool_calls_data:
                        extra = {}
                        if assistant_message.get("reasoning_content"):
                            extra["reasoning_content"] = assistant_message["reasoning_content"]
                        if assistant_message.get("tool_calls") is not None:
                            extra["tool_calls"] = assistant_message["tool_calls"]
                        self._append_message("assistant", full_content, **extra)
                        self._save_messages()

                        # CrystalObserver auto-extraction (best-effort, never blocks)
                        if self.crystal_observer and state.active_project:
                            try:
                                turn_msgs = [
                                    m for m in self.messages[-8:]
                                    if m.get("role") in ("user", "assistant", "tool")
                                ]
                                cid = self.crystal_observer.analyze_turn(
                                    turn_msgs, state.active_project
                                )
                                if cid:
                                    print(
                                        f"[CrystalObserver] Auto-extracted: {cid}",
                                        file=sys.stderr,
                                    )
                            except Exception as e:
                                print(
                                    f"[CrystalObserver] Non-fatal error: {e}",
                                    file=sys.stderr,
                                )

                        return

                    # Execute tool calls one by one
                    tool_messages = []
                    for tool_call in tool_calls_data.values():
                        tool_message = None
                        try:
                            func_name = tool_call["function"]["name"]

                            try:
                                arguments = json.loads(
                                    tool_call["function"]["arguments"]
                                )
                            except json.JSONDecodeError as e:
                                # Feed error back to model and continue
                                raise ValueError(
                                    f"JSON parsing error: {e}. Raw arguments: {tool_call['function']['arguments']}"
                                )

                            # Guard against null arguments from malformed tool calls
                            if arguments is None:
                                arguments = {}

                            # If the model directly called a built-in tool name (e.g., time, read), automatically convert to tools call
                            if func_name != "tools" and "/" not in func_name:
                                # Construct new arguments: tool_name is the original function name, arguments are the original parameters
                                new_arguments = {
                                    "tool_name": func_name,
                                    "arguments": arguments,
                                }
                                # Update tool_call object
                                tool_call["function"]["name"] = "tools"
                                tool_call["function"]["arguments"] = json.dumps(
                                    new_arguments, ensure_ascii=False
                                )
                                func_name = "tools"
                                arguments = new_arguments

                            # Determine the actual tool name
                            actual_tool_name = None
                            if func_name == "tools":
                                # Extract tool_name from arguments (when wrapped)
                                actual_tool_name = arguments.get("tool_name")
                            else:
                                actual_tool_name = func_name

                            # 1. Send tool_call event first (shows "Using xxx...")
                            call_id = tool_call["id"]
                            yield {
                                "type": "tool_call",
                                "call_id": call_id,
                                "tool_name": actual_tool_name,
                                "arguments": arguments,
                                "result": None,  # No result yet
                            }

                            result = None
                            # 2. Handle tool execution based on type
                            if actual_tool_name == "command":
                                # Command tools require user confirmation
                                confirm_id = str(uuid.uuid4())
                                # 3. Send confirmation request event
                                approved = yield {
                                    "type": "confirmation_required",
                                    "confirm_id": confirm_id,
                                    "call_id": call_id,
                                    "tool_name": actual_tool_name,
                                    "arguments": arguments,
                                }
                                if approved:
                                    # Execute the tool
                                    func = self.tool_functions.get(func_name)
                                    if func:
                                        result = func(**arguments)
                                    else:
                                        result = f"Error: unknown tool {func_name}"
                                else:
                                    # User rejected
                                    result = f"Tool '{actual_tool_name}' execution was rejected by the user."
                            elif actual_tool_name == "write":
                                # Write tools use proposal-review-overwrite mode
                                # First, execute the tool to get the AI's suggested content
                                func = self.tool_functions.get(func_name)
                                if func:
                                    ai_content = func(**arguments)
                                else:
                                    ai_content = f"Error: unknown tool {func_name}"
                                confirm_id = str(uuid.uuid4())
                                # Send proposal to frontend, wait for user's final content
                                result = yield {
                                    "type": "write_proposal",
                                    "confirm_id": confirm_id,
                                    "call_id": call_id,
                                    "tool_name": actual_tool_name,
                                    "arguments": arguments,
                                    "content": str(ai_content),
                                }
                                # result is the final_content string from frontend, or False if rejected
                                if not result or result is False:
                                    result = f"Tool '{actual_tool_name}' proposal was rejected by the user."
                            else:
                                # Normal execution (no confirmation needed)
                                func = self.tool_functions.get(func_name)
                                if func:
                                    result = func(**arguments)
                                else:
                                    result = f"Error: unknown tool {func_name}"

                            # 4. Send tool result event (updates UI)
                            yield {
                                "type": "tool_result",
                                "call_id": call_id,
                                "result": str(result)
                                if result is not None
                                else "No result",
                            }

                            # Add tool execution result to both current API messages and persistent history
                            tool_message = {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": str(result),
                            }
                        except Exception as e:
                            # Catch any exception (including from tool functions) and turn into error message
                            error_content = (
                                f"Tool execution error: {type(e).__name__}: {str(e)}"
                            )
                            # Try to get call_id if available, otherwise use fallback
                            call_id = tool_call.get("id", "unknown")
                            yield {
                                "type": "tool_result",
                                "call_id": call_id,
                                "result": error_content,
                            }
                            tool_message = {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": error_content,
                            }
                        finally:
                            if tool_message:
                                tool_messages.append(tool_message)

                    current_api_messages.extend(tool_messages)
                    extra = {}
                    if assistant_message.get("reasoning_content"):
                        extra["reasoning_content"] = assistant_message["reasoning_content"]
                    if assistant_message.get("tool_calls") is not None:
                        extra["tool_calls"] = assistant_message["tool_calls"]
                    self._append_message("assistant", full_content, **extra)
                    for tm in tool_messages:
                        self._append_message("tool", tm["content"], tool_call_id=tm["tool_call_id"])

                        # Monitor crystallize(ImplCrystal) for module completion detection
                        if self.crystal_store and state.active_project:
                            cid = tm.get("tool_call_id", "")
                            # Find the corresponding assistant message to check tool name
                            for tc in (assistant_message.get("tool_calls") or []):
                                if tc["id"] == cid:
                                    try:
                                        tc_args = json.loads(tc["function"]["arguments"])
                                    except (json.JSONDecodeError, KeyError):
                                        continue
                                    if (tc_args.get("tool_name") == "crystallize"
                                            and tc_args.get("arguments", {}).get("crystal_type") == "ImplCrystal"):
                                        module_name = tc_args.get("arguments", {}).get("module")
                                        project_id = state.active_project.get("project_id")
                                        if project_id and module_name:
                                            self._mark_module_pending_completion(project_id, module_name)
                                    break

                except Exception as e:
                    # If API call fails due to context length, compress and retry
                    error_str = str(e).lower()
                    if (
                        "context length" in error_str
                        or "token" in error_str
                        or "too long" in error_str
                    ):
                        # Compress messages and retry
                        self.memory()
                        # Rebuild API messages with compressed history
                        current_api_messages = self._build_context(msg, relevant)
                        continue
                    else:
                        # Re-raise other exceptions
                        raise

            # Max iterations exhausted — save current state and return
            self._save_messages()
            return

        except GeneratorExit:
            # User stopped; keep committed messages, clean orphans
            # If only the user message was added (no assistant response), roll back
            if (
                len(self.messages) == original_len + 1
                and self.messages[-1]["role"] == "user"
            ):
                self.messages = self.messages[:original_len]
            else:
                self._clean_orphan_tool_messages()
            # Persist current state immediately so messages.json stays complete
            self._save_messages()
            return

        finally:
            self._input_lock.release()

    def _find_safe_cut_index(self):
        """Find the earliest index where cutting won't break tool_call/tool_result pairs.
        Returns None if no safe cut exists."""
        # Map tool_call_id -> message index for both calls and results
        call_positions = {}
        result_positions = {}
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    call_positions[tc["id"]] = i
            elif msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    result_positions[cid] = i

        # Only IDs with both call and result matter for safety
        paired_ids = set(call_positions.keys()) & set(result_positions.keys())

        for cut_idx in range(2, len(self.messages)):
            safe = True
            for cid in paired_ids:
                call_before = call_positions[cid] < cut_idx
                result_before = result_positions[cid] < cut_idx
                if call_before != result_before:
                    # Pair crosses the cut boundary - not safe
                    safe = False
                    break
            if safe:
                return cut_idx
        return None

    def _mark_module_pending_completion(self, project_id: str, module_name: str):
        """Mark a module as pending completion confirmation.

        Appends a system marker message so the model knows to prompt the user
        for explicit archive confirmation (e.g. \"确认归档\").
        """
        self.pending_completion = {
            "project_id": project_id,
            "module": module_name,
        }
        # Append a visible marker — model sees this and should ask user to confirm
        self.messages.append({
            "role": "system",
            "content": (
                f"[模块完成标记] {module_name} 的实现已通过 ImplCrystal 记录。"
                f"请在回复末尾询问用户是否确认归档该模块（回复\"确认归档\"以归档）。"
            ),
        })

    def _detect_completion_confirmation(self, msg: str) -> bool:
        """Check if user message confirms a pending module completion."""
        if not self.pending_completion:
            return False
        msg_lower = msg.strip().lower()
        for pat in self._CONFIRM_PATTERNS:
            if pat in msg_lower:
                return True
        return False

    def _build_chain_ranges(self) -> list[tuple[int, int]]:
        """Scan message_meta and build approval chain intervals.

        Returns: [(start_idx, end_idx), ...] for each unique chain_id.
        """
        chains: dict[str, dict] = {}  # chain_id -> {start, end}
        for idx in sorted(self.message_meta.keys()):
            meta = self.message_meta[idx]
            chain_id = meta.get("chain_id")
            if not chain_id:
                continue
            if chain_id not in chains:
                chains[chain_id] = {"start": idx, "end": idx}
            else:
                chains[chain_id]["end"] = idx

        return [(rng["start"], rng["end"]) for rng in chains.values()]

    def _build_atomic_ranges(self) -> list[tuple[int, int]]:
        """Build all atomic (indivisible) message ranges.

        Merges: chain intervals + tool_call/tool_result pair intervals.
        Returns sorted, merged list of (start, end) inclusive ranges.
        """
        ranges = []

        # Chain intervals from metadata
        for start, end in self._build_chain_ranges():
            ranges.append((start, end))

        # Tool call/result pair intervals
        call_positions = {}
        result_positions = {}
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    call_positions[tc["id"]] = i
            elif msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    result_positions[cid] = i
        paired_ids = set(call_positions.keys()) & set(result_positions.keys())
        for cid in paired_ids:
            c_idx = call_positions[cid]
            r_idx = result_positions[cid]
            start = min(c_idx, r_idx)
            end = max(c_idx, r_idx)
            ranges.append((start, end))

        if not ranges:
            return []

        # Merge overlapping ranges
        ranges.sort()
        merged = [ranges[0]]
        for r in ranges[1:]:
            last = merged[-1]
            if r[0] <= last[1]:
                merged[-1] = (last[0], max(last[1], r[1]))
            else:
                merged.append(r)
        return merged

    def _find_skill_safe_cut_index(self) -> int | None:
        """Find earliest cut index that doesn't break any atomic interval.

        Returns None if no safe cut point exists (all indices fall inside intervals).
        """
        atomic = self._build_atomic_ranges()
        if not atomic:
            return 2  # No constraints, safe to cut at index 2

        for cut_idx in range(2, len(self.messages)):
            safe = True
            for start, end in atomic:
                if start < cut_idx <= end:
                    safe = False
                    break
            if safe:
                return cut_idx
        return None

    def _rebuild_meta_after_cut(self, cut_idx: int):
        """Rebuild message_meta indices after cutting messages[:cut_idx]."""
        new_meta = {}
        offset = cut_idx - 1  # messages[0] stays, so dropped = cut_idx - 1
        for old_idx, meta in self.message_meta.items():
            if old_idx == 0:
                new_meta[0] = meta
            elif old_idx >= cut_idx:
                new_meta[old_idx - offset] = meta
        self.message_meta = new_meta

    def _build_module_summary(self, project_id: str, module_name: str) -> str | None:
        """Build an archive summary for a module from CrystalStore."""
        if not self.crystal_store:
            return None

        contracts = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal", module=module_name
        )
        logic = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="LogicCrystal", module=module_name
        )
        impls = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ImplCrystal", module=module_name
        )

        lines = [f"📦 模块 `{module_name}` 已归档", ""]

        if contracts:
            c = contracts[0]
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            sig = content.get("signature", c["name"])
            pre = content.get("preconditions", [])
            post = content.get("postconditions", [])
            lines.append(f"**L3 契约**：{sig}")
            if pre:
                lines.append(f"  前置条件：{', '.join(pre)}")
            if post:
                lines.append(f"  后置条件：{', '.join(post)}")
            lines.append("")

        if logic:
            l = logic[0]
            content = l.get("content", {}) if isinstance(l.get("content"), dict) else {}
            steps = content.get("algorithm_steps", [])
            if steps:
                steps_str = " → ".join(steps[:6])
                lines.append(f"**L4 算法**：{steps_str}")
                lines.append("")

        if impls:
            imp = impls[0]
            impl_content = imp.get("content", {}) if isinstance(imp.get("content"), dict) else {}
            lang = impl_content.get("language", "")
            lines.append(f"**L7 实现**：{imp['name']}{' (' + lang + ')' if lang else ''}，通过最小测试")
            lines.append("")

        lines.append("**变更记录**：无契约复议")
        lines.append("")
        crystal_refs = []
        for c in contracts[:1]:
            crystal_refs.append(f"contract:{module_name}:{c['name']}")
        for imp in impls[:1]:
            crystal_refs.append(f"impl:{module_name}:{imp['name']}")
        if crystal_refs:
            lines.append(f"🔗 相关结晶：{', '.join(crystal_refs)}")

        return "\n".join(lines)

    def _archive_module(self, project_id: str, module_name: str) -> bool:
        """Archive a completed module: replace its chain with a summary message.

        Returns True if the module was actually archived.
        """
        if not self.module_archive_policy.get(module_name, True):
            return False

        # Find the chain for this module
        chain_id = f"{project_id}/{module_name}/L3-L7"
        chain_start = None
        chain_end = None
        for idx, meta in self.message_meta.items():
            if meta.get("chain_id") == chain_id:
                if chain_start is None:
                    chain_start = idx
                chain_end = idx

        if chain_start is None:
            return False

        summary = self._build_module_summary(project_id, module_name)
        if not summary:
            return False

        summary_msg = {"role": "assistant", "content": summary}

        # Replace chain messages with summary
        self.messages = (
            self.messages[:chain_start]
            + [summary_msg]
            + self.messages[chain_end + 1:]
        )

        # Update metadata: remove replaced entries, tag summary
        new_meta = {}
        replaced_count = chain_end - chain_start + 1
        offset = replaced_count - 1  # N old messages → 1 summary, lost N-1 slots
        for old_idx, meta in self.message_meta.items():
            if old_idx < chain_start:
                new_meta[old_idx] = meta
            elif old_idx > chain_end:
                new_meta[old_idx - offset] = meta
        new_meta[chain_start] = {
            "skill_layer": "L8",
            "module": module_name,
            "project_id": project_id,
            "is_approval": False,
            "chain_id": None,
        }
        self.message_meta = new_meta

        print(
            f"[Archive] Module {module_name}: chain L3-L7 compressed to summary "
            f"({replaced_count} messages → 1)",
            file=sys.stderr,
        )
        return True

    def _archive_completed_modules(self) -> bool:
        """Archive all modules with pending completion that have been confirmed.

        Returns True if at least one module was archived.
        """
        if not self.pending_completion:
            return False

        pi = self.pending_completion
        archived = self._archive_module(pi["project_id"], pi["module"])
        self.pending_completion = None
        if archived:
            self._compact_messages()
        return archived

    def _compact_messages(self):
        """Trigger garbage collection of replaced message list segments."""
        self._save_messages()

    def _build_degradation_summary(self, dropped_count: int) -> dict | None:
        """Build a system message summarizing active crystals after compression."""
        if not self.crystal_store or not state.active_project:
            return None

        project_id = state.active_project["project_id"]
        contracts = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal"
        )
        traces = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="TraceCrystal"
        )

        if not contracts and not traces:
            return None

        lines = [
            f"[Context compressed: ~{dropped_count} earlier messages removed]",
            "",
            "Engineering decisions below remain locked. Do not redesign or contradict:",
        ]
        for c in contracts[:8]:
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            sig = content.get("signature", c["name"])
            lines.append(f"- [{c['module']}.{c['name']}] {sig}")

        if traces:
            lines.append("")
            lines.append("Known failure patterns — avoid these root causes:")
            for t in traces[:5]:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                root = content.get("root_cause", "")
                if root:
                    lines.append(f"- {t['name']}: {root}")

        return {"role": "system", "content": "\n".join(lines)}

    def memory(self):
        """Hierarchical memory compression with skill-aware chain protection.

        Flow:
        1. Try skill-safe cut (protects approval chains + tool pairs)
        2. If no safe point, archive completed modules to free space, retry
        3. Fallback: original tool-pair-only protection
        4. Last resort: force-cut at midpoint with warning
        """
        self._clean_orphan_tool_messages()

        if len(self.messages) <= 5:
            return

        orig_len = len(self.messages)

        # Step 1: Try skill-safe cut
        cut_idx = self._find_skill_safe_cut_index()

        # Step 2: No safe point — try archiving completed modules to free space
        if cut_idx is None and self.pending_completion:
            print(
                "[Memory] No safe cut point found, attempting archive of completed modules...",
                file=sys.stderr,
            )
            self._archive_completed_modules()
            cut_idx = self._find_skill_safe_cut_index()

        # Step 3: Fallback to original tool-pair protection
        if cut_idx is None:
            cut_idx = self._find_safe_cut_index()

        # Step 4: Last resort
        forced = False
        if cut_idx is None or cut_idx >= len(self.messages) - 1 or cut_idx <= 1:
            cut_idx = len(self.messages) // 2 + 1
            forced = True

        dropped = cut_idx - 1

        # Build crystal degradation summary before dropping messages
        summary = self._build_degradation_summary(dropped)

        self.messages = [self.messages[0]] + self.messages[cut_idx:]

        # Rebuild metadata after cut
        self._rebuild_meta_after_cut(cut_idx)

        # Inject crystal summary after the base system prompt
        if summary:
            self.messages.insert(1, summary)
            # Shift metadata indices by 1 to account for inserted summary
            shifted_meta = {}
            for idx, meta in self.message_meta.items():
                shifted_meta[idx + 1] = meta
            self.message_meta = shifted_meta

        self._clean_orphan_tool_messages()

        # Warn if forced cut was used
        if forced:
            self.messages.append({
                "role": "system",
                "content": (
                    "⚠️ 上下文压缩被迫截断了部分审批历史，可能影响当前模块的决策追溯。"
                    "建议尽快归档已完成模块。"
                ),
            })

        print(
            f"[Memory] Compressed: {orig_len} → {len(self.messages)} messages "
            f"(dropped {dropped}, {'+summary' if summary else 'no crystals active'})",
            file=sys.stderr,
        )

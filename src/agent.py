# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Agent Module - Core Implementation of AI Agent
Provides the Crystal-Sculpt-Diffus-Coder class, responsible for interacting with AI models, tool calling, and memory management
"""

import os
import json
import sys
import time
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
## ⚠️ CRITICAL: Recall Before First Use

**For EVERY tool you plan to use for the first time in this conversation, you MUST first call `recall(memory_id="tool:<name>")` to fetch its full documentation.** The inline table below is a quick reference only — it does NOT include complete parameter details, mode descriptions, or output formats. Guessing parameters will cause errors.

Example: before your first `write` call, do `recall(memory_id="tool:write")`. Before your first `read` call, do `recall(memory_id="tool:read")`.

---

## 📌 Tool Calling Convention

Each tool is a first-class function with its own parameter schema. Call tools directly by name — the system automatically provides the correct JSON Schema for each tool's parameters.

For example, to get the current time, call `time()` with no arguments. To read a file, call `read(path="/path/to/file.py")`. The model's native function-calling mechanism handles parameter validation automatically.

---

## 🧠 Tool Usage Principles
- **Least privilege**: Only use the tools necessary to complete the task; do not misuse `command` for file operations (use `read`/`write` instead).
- **Accurate calling**: Ensure parameters are correct. The `path` parameter always uses forward slashes, even on Windows.
- **Error handling**: If a tool returns an error, check the error message and adjust your call accordingly. Use `recall` to fetch full tool documentation if needed.
- **User intent first**: Always choose tools and operations based on the user's request.
- **Use tools, not skills**: Any heading marked with "skill" is not a tool you can call; it is content you should learn.

---

## Available Tools

**The entries below are quick-reference summaries. Use `recall(memory_id="tool:<name>")` for complete parameter docs.**

| Tool | Memory ID | Purpose |
|------|-----------|---------|
| `read` | `tool:read` | Read files with 3 modes (all/lines/find), line numbers, optional AST structure. |
| `write` | `tool:write` | Propose file edits (overwrite/edit/replace/insert). Returns diff preview, no disk write. |
| `command` | `tool:command` | Execute system commands. **⚠️ File deletion is strictly prohibited — use `mv`/`move` instead.** |
| `search` | `tool:search` | Web search via DuckDuckGo (free, no API key). |
| `time` | `tool:time` | Get current system time in ISO 8601 format. |
| `add_skill` | `tool:add_skill` | Save a reusable skill as Markdown and index it into the knowledge base. |
| `set_project` | `tool:set_project` | Activate the crystal-aware engineering workflow (phases L0-L8, module tracking). |
| `crystallize` | `tool:crystallize` | Store thought crystals (contracts, traces, experience) or find existing ones by type/module/query. |
| `dependency` | `tool:dependency` | Manage the dependency graph: define modules+dependencies, analyze, recommend next, compute impact. |
| `review_approval` | `tool:review_approval` | LLM-powered review with 4 modes: general review, contract consistency check, single-step critique, iteration drift detection (L3→L7). |

---

### `recall` — Fetch Full Document or Crystal Content by ID

This is the **second level** of the two-level summary memory system. The model first sees summaries in context (from `search()` results), then calls `recall` to get the full content.

**Important: Always obtain `memory_id` from `search()` results — never guess or invent IDs.**

**Memory ID format**: `{type}:{name}` — `tool:read`, `skill:nginx-setup`, `conv:20260115-143022-a1b2c3`

**Parameters:**
- `memory_id` (string, optional if `crystal_id` provided): The document identifier.
- `crystal_id` (string, optional if `memory_id` provided): Crystal identifier, e.g. `ExperienceCrystal:proj:module.name:v1.0`.
- `query` (string, optional): Keyword to locate specific paragraphs. Returns best match + one paragraph of context.
- `lines` (string, optional): Line range like `"10-30"` or `"50"` for precise retrieval.
- `dim` (string, optional): Dimension filter — `architecture`, `contract`, `algorithm`, `implementation`, `debug`, or `meta`.

**Output**: Full or filtered document content with metadata header (source, char count, token estimate, line count). Default limit: 8000 chars.

**Examples:**

1. Fetch full docs for a tool before using it:
   ```
   recall(memory_id="tool:write")
   ```

2. Get a specific section by keyword:
   ```
   recall(memory_id="tool:write", query="edit mode")
   ```

3. Fetch a conversation backup:
   ```
   recall(memory_id="conv:20260115-143022-a1b2c3")
   ```

4. Get a specific dimension from an ExperienceCrystal:
   ```
   recall(crystal_id="ExperienceCrystal:proj:Auth.verify:v1.0", dim="debug")
   ```

**Notes:**
- When both `lines` and `query` are provided, `lines` is applied first, then `query` searches within that range.
- Only accesses files under `knowledge/`; returns an error for paths outside this directory.

---

## Coding Process

The full software engineering workflow is documented in the skill `skill:idea-to-code-sculpting`. Use `recall(memory_id="skill:idea-to-code-sculpting")` to load it when starting a complex task. Key principles:

- **Understand → Plan → Write** — the order is non-negotiable.
- **Diagnose root causes** before touching code — do not guess.
- **Edit surgically** by line numbers from `read` output — one change, one verify.
- **Minimal change** — only touch what is directly responsible; do not refactor stable code.
- **Safety first** — for delete operations, always use move instead of direct deletion.

Now you can start helping the user.

<!--
This is part of Crystal-Sculpt-Diffus-Coder
See the file COPYING for copying conditions.
-->
"""


# ── Compression prompts ───────────────────────────────────────────────
# See prompts.md for the design rationale behind these three scenarios.

COMPRESSION_PROMPT_REACTIVE = r"""Your task is to create a detailed summary of the conversation so far, focusing on preserving the project state and recent decisions essential for continuing the development. Pay special attention to the active project (if any) and the current skill phase.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, chronologically scan the conversation and identify:
- The active project ID, current phase (L0-L8), and module being worked on.
- All approved contracts (ContractCrystal IDs), their signatures, and key constraints.
- The dependency graph state (if defined) and the list of completed modules with their status.
- Recent decisions, user approvals, and any pending approval requests.
- Specific file paths, code snippets, error messages, or test outcomes mentioned in the last few exchanges.
- Any L3.1 renegotiations or bug backtracking events.

Then produce a summary using the following structure:

<summary>
1. Active Project & Phase:
   [project_id, current phase, current module if any]
2. Module & Contract Status:
   - [Module name]: [status (contracted/implemented/tested)], Contract ID: [crystal_id], Signature: [function signature], Key constraints: [...]
3. Dependency Graph:
   [If defined, include topological order and any cycle warnings]
4. Recent Decisions & Approvals:
   - [Decision 1, with approval status]
   - [...]
5. Pending Actions:
   - [Approval request, next module to implement, etc.]
6. Important Recent Messages:
   [Quote the most recent user request and your response verbatim if short; otherwise summarise with key details]
7. Next Step:
   [If known, state the next expected action, aligned with the current skill phase]
</summary>"""

COMPRESSION_PROMPT_L3_DONE = r"""You are performing a phase transition compression. The project has completed contract definition (L3) for all modules and is about to start per-module implementation (L4-L7). Your task is to create a summary that replaces all previous detailed discussion of L3 contracts, leaving only the final approved contracts and dependency relationships.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, thoroughly identify:
- Every module and its final approved contract: function signatures, preconditions, postconditions, boundary handling strategies, and the crystal ID (ContractCrystal).
- The explicitly declared dependencies between modules (from L2 ModMap) and any dependency constraints.
- Any outstanding concerns or warnings noted during L3 approval (e.g., potential performance issues, ambiguous edge cases). Do not lose these warnings.
- The decision to proceed to implementation and the expected implementation order (if already discussed).

Then produce a summary with these sections:

<summary>
1. Project & Phase Transition:
   [project_id, transitioning from L3 to L4-L7, all contracts locked]
2. Module Contract Catalog:
   For each module, provide a compact record:
   - Module: [name]
   - Contract ID: [crystal_id]
   - Signature: [function/method signature(s)]
   - Preconditions: [...]
   - Postconditions: [...]
   - Boundary handling: [...]
   - Notes/Warnings: [...]
3. Dependency Map:
   [Explicit list: ModuleA depends on ModuleB, ModuleC; ...]
   Recommended implementation order: [topological order]
4. Important Design Decisions:
   - [Any global design choices or constraints agreed during L3 phase]
5. Transition Confirmation:
   [Statement that all contracts are approved and implementation may now proceed module by module.]
</summary>"""

COMPRESSION_PROMPT_MODULE_DONE = r"""You are performing a module completion compression. The module [ModuleName] has finished implementation (L7) and testing. A new module will start next. Your task is to summarize the just-completed module's outcome and any contract changes, while discarding the detailed L4-L7 design discussions.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, identify:
- The module name and its current contract (including any L3.1 revisions that occurred during implementation). Note the final contract crystal ID.
- The implementation files and key functions created/modified, with their paths.
- The test results (pass/fail, any significant edge cases tested).
- Any bugs encountered and how they were fixed (summarize TraceCrystal if applicable).
- The decision that this module is complete and ready for integration.

Then produce a summary:

<summary>
1. Completed Module:
   - Module: [ModuleName]
   - Status: Implemented & Tested (L7 complete)
   - Final Contract ID: [crystal_id]
   - Contract Summary: [Signature, key constraints, any revisions from L3.1]
2. Implementation Artifacts:
   - File: [path] -- [function/class names] -- [brief description]
   - ...
3. Test Results:
   - [Test name]: PASS/FAIL -- [note if any known limitations]
4. Bug Fixes (if any):
   - [Symptom] -> Root cause: [cause] -> Fix: [fix]
   - TraceCrystal ID: [if applicable]
5. Next Module:
   [If known, indicate which module is next and its expected contract]
6. Transition Confirmation:
   [Module complete, context compressed; ready to start next module.]
</summary>"""


class BaseAgent:
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
        crystal_k=3,
        crystal_store=None,
        crystal_observer=None,
    ):
        """
        Initialize the agent
        """
        self.client = OpenAI(api_key=key, base_url=url, timeout=120.0)
        self.model = model
        self.user_settings = settings
        self.temperature = temperature
        self.thinking = thinking
        self.knowledge_k = knowledge_k  # Number of knowledge fragments to retrieve
        self.crystal_k = crystal_k  # Max crystal matches per query
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
        self._last_injections: list[dict] = []  # Injection metadata for SSE notices
        self._last_injected_guidance: str | None = None  # Phase guidance throttle
        self._last_guidance_token_est: int = 0  # Token position at last guidance injection
        self._last_crystal_ctx_hash: int | None = None  # Dedup crystal context on restart
        self._turn_usage = {"input": 0, "output": 0, "total": 0}  # Per-turn token tracking
        self._compression_cooldown = 0  # Suppress back-to-back reactive compression

        raw = [{}]
        if os.path.exists("messages.json"):
            try:
                with open("messages.json", "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, ValueError):
                print("[Agent] Corrupted messages.json — starting fresh.", file=sys.stderr)
                raw = [{}]
        if isinstance(raw, dict) and "messages" in raw:
            self.messages = raw["messages"]
            if not self.messages:
                self.messages = [{}]
            self.message_meta = {int(k): v for k, v in raw.get("_meta", {}).items()}
            self.module_archive_policy = raw.get("_archive_policy", {})
        elif isinstance(raw, list):
            self.messages = raw if raw else [{}]
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
                    f"[BaseAgent] Failed to save messages on exit: {e}",
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
                    new_messages.append(new_msg)
                elif new_msg.get("content"):
                    # Strip invalid tool_calls but keep the message if it has text content
                    new_msg.pop("tool_calls", None)
                    new_messages.append(new_msg)
                # else: skip empty assistant message (no content, no valid tool_calls)
            elif role == "tool":
                if msg.get("tool_call_id") in valid_ids:
                    new_messages.append(msg)
                # else discard orphan tool message (no matching assistant tool_call)
            else:
                new_messages.append(msg)
        self.messages = new_messages

    def _inject_project_context(self, messages: list[dict], *,
                                 force_guidance: bool = False,
                                 clear_module_switch: bool = True):
        """Inject phase guidance, rollback, crystal context, and module switch.

        Appends system messages to ``messages`` and populates
        ``self._last_injections`` for SSE notice emission.

        Called from _build_context() at turn start and from the set_project
        handler mid-turn so the model sees state changes immediately.
        """
        # ── Phase guidance ──────────────────────────────────────────────
        if state.phase_guidance:
            _GUIDANCE_TOKEN_INTERVAL = 50000
            current_tokens = sum(len(m.get("content", "")) for m in self.messages) // 4
            guidance_changed = (state.phase_guidance != self._last_injected_guidance)
            tokens_since = current_tokens - self._last_guidance_token_est

            if force_guidance or guidance_changed or tokens_since >= _GUIDANCE_TOKEN_INTERVAL or tokens_since < 0:
                messages.append({"role": "system", "content": state.phase_guidance})
                self._last_injections.append({
                    "source": "set_project",
                    "kind": "phase_guidance",
                    "phase": state.active_project.get("phase", "") if state.active_project else "",
                    "module": state.active_project.get("module", "") if state.active_project else "",
                    "summary": f"Phase guidance injected ({len(state.phase_guidance)} chars)",
                    "preview": state.phase_guidance[:800],
                })
                self._last_injected_guidance = state.phase_guidance
                self._last_guidance_token_est = current_tokens

        # ── Phase rollback ──────────────────────────────────────────────
        if state.phase_rollback_notice:
            notice = state.phase_rollback_notice
            phase_label = {"L3": "L3 — 模块规格书", "L4": "L4 — 自然语言算法",
                           "L6": "L6 — 代码骨架", "L7": "L7 — 完整实现"}
            to_label = phase_label.get(notice['to'], notice['to'])
            from_label = phase_label.get(notice['from'], notice['from'])

            rollback_msg = (
                f"## ⚠️ 相位回退：{from_label} → {to_label}\n\n"
                f"工作流相位已从 **{from_label}（{notice['from']}）** 回退到 **{to_label}（{notice['to']}）**"
            )
            if notice.get("module"):
                rollback_msg += f"（模块: {notice['module']}）"
            rollback_msg += (
                f"\n\n这意味着之前的设计需要重新审视。"
                f"请基于已锁定的接口契约重新开展工作。"
                f"回退前的产出不再有效，需要重新生成。"
            )
            if notice.get("previous_record"):
                rollback_msg += (
                    f"\n\n### 回退参考：{notice.get('module', '')} 在 {notice['to']} 的上一个版本\n\n"
                    f"{notice['previous_record'][:3000]}"
                )
            messages.append({"role": "system", "content": rollback_msg})
            self._last_injections.append({
                "source": "set_project",
                "kind": "phase_rollback",
                "from_phase": notice["from"],
                "to_phase": notice["to"],
                "module": notice.get("module", ""),
                "summary": f"Phase rollback: {notice['from']} → {notice['to']}"
                + (f" (module: {notice['module']})" if notice.get("module") else ""),
                "preview": rollback_msg[:800],
            })
            state.phase_rollback_notice = None

        # ── Crystal working context ─────────────────────────────────────
        if self.crystal_store and state.active_project:
            ctx = self.crystal_store.working_context(
                project_id=state.active_project.get("project_id", ""),
                phase=state.active_project.get("phase", ""),
                module=state.active_project.get("module"),
            )
            if ctx:
                ctx_hash = hash(ctx)
                if ctx_hash != self._last_crystal_ctx_hash:
                    print(
                        f"[CrystalStore] Injecting {len(ctx)} chars of engineering state "
                        f"(project={state.active_project.get('project_id', '')}, "
                        f"phase={state.active_project.get('phase', '')})",
                        file=sys.stderr,
                    )
                    messages.append({"role": "system", "content": ctx})
                    self._last_injections.append({
                        "source": "set_project",
                        "kind": "crystal_context",
                        "phase": state.active_project.get("phase", ""),
                        "module": state.active_project.get("module", ""),
                        "summary": f"Engineering crystal state ({len(ctx)} chars)"
                        + (f" for {state.active_project.get('module')}" if state.active_project.get("module") else ""),
                        "preview": ctx[:800],
                    })
                    self._last_crystal_ctx_hash = ctx_hash
            else:
                print(
                    f"[CrystalStore] No relevant crystals for "
                    f"phase={state.active_project.get('phase', '')}, module={state.active_project.get('module')}",
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

        # ── Module switch context ───────────────────────────────────────
        if state.module_switch_notice:
            if not self.crystal_store:
                print(
                    f"[ModuleSwitch] CrystalStore unavailable, clearing module_switch_notice",
                    file=sys.stderr,
                )
                state.module_switch_notice = None
            else:
                switch = state.module_switch_notice
                entry_ctx = self.crystal_store.get_module_entry_context(
                    project_id=state.active_project.get("project_id", ""),
                    module=switch["new_module"],
                )
                if entry_ctx:
                    switch_msg = (
                        f"## 🔄 模块切换：{switch['old_module']} → {switch['new_module']}\n\n"
                        f"你已切换到模块 **{switch['new_module']}**（阶段: {switch['phase']}）。"
                        f"以下是该模块及其依赖的已锁定契约，请基于这些契约开展工作。\n\n"
                        f"{entry_ctx}"
                    )
                    recommend_ctx = self._build_recommend_context(
                        project_id=state.active_project.get("project_id", ""),
                        current_module=switch["new_module"],
                    )
                    if recommend_ctx:
                        switch_msg += "\n\n" + recommend_ctx
                    messages.append({"role": "system", "content": switch_msg})
                    self._last_injections.append({
                        "source": "set_project",
                        "kind": "module_switch",
                        "old_module": switch["old_module"],
                        "new_module": switch["new_module"],
                        "phase": switch["phase"],
                        "summary": f"Module switch: {switch['old_module']} → {switch['new_module']}"
                        + f" (phase: {switch['phase']}, {len(switch_msg)} chars)",
                        "preview": switch_msg[:800],
                    })
                    print(
                        f"[CrystalStore] Module switch {switch['old_module']}→{switch['new_module']}: "
                        f"injected {len(switch_msg)} chars entry context",
                        file=sys.stderr,
                    )
                if clear_module_switch:
                    state.module_switch_notice = None

    def _build_context(self, msg: str, relevant: list[str]) -> list[dict]:
        """Assemble the message list sent to the model (without persistent history).

        Also populates self._last_injections with metadata about injected system
        messages so that input() can yield SSE notices to the frontend.
        """
        self._last_injections = []
        messages = [
            {"role": "system", "content": self.base_system_prompt}
        ]

        self._inject_project_context(messages)

        # RAG knowledge retrieval (two-level summary memory system)
        if relevant:
            knowledge_text = "\n".join(relevant)
            messages.append({
                "role": "system",
                "content": f"## 📚 相关记忆摘要\n\n{knowledge_text}",
            })
            self._last_injections.append({
                "source": "knowledge_base",
                "kind": "knowledge_summary",
                "summary": f"RAG knowledge: {len(relevant)} results ({len(knowledge_text)} chars)",
                "preview": knowledge_text[:800],
            })

        # Attach persistent message history (skip index 0 if it is the base system prompt)
        start_idx = 1 if (self.messages and self.messages[0].get("role") == "system") else 0
        messages.extend(self.messages[start_idx:])
        return messages

    def _get_relevant_knowledge(self, msg: str) -> list[str]:
        """Retrieve knowledge fragments. Phase-aware when CrystalStore is active.

        Two-level summary memory format:
          Each result string includes a memory_id reference so the model can
          call recall(memory_id="...") to fetch full original content.

        Persistent ExperienceCrystals are injected in all branches for
        cross-project knowledge transfer.
        """
        # ── Use raw user query directly for embedding search ──
        if not msg or not msg.strip():
            return []
        search_query = msg

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
            results = self._format_search_results(search(search_query, k=self.knowledge_k))
            # Inject matching persistent experiences even without active project
            results.extend(self._get_persistent_experiences(search_query))
            return results

        phase = state.active_project.get("phase", "")
        module = state.active_project.get("module", "")
        project_id = state.active_project.get("project_id", "")

        # ── L0 / L1 / L2: Project contracts ────────────────────────────
        if phase in ("L0", "L1", "L2"):
            contracts = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="ContractCrystal",
            )
            print(
                f"[CrystalStore] Phase {phase}: found {len(contracts)} project contracts",
                file=sys.stderr,
            )
            results = []
            for c in contracts[:self.crystal_k]:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                results.append(
                    f"[ContractCrystal v{c['vitality']}] {c['module']}.{c['name']}: "
                    f"signature={content.get('signature', 'N/A')}"
                )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── L3 / L3.1: Similar contracts + related traces ──────────────
        if phase in ("L3", "L3.1"):
            contracts = self.crystal_store.find_similar_contracts(msg, top_k=self.crystal_k)
            traces = self.crystal_store.find_related_traces(module or msg, top_k=max(1, self.crystal_k - 1))
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
            # L3.1 also injects the current contract being renegotiated
            if phase == "L3.1" and module:
                current = self.crystal_store.get_active_crystals(
                    project_id=state.active_project.get("project_id", ""),
                    crystal_type="ContractCrystal",
                    module=module,
                )
                for c in current[:1]:
                    content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                    results.insert(0,
                        f"[CURRENT CONTRACT — under renegotiation] {c['name']}: "
                        f"signature={content.get('signature', 'N/A')}"
                    )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── L4: Logic crystals + related traces ────────────────────────
        if phase in ("L4",):
            logics = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="LogicCrystal",
            )
            traces = self.crystal_store.find_related_traces(module or msg, top_k=self.crystal_k)
            print(
                f"[CrystalStore] Phase {phase}: found {len(logics)} logic crystals + "
                f"{len(traces)} related traces",
                file=sys.stderr,
            )
            results = []
            if logics:
                for lc in logics[:self.crystal_k]:
                    content = lc.get("content", {}) if isinstance(lc.get("content"), dict) else {}
                    steps = content.get("algorithm_steps", [])
                    # Normalize: steps may be list[str], list[dict], or dict
                    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
                        steps = [s.get("step", s.get("description", str(s))) for s in steps]
                    elif isinstance(steps, dict):
                        steps = [f"{k}: {v}" for k, v in steps.items()]
                    elif not isinstance(steps, list):
                        steps = [str(steps)]
                    steps_preview = "; ".join(steps[:3]) if steps else "N/A"
                    results.append(
                        f"[LogicCrystal v{lc['vitality']}] {lc['module']}.{lc['name']}: "
                        f"steps={steps_preview}"
                    )
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                results.append(
                    f"[TraceCrystal] {t['name']}: root_cause={content.get('root_cause', 'N/A')}"
                )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── L5: Logic crystals + Skeleton crystals + traces ────────────
        if phase in ("L5",):
            logics = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="LogicCrystal",
                module=module,
            )
            skeletons = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="SkeletonCrystal",
                module=module,
            )
            traces = self.crystal_store.find_related_traces(module or msg, top_k=2)
            print(
                f"[CrystalStore] Phase {phase}: found {len(logics)} logic + "
                f"{len(skeletons)} skeleton + {len(traces)} traces",
                file=sys.stderr,
            )
            results = []
            for lc in (logics or [])[:self.crystal_k]:
                content = lc.get("content", {}) if isinstance(lc.get("content"), dict) else {}
                steps = content.get("algorithm_steps", [])
                # Normalize: steps may be list[str], list[dict], or dict
                if isinstance(steps, list) and steps and isinstance(steps[0], dict):
                    steps = [s.get("step", s.get("description", str(s))) for s in steps]
                elif isinstance(steps, dict):
                    steps = [f"{k}: {v}" for k, v in steps.items()]
                elif not isinstance(steps, list):
                    steps = [str(steps)]
                steps_preview = "; ".join(steps[:3]) if steps else "N/A"
                results.append(
                    f"[LogicCrystal v{lc['vitality']}] {lc['module']}.{lc['name']}: "
                    f"steps={steps_preview}"
                )
            for sk in (skeletons or [])[:self.crystal_k]:
                content = sk.get("content", {}) if isinstance(sk.get("content"), dict) else {}
                code = content.get("code_skeleton", "")
                code_preview = code[:200] if code else "N/A"
                results.append(
                    f"[SkeletonCrystal v{sk['vitality']}] {sk['module']}.{sk['name']}: "
                    f"code={code_preview}"
                )
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                results.append(
                    f"[TraceCrystal] {t['name']}: root_cause={content.get('root_cause', 'N/A')}"
                )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── L6 / L7: Traces + Skeleton/Impl crystals ───────────────────
        if phase in ("L6", "L7"):
            traces = self.crystal_store.find_related_traces(module or msg, top_k=self.crystal_k)
            # Also look for existing skeletons/impls for this module
            skeletons = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="SkeletonCrystal",
                module=module,
            )
            impls = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="ImplCrystal",
                module=module,
            )
            print(
                f"[CrystalStore] Phase {phase}: found {len(traces)} traces + "
                f"{len(skeletons)} skeleton + {len(impls)} impl",
                file=sys.stderr,
            )
            results = []
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                results.append(
                    f"[TraceCrystal] {t['name']}: "
                    f"symptom={content.get('symptom', 'N/A')}, "
                    f"fix={content.get('fix', 'N/A')}"
                )
            for sk in (skeletons or [])[:max(1, self.crystal_k - len(traces))]:
                content = sk.get("content", {}) if isinstance(sk.get("content"), dict) else {}
                lang = content.get("language", "")
                results.append(
                    f"[SkeletonCrystal v{sk['vitality']}] {sk['module']}.{sk['name']}"
                    + (f" ({lang})" if lang else "")
                )
            for imp in (impls or [])[:max(1, self.crystal_k - len(traces) - len(skeletons or []))]:
                content = imp.get("content", {}) if isinstance(imp.get("content"), dict) else {}
                lang = content.get("language", "")
                results.append(
                    f"[ImplCrystal v{imp['vitality']}] {imp['module']}.{imp['name']}"
                    + (f" ({lang})" if lang else "")
                )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── L8: All traces + full contract chain ───────────────────────
        if phase in ("L8",):
            traces = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="TraceCrystal",
            )
            contracts = self.crystal_store.get_active_crystals(
                project_id=state.active_project.get("project_id", ""),
                crystal_type="ContractCrystal",
            )
            print(
                f"[CrystalStore] Phase {phase}: found {len(traces)} traces + "
                f"{len(contracts)} contracts",
                file=sys.stderr,
            )
            results = []
            for t in (traces or [])[:self.crystal_k]:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                results.append(
                    f"[TraceCrystal] {t['name']}: "
                    f"symptom={content.get('symptom', 'N/A')}, "
                    f"root_cause={content.get('root_cause', 'N/A')}"
                )
            for c in (contracts or [])[:self.crystal_k]:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                results.append(
                    f"[ContractCrystal v{c['vitality']}] {c['module']}.{c['name']}: "
                    f"{'✅' if content.get('has_implementation') else '⏳'} "
                    f"signature={content.get('signature', 'N/A')}"
                )
            if not results:
                results = self._format_search_results(search(search_query, k=self.knowledge_k))
            else:
                results.extend(self._format_search_results(search(search_query, k=2)))
            results.extend(self._get_persistent_experiences(search_query))
            return results

        # ── Fallback: no active project or unrecognized phase ──────────
        results = self._format_search_results(search(search_query, k=self.knowledge_k))
        results.extend(self._get_persistent_experiences(search_query))
        return results

    def _get_persistent_experiences(self, msg: str) -> list[str]:
        """Fetch persistent ExperienceCrystals matching the current message.

        Returns formatted strings with crystal_id references so the model
        can call recall(crystal_id="...") for full details.
        """
        if not self.crystal_store:
            return []

        persistent = self.crystal_store.get_persistent_crystals("ExperienceCrystal")
        if not persistent:
            return []

        # Simple keyword matching
        msg_lower = msg.lower()
        matched = []
        for c in persistent:
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            title = content.get("title", c.get("name", ""))
            summary = content.get("summary", "")
            tags = content.get("tags", [])
            combined = f"{title} {summary} {' '.join(tags)}".lower()

            score = 0
            for word in msg_lower.split():
                if len(word) >= 2 and word in combined:
                    score += 1
            if score == 0:
                continue

            crystal_id_str = (
                f"ExperienceCrystal:{c.get('project_id', '')}:"
                f"{c.get('module', '')}.{c.get('name', '')}:v1.0"
            )
            refs = content.get("reference_values", {})
            dim_tags = [
                f"[{d}]" for d in ("debug", "architecture", "implementation",
                                   "contract", "algorithm", "meta")
                if refs.get(d) and isinstance(refs.get(d), str) and len(refs[d]) > 5
            ]

            line = (
                f"- **{crystal_id_str}** | 🧠 经验"
                f"{('：' + title) if title else ''}\n"
                f"  {summary}\n"
            )
            if dim_tags:
                line += f"  可用维度：{' '.join(dim_tags)}\n"
            line += f"  → 使用 `recall(memory_id=\"{crystal_id_str}\")` 查看完整经验"
            matched.append((score, line))

        matched.sort(key=lambda x: x[0], reverse=True)
        return [line for _, line in matched[:2]]

    def _format_search_results(self, results: list[dict]) -> list[str]:
        """Format structured search results with memory_id for recall tool.

        Each result becomes a markdown bullet with memory_id reference
        so the model can call recall(memory_id="...") for full details.
        Prefers main_summary over truncated text when available.
        Appends dimension tags below the summary for multi-dimensional entries.
        For experience_crystal type, uses crystal_id reference.
        """
        formatted = []
        for r in results:
            mid = r.get("memory_id")
            doc_type = r.get("type", "")
            icon = r.get("icon", "📄")
            title = r.get("title", "")
            main_summary = r.get("main_summary")
            dimensions = r.get("dimensions", [])
            text = r.get("text", "")

            # Prefer main_summary, fallback to truncated text
            if main_summary:
                summary = main_summary
            else:
                summary = text[:200] if len(text) > 200 else text

            is_experience = doc_type == "experience_crystal"

            if mid:
                line = (
                    f"- **{mid}** | {icon}"
                    f"{('：' + title) if title else ''}\n"
                    f"  {summary}\n"
                )
                # Append dimension lines
                for d in dimensions:
                    if isinstance(d, dict) and d.get("dim") and d.get("summary"):
                        line += f"    [{d['dim']}] {d['summary']}\n"
                if is_experience:
                    line += (
                        f"  → 使用 `recall(memory_id=\"{mid}\", dim=\"<维度>\")` "
                        f"查看特定维度的参考建议"
                    )
                else:
                    line += f"  → 使用 `recall(memory_id=\"{mid}\")` 查看原文"
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
        if not self._input_lock.acquire(timeout=30):
            raise RuntimeError(
                "Another request is in progress for this agent. "
                "Please wait and retry."
            )
        self._turn_usage = {"input": 0, "output": 0, "total": 0}
        try:
            max_restarts = 3
            restart = True
            first_entry = True

            while restart and max_restarts > 0:
                restart = False
                _should_exit = False
                max_restarts -= 1

                # 0. Phase transition compression — L3→L4: all contracts locked,
                #    entering per-module implementation. Compress L3 negotiation
                #    history into a contract catalog before heavy L4-L7 work.
                if state.phase_transition_notice:
                    ptn = state.phase_transition_notice
                    print(
                        f"[Memory] Phase transition compression triggered: "
                        f"{ptn['from']}→{ptn['to']}",
                        file=sys.stderr,
                    )
                    # Generate contract catalog summary of all L3 negotiation
                    l3_summary, l3_max_idx = self._compress_l3_done()
                    if l3_summary:
                        self.messages.append({
                            "role": "system",
                            "content": l3_summary,
                        })
                        print(
                            f"[Memory] L3→L4: injected contract catalog "
                            f"({len(l3_summary)} chars)",
                            file=sys.stderr,
                        )
                    before_count = len(self.messages)
                    self._proactive_cut(l3_max_idx)
                    after_count = len(self.messages)
                    cut_count = before_count - after_count
                    print(
                        f"[Memory] Phase transition result: {before_count}→{after_count} "
                        f"(cut {cut_count} messages)",
                        file=sys.stderr,
                    )
                    if cut_count > 0:
                        yield {
                            "type": "compression",
                            "cut_messages": cut_count,
                            "remaining_messages": after_count,
                            "reason": "phase_transition",
                            "from_phase": ptn["from"],
                            "to_phase": ptn["to"],
                        }

                    state.phase_transition_notice = None

                # 0.5 Module switch compression — fires when set_project changes
                #     module within the same project (e.g. Auth→API after L7 done).
                #     Skip at L3/L3.1: switching modules during contract-first
                #     negotiation keeps all contract history as cross-module context.
                if (state.module_switch_notice
                        and state.module_switch_notice.get("phase", "") not in ("L3", "L3.1")):
                    switch = state.module_switch_notice
                    print(
                        f"[ModuleSwitch] Proactive compression triggered: "
                        f"{switch['old_module']}→{switch['new_module']} ({switch['phase']})",
                        file=sys.stderr,
                    )
                    # Generate completion summary for the just-finished module
                    mod_summary, mod_max_idx = self._compress_module_done(switch["old_module"])
                    if mod_summary:
                        self.messages.append({
                            "role": "system",
                            "content": mod_summary,
                        })
                        print(
                            f"[ModuleSwitch] Injected {switch['old_module']} "
                            f"completion summary ({len(mod_summary)} chars)",
                            file=sys.stderr,
                        )
                    before_count = len(self.messages)
                    self._proactive_cut(mod_max_idx)
                    after_count = len(self.messages)
                    cut_count = before_count - after_count
                    print(
                        f"[ModuleSwitch] Compression result: {cut_count} messages cut "
                        f"({before_count}→{after_count})",
                        file=sys.stderr,
                    )
                    if cut_count > 0:
                        yield {
                            "type": "compression",
                            "cut_messages": cut_count,
                            "remaining_messages": after_count,
                            "reason": "module_switch",
                            "old_module": switch["old_module"],
                            "new_module": switch["new_module"],
                        }

                # Capture restart flag before first_entry block clears it
                is_restart = not first_entry

                if first_entry:
                    first_entry = False

                    # 1. Persist the current user message
                    self._append_message("user", msg)

                    # 1.5 Detect pending completion confirmation from previous turn
                    if self._detect_completion_confirmation(msg):
                        self._archive_completed_modules()
                    elif self.pending_completion:
                        pending_mod = self.pending_completion["module"]
                        print(
                            f"[Archive] Module {pending_mod} completion NOT confirmed, "
                            f"clearing pending marker",
                            file=sys.stderr,
                        )
                        self.pending_completion = None

                # 2. Retrieve relevant knowledge (re-run on restart — state may have changed)
                relevant = self._get_relevant_knowledge(msg)

                # 3. Build context (re-run on restart — _inject_project_context picks up new state)
                api_messages = self._build_context(msg, relevant)

                # 3.5 Yield system injection notices to frontend
                if self._last_injections:
                    for inj in self._last_injections:
                        yield {"type": "system_injection", **inj}
                    self._last_injections = []

                # 4. On outer-loop restart, signal frontend to create a new bubble
                if is_restart:
                    yield {"type": "context_restart"}

                # Make a working copy for the tool call loop
                current_api_messages = api_messages.copy()

                max_iterations = 50
                iteration = 0
                while True:
                    iteration += 1
                    if iteration >= max_iterations:
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
                                stream_options={"include_usage": True},
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
                                stream_options={"include_usage": True},
                                extra_body={"thinking": {"type": "disabled"}},
                            )

                        full_content = ""  # Accumulate complete response
                        full_reasoning = ""  # Accumulate reasoning (if enabled)
                        tool_calls_data = {}  # Store tool call data
                        turn_usage = None  # Token usage from this API call

                        # Process streaming response
                        for chunk in stream:
                            if hasattr(chunk, "usage") and chunk.usage:
                                turn_usage = {
                                    "input": chunk.usage.prompt_tokens or 0,
                                    "output": chunk.usage.completion_tokens or 0,
                                    "total": chunk.usage.total_tokens or 0,
                                }
                            if not chunk.choices:
                                continue
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

                        # Accumulate token usage from this API call
                        if turn_usage:
                            self._turn_usage["input"] += turn_usage["input"]
                            self._turn_usage["output"] += turn_usage["output"]
                            self._turn_usage["total"] += turn_usage["total"]

                        # If no tool calls, finish
                        if not tool_calls_data:
                            extra = {}
                            if assistant_message.get("reasoning_content"):
                                extra["reasoning_content"] = assistant_message["reasoning_content"]
                            if assistant_message.get("tool_calls") is not None:
                                extra["tool_calls"] = assistant_message["tool_calls"]
                            self._append_message("assistant", full_content, **extra)
                            self._save_messages()

                            # CrystalObserver auto-extraction (background, non-blocking)
                            if self.crystal_observer and state.active_project:
                                observer = self.crystal_observer
                                project_snapshot = dict(state.active_project)
                                turn_msgs = [
                                    m for m in self.messages[-8:]
                                    if m.get("role") in ("user", "assistant", "tool")
                                ]
                                def _run_observer():
                                    try:
                                        cid = observer.analyze_turn(
                                            turn_msgs, project_snapshot
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
                                threading.Thread(target=_run_observer, daemon=True).start()

                            if self._turn_usage["total"] > 0:
                                yield {
                                    "type": "token_usage",
                                    "input_tokens": self._turn_usage["input"],
                                    "output_tokens": self._turn_usage["output"],
                                    "total_tokens": self._turn_usage["total"],
                                }
                            return

                        # Execute tool calls one by one
                        tool_messages = []
                        tool_call = None  # ensure defined for finally block
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
                                    raw_args = tool_call['function']['arguments']
                                    hint = ""
                                    if "\n" in raw_args:
                                        hint = " (Hint: newlines in JSON must be escaped as \\n, not literal newlines)"
                                    raise ValueError(
                                        f"JSON parsing error: {e}.{hint} Raw arguments: {raw_args}"
                                    )

                                # Guard against null arguments from malformed tool calls
                                if arguments is None:
                                    arguments = {}

                                # Determine the actual tool name — func_name IS the tool name
                                # since each tool is now a first-class function.
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

                                # Record tool_call event in development journal
                                _start_time = time.time()
                                if state.journal:
                                    proj = state.active_project
                                    state.journal.record_event(
                                        "tool_call",
                                        project_id=proj.get("project_id") if proj else None,
                                        phase=proj.get("phase") if proj else None,
                                        module=proj.get("module") if proj else None,
                                        data={
                                            "tool_name": actual_tool_name,
                                            "arguments": arguments,
                                            "call_id": call_id,
                                        },
                                    )

                                result = None
                                # 2. Handle tool execution based on type
                                if actual_tool_name == "command":
                                    # Extract command string and classify risk level
                                    cmd_str = arguments.get("command", "")
                                    from knowledge.tools.command import classify_command
                                    risk = classify_command(cmd_str) if cmd_str else "dangerous"

                                    if risk == "forbidden":
                                        # Deletion commands are hard-blocked by tool.py
                                        func = self.tool_functions.get(func_name)
                                        result = func(**arguments) if func else f"Error: unknown tool {func_name}"
                                    elif risk == "safe":
                                        # Read-only commands — execute directly
                                        func = self.tool_functions.get(func_name)
                                        if func:
                                            result = func(**arguments)
                                        else:
                                            result = f"Error: unknown tool {func_name}"
                                    else:
                                        # Dangerous commands — require confirmation with warning
                                        confirm_id = str(uuid.uuid4())
                                        approved = yield {
                                            "type": "confirmation_required",
                                            "confirm_id": confirm_id,
                                            "call_id": call_id,
                                            "tool_name": actual_tool_name,
                                            "arguments": arguments,
                                            "warning": (
                                                "This command may modify files or system state. "
                                                "Please review carefully before approving."
                                            ),
                                        }
                                        if approved:
                                            func = self.tool_functions.get(func_name)
                                            if func:
                                                result = func(**arguments)
                                            else:
                                                result = f"Error: unknown tool {func_name}"
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=proj.get("phase") if proj else None,
                                                    module=proj.get("module") if proj else None,
                                                    data={
                                                        "approval_type": "confirmation_required",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "approved",
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                        else:
                                            result = f"Tool '{actual_tool_name}' execution was rejected by the user."
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=proj.get("phase") if proj else None,
                                                    module=proj.get("module") if proj else None,
                                                    data={
                                                        "approval_type": "confirmation_required",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "rejected",
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                elif actual_tool_name == "write":
                                    # Write tools use proposal-review-overwrite mode.
                                    # The tool returns a string split by ---FILE_CONTENT---:
                                    #   part 0: diff/structure (for agent history, ~300-600 chars)
                                    #   part 1: full file content (for frontend review)
                                    func = self.tool_functions.get(func_name)
                                    if func:
                                        ai_content_raw = str(func(**arguments))
                                    else:
                                        ai_content_raw = f"Error: unknown tool {func_name}"

                                    if "---FILE_CONTENT---" not in ai_content_raw:
                                        # Error or unexpected output — feed back to model
                                        # directly, no proposal UI needed
                                        result = ai_content_raw
                                    else:
                                        parts = ai_content_raw.split("---FILE_CONTENT---", 1)
                                        agent_result = parts[0].strip()
                                        full_content = parts[1].strip()

                                        confirm_id = str(uuid.uuid4())
                                        result = yield {
                                            "type": "write_proposal",
                                            "confirm_id": confirm_id,
                                            "call_id": call_id,
                                            "tool_name": actual_tool_name,
                                            "arguments": arguments,
                                            "content": full_content,
                                        }
                                        if result is True or isinstance(result, str):
                                            # True = simple approval; str = user-edited final content
                                            result = agent_result
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=proj.get("phase") if proj else None,
                                                    module=proj.get("module") if proj else None,
                                                    data={
                                                        "approval_type": "write_proposal",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "approved",
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                        elif not result or result is False:
                                            result = f"Tool '{actual_tool_name}' proposal was rejected by the user."
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=proj.get("phase") if proj else None,
                                                    module=proj.get("module") if proj else None,
                                                    data={
                                                        "approval_type": "write_proposal",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "rejected",
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                        elif isinstance(result, dict) and not result.get("approved", True):
                                            reason = result.get("reason", "")
                                            result = (
                                                f"Tool '{actual_tool_name}' proposal was rejected by the user."
                                                + (f" User feedback: {reason}" if reason else "")
                                            )
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=proj.get("phase") if proj else None,
                                                    module=proj.get("module") if proj else None,
                                                    data={
                                                        "approval_type": "write_proposal",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "rejected",
                                                        "user_feedback": reason,
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                elif actual_tool_name == "request_approval":
                                    # Atomically store ModuleRecord snapshot AND present
                                    # content to user for approval.  This replaces the
                                    # old set_project(action="record") which unreliably
                                    # auto-captured "most recent assistant message".
                                    import json as _json

                                    # arguments = {phase, module, content, files, summary}

                                    # Store the snapshot immediately
                                    func = self.tool_functions.get(func_name)
                                    if func:
                                        try:
                                            result_str = func(**arguments)
                                            result_data = _json.loads(result_str)
                                        except _json.JSONDecodeError:
                                            # Tool succeeded but returned non-JSON — accept as-is
                                            result_data = None
                                        except Exception:
                                            result_str = "Error: request_approval tool failed"
                                            result_data = None
                                    else:
                                        result_str = f"Error: unknown tool {func_name}"
                                        result_data = None

                                    if result_data and result_data.get("status") == "stored":
                                        confirm_id = str(uuid.uuid4())

                                        # ── Build context snapshot (方案C) ──
                                        proj = state.active_project
                                        context_snapshot = {
                                            "project_id": proj.get("project_id", "") if proj else "",
                                            "active_phase": proj.get("phase", "") if proj else "",
                                            "active_module": proj.get("module", "") if proj else "",
                                            "request_phase": result_data.get("phase", ""),
                                            "request_module": result_data.get("module", ""),
                                            "target_module": result_data.get("target_module", ""),
                                            "target_phase": result_data.get("target_phase", ""),
                                        }

                                        event_data = {
                                            "type": "approval_required",
                                            "confirm_id": confirm_id,
                                            "call_id": call_id,
                                            "tool_name": actual_tool_name,
                                            "phase": result_data.get("phase", ""),
                                            "module": result_data.get("module", ""),
                                            "content": result_data.get("content", ""),
                                            "files": result_data.get("files", []),
                                            "file_contents": result_data.get("file_contents", {}),
                                            "summary": arguments.get("summary", ""),
                                            "crystal_id": result_data.get("crystal_id", ""),
                                            "context_snapshot": context_snapshot,
                                        }

                                        # ── Cross-module review data ──
                                        target_module = result_data.get("target_module", "")
                                        if target_module:
                                            event_data["target_module"] = target_module
                                            event_data["target_phase"] = result_data.get("target_phase", "")
                                            event_data["original_content"] = result_data.get("original_content", "")
                                            event_data["original_files"] = result_data.get("original_files", [])
                                            event_data["original_file_contents"] = result_data.get("original_file_contents", {})
                                            event_data["original_summary"] = result_data.get("original_summary", "")

                                        approved = yield event_data
                                        if approved:
                                            # Could be True or a dict {"approved": true, ...}
                                            is_approved = approved if isinstance(approved, bool) else approved.get("approved", False)
                                            if is_approved:
                                                result = (
                                                    f"Approved. Snapshot stored: "
                                                    f"{result_data.get('crystal_id', '')}. "
                                                    f"Now call crystallize(...) to store the "
                                                    f"final crystal product."
                                                )
                                                restart = True
                                                if state.journal:
                                                    proj = state.active_project
                                                    state.journal.record_event(
                                                        "approval",
                                                        project_id=proj.get("project_id") if proj else None,
                                                        phase=result_data.get("phase"),
                                                        module=result_data.get("module"),
                                                        data={
                                                            "approval_type": "approval_required",
                                                            "tool_name": actual_tool_name,
                                                            "decision": "approved",
                                                            "confirm_id": confirm_id,
                                                        },
                                                    )
                                                print(
                                                    f"[Restart] request_approval approved "
                                                    f"(phase={result_data.get('phase', '')}, "
                                                    f"module={result_data.get('module', '')}), "
                                                    f"restarting outer loop",
                                                    file=sys.stderr,
                                                )
                                            else:
                                                reason = approved.get("reason", "") if isinstance(approved, dict) else ""
                                                result = (
                                                    f"Rejected. The snapshot was stored but "
                                                    f"the user wants changes."
                                                    + (f" User feedback: {reason}" if reason else "")
                                                    + f" Please revise the {result_data.get('phase', '')} output "
                                                    f"for module '{result_data.get('module', '')}' "
                                                    f"and call request_approval again."
                                                )
                                                if state.journal:
                                                    proj = state.active_project
                                                    state.journal.record_event(
                                                        "approval",
                                                        project_id=proj.get("project_id") if proj else None,
                                                        phase=result_data.get("phase"),
                                                        module=result_data.get("module"),
                                                        data={
                                                            "approval_type": "approval_required",
                                                            "tool_name": actual_tool_name,
                                                            "decision": "rejected",
                                                            "user_feedback": reason,
                                                            "confirm_id": confirm_id,
                                                        },
                                                    )
                                        else:
                                            result = (
                                                f"Rejected. The snapshot was stored but "
                                                f"the user wants changes. Please revise "
                                                f"the {result_data.get('phase', '')} output "
                                                f"for module '{result_data.get('module', '')}' "
                                                f"and call request_approval again."
                                            )
                                            if state.journal:
                                                proj = state.active_project
                                                state.journal.record_event(
                                                    "approval",
                                                    project_id=proj.get("project_id") if proj else None,
                                                    phase=result_data.get("phase"),
                                                    module=result_data.get("module"),
                                                    data={
                                                        "approval_type": "approval_required",
                                                        "tool_name": actual_tool_name,
                                                        "decision": "rejected",
                                                        "confirm_id": confirm_id,
                                                    },
                                                )
                                    else:
                                        result = result_str
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

                                # Record tool_result event in development journal
                                if state.journal:
                                    duration_ms = int((time.time() - _start_time) * 1000)
                                    proj = state.active_project
                                    result_str = str(result) if result is not None else ""
                                    state.journal.record_event(
                                        "tool_result",
                                        project_id=proj.get("project_id") if proj else None,
                                        phase=proj.get("phase") if proj else None,
                                        module=proj.get("module") if proj else None,
                                        data={
                                            "tool_name": actual_tool_name,
                                            "call_id": call_id,
                                            "success": "Error" not in result_str,
                                            "result_summary": result_str[:500] if result_str else "",
                                            "duration_ms": duration_ms,
                                        },
                                    )

                                # 4.5 set_project: exit the generator so the user can inject
                                #     the next prompt with fresh phase/crystal state.
                                #     (Do NOT restart — that would waste an API call in
                                #      a context the user hasn't had a chance to shape.)
                                if actual_tool_name == "set_project" and result and "Error" not in str(result):
                                    action = arguments.get("action", "activate")

                                    if action == "activate" and state.active_project:
                                        _should_exit = True
                                        yield {
                                            "type": "project_state",
                                            "active": True,
                                            "project_id": state.active_project.get("project_id", ""),
                                            "phase": state.active_project.get("phase", ""),
                                            "module": state.active_project.get("module", ""),
                                        }
                                        yield str(result)

                                    elif action == "deactivate":
                                        _should_exit = True
                                        yield {
                                            "type": "project_state",
                                            "active": False,
                                        }
                                        yield str(result)

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
                                # Record error event in development journal
                                if state.journal:
                                    import traceback as _tb
                                    proj = state.active_project
                                    _err_tool_name = locals().get('actual_tool_name', 'unknown')
                                    state.journal.record_event(
                                        "error",
                                        project_id=proj.get("project_id") if proj else None,
                                        phase=proj.get("phase") if proj else None,
                                        module=proj.get("module") if proj else None,
                                        data={
                                            "error_type": type(e).__name__,
                                            "error_message": str(e)[:500],
                                            "context": f"tool:{_err_tool_name}",
                                            "traceback": _tb.format_exc()[:1000],
                                        },
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
                                try:
                                    if tool_message:
                                        tool_messages.append(tool_message)
                                except Exception:
                                    pass

                        # 5. Always persist assistant message and tool results to history.
                        #    This must happen before the restart check so the outer
                        #    loop's _build_context() picks them up via self.messages[1:].
                        extra = {}
                        if assistant_message.get("reasoning_content"):
                            extra["reasoning_content"] = assistant_message["reasoning_content"]
                        if assistant_message.get("tool_calls") is not None:
                            extra["tool_calls"] = assistant_message["tool_calls"]
                        self._append_message("assistant", full_content, **extra)
                        for tm in tool_messages:
                            self._append_message("tool", tm["content"], tool_call_id=tm["tool_call_id"])

                        # 6. Monitor crystallize(ImplCrystal) for module completion detection
                        if self.crystal_store and state.active_project:
                            for tm in tool_messages:
                                cid = tm.get("tool_call_id", "")
                                for tc in (assistant_message.get("tool_calls") or []):
                                    if tc["id"] == cid:
                                        try:
                                            tc_args = json.loads(tc["function"]["arguments"])
                                        except (json.JSONDecodeError, KeyError):
                                            continue
                                        if (tc["function"]["name"] == "crystallize"
                                                and tc_args.get("crystal_type") == "ImplCrystal"):
                                            module_name = tc_args.get("module")
                                            project_id = state.active_project.get("project_id")
                                            if project_id and module_name:
                                                self._mark_module_pending_completion(project_id, module_name)
                                        break

                        # 7. If a tool signalled restart or exit, leave the inner loop.
                        if restart or _should_exit:
                            break

                        # 8. Otherwise feed tool results back into the API message
                        #    list and continue the tool-calling loop.
                        current_api_messages.extend(tool_messages)

                    except Exception as e:
                        # If API call fails due to context length, compress and retry
                        error_str = str(e).lower()
                        if (
                            "context length" in error_str
                            or "too long" in error_str
                            or ("token" in error_str and "context" in error_str)
                        ):
                            print(
                                f"[Memory] Reactive compression triggered by context error: {str(e)[:120]}",
                                file=sys.stderr,
                            )
                            # Compress messages and retry
                            before_count = len(self.messages)
                            self.memory()
                            after_count = len(self.messages)
                            cut_count = before_count - after_count
                            print(
                                f"[Memory] Reactive result: {before_count}→{after_count} "
                                f"(cut {cut_count} messages)",
                                file=sys.stderr,
                            )
                            # Save flags before _build_context (which may consume
                            # them), then restore so the outer loop still sees them.
                            _saved_switch = state.module_switch_notice
                            _saved_phase_trans = state.phase_transition_notice
                            _saved_restart = restart
                            _saved_exit = _should_exit
                            current_api_messages = self._build_context(msg, relevant)
                            state.module_switch_notice = _saved_switch
                            state.phase_transition_notice = _saved_phase_trans
                            restart = _saved_restart
                            _should_exit = _saved_exit
                            # Clear injection notices without re-yielding — they
                            # were already sent at the start of this outer iteration.
                            self._last_injections = []
                            # Yield compression notice to frontend (only if something was cut)
                            if cut_count > 0:
                                yield {
                                    "type": "compression",
                                    "cut_messages": cut_count,
                                    "remaining_messages": after_count,
                                }
                            iteration -= 1  # compression retry doesn't consume iteration budget
                            continue
                        else:
                            # Re-raise other exceptions
                            raise

                if restart:
                    # Restart outer loop to rebuild context with updated
                    # phase/crystal/module state from request_approval.
                    continue

                # set_project exit or normal completion — save and return
                if self._turn_usage["total"] > 0:
                    yield {
                        "type": "token_usage",
                        "input_tokens": self._turn_usage["input"],
                        "output_tokens": self._turn_usage["output"],
                        "total_tokens": self._turn_usage["total"],
                    }
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
            self._compression_cooldown = 0  # Reset for next turn
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

        for cut_idx in range(2, len(self.messages) + 1):
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

        Only tracks one module at a time — if multiple ImplCrystals complete
        in the same turn, the last one wins. This is an acceptable limitation
        since multiple module completions in a single turn are extremely rare.
        """
        self.pending_completion = {
            "project_id": project_id,
            "module": module_name,
        }
        # Avoid duplicate markers — check if one already exists for this module
        marker_content = (
            f"[模块完成标记] {module_name} 的实现已通过 ImplCrystal 记录。"
            f"请在回复末尾询问用户是否确认归档该模块（回复\"确认归档\"以归档）。"
        )
        for m in self.messages:
            if m.get("role") == "system" and m.get("content") == marker_content:
                return
        self.messages.append({
            "role": "system",
            "content": marker_content,
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

        for cut_idx in range(2, len(self.messages) + 1):
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
        """Build an archive summary for a module from CrystalStore.

        Uses ContractCrystal, LogicCrystal, ImplCrystal when available.
        Falls back to ModuleRecord data when primary crystals are missing.
        """
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

        # ModuleRecord fallback
        records = self.crystal_store.get_module_records(project_id)
        l3_records = [
            r for r in records
            if r.get("module") == module_name
            and isinstance(r.get("content"), dict)
            and r["content"].get("record_type") == "L3_snapshot"
        ]
        l7_records = [
            r for r in records
            if r.get("module") == module_name
            and isinstance(r.get("content"), dict)
            and r["content"].get("record_type") == "L7_snapshot"
        ]

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
        elif l3_records:
            r = l3_records[0]
            rc = r["content"]
            sig = rc.get("contract_signature", "")
            if sig:
                lines.append(f"**L3 契约**：{sig}")
                reneg = rc.get("renegotiation_notes", "")
                if reneg:
                    lines.append(f"  复议记录：{reneg}")
                lines.append("")

        if logic:
            l = logic[0]
            content = l.get("content", {}) if isinstance(l.get("content"), dict) else {}
            steps = content.get("algorithm_steps", [])
            # Normalize: steps may be list[str], list[dict], or dict
            if isinstance(steps, dict):
                steps = [f"{k}: {v}" for k, v in steps.items()]
            elif isinstance(steps, list) and steps and isinstance(steps[0], dict):
                steps = [s.get("step", s.get("description", str(s))) for s in steps]
            elif not isinstance(steps, list):
                steps = [str(steps)]
            if steps:
                steps_str = " → ".join(steps[:6])
                lines.append(f"**L4 算法**：{steps_str}")
                lines.append("")
        elif l7_records:
            r = l7_records[0]
            algo = r["content"].get("algorithm_summary", "")
            if algo:
                lines.append(f"**算法摘要**：{algo}")
                lines.append("")

        if impls:
            imp = impls[0]
            impl_content = imp.get("content", {}) if isinstance(imp.get("content"), dict) else {}
            lang = impl_content.get("language", "")
            lines.append(f"**L7 实现**：{imp['name']}{' (' + lang + ')' if lang else ''}，通过最小测试")
            lines.append("")
        elif l7_records:
            r = l7_records[0]
            files = r["content"].get("impl_files", [])
            tests = r["content"].get("test_results", "")
            if files:
                lines.append(f"**实现文件**：{', '.join(files[:5])}")
            if tests:
                lines.append(f"**测试结果**：{tests}")
            lines.append("")

        # Renegotiation notes
        reneg_notes = ""
        for rec in l3_records + l7_records:
            notes = rec.get("content", {}).get("renegotiation_notes", "")
            if notes:
                reneg_notes += f"  - {notes}\n"
        lines.append(f"**变更记录**：{reneg_notes if reneg_notes else '无契约复议'}")
        lines.append("")

        crystal_refs = []
        for c in contracts[:1]:
            crystal_refs.append(f"contract:{module_name}:{c['name']}")
        for imp in impls[:1]:
            crystal_refs.append(f"impl:{module_name}:{imp['name']}")
        for rec in l3_records[:1]:
            crystal_refs.append(f"modrec:{module_name}:{rec['name']}")
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
            print(
                f"[Archive] Module {module_name}: _build_module_summary returned empty, "
                f"pending_completion preserved for retry",
                file=sys.stderr,
            )
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
        if archived:
            self.pending_completion = None
            self._compact_messages()
        return archived

    def _compact_messages(self):
        """Trigger garbage collection of replaced message list segments."""
        self._save_messages()

    def _build_recommend_context(self, project_id: str, current_module: str) -> str:
        """Build context showing recommended next modules and their L3 contracts.

        Reads the DependencyGraphCrystal to find modules whose dependencies are
        all satisfied, then injects their L3 contracts so the agent knows what
        it can work on after finishing the current module.
        """
        if not self.crystal_store:
            return ""

        import json as _json

        dep_crystals = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        if not dep_crystals:
            return ""

        graph_data = dep_crystals[0].get("content", {})
        if isinstance(graph_data, str):
            try:
                graph_data = _json.loads(graph_data)
            except (_json.JSONDecodeError, TypeError):
                return ""

        graph = graph_data.get("graph", {})
        module_status = graph_data.get("module_status", {})

        if not graph:
            return ""

        # Extract completed modules from module_status
        completed: set[str] = set()
        for mod, status in module_status.items():
            if status == "implemented":
                completed.add(mod)

        from knowledge.dependency import recommend_next

        ready = recommend_next(graph, completed)
        # Filter out current module and already-completed
        ready = [m for m in ready if m != current_module and m not in completed]
        if not ready:
            return ""

        lines = [
            "## 📋 推荐后续模块",
            "",
            "以下模块的所有依赖已满足，可在完成当前模块后开展工作：",
            "",
        ]
        for mod in ready[:5]:
            contracts = self.crystal_store.get_active_crystals(
                project_id=project_id,
                crystal_type="ContractCrystal",
                module=mod,
            )
            if contracts:
                c = contracts[0]
                content = c.get("content", {})
                if isinstance(content, str):
                    try:
                        content = _json.loads(content)
                    except (_json.JSONDecodeError, TypeError):
                        content = {}
                lines.append(f"### {mod}")
                lines.append(f"签名: `{content.get('signature', '?')}`")
                pre = content.get("preconditions", "")
                if pre:
                    lines.append(f"- Pre: {pre}")
                post = content.get("postconditions", "")
                if post:
                    lines.append(f"- Post: {post}")
            else:
                lines.append(f"### {mod}")
                lines.append("(L3 契约尚未建立)")
            lines.append("")

        return "\n".join(lines)

    def _get_compression_client(self):
        """Return (client, model) preferring lightweight model for compression summaries.

        Falls back to the main model when lightweight is unavailable.
        """
        try:
            from knowledge.lightweight import is_available, get_model as _lw_model
            from knowledge.lightweight import _get_client as _lw_client
            if is_available():
                return _lw_client(), _lw_model()
        except Exception:
            pass
        return self.client, self.model

    def _reinject_core_skill(self):
        """Re-inject the idea-to-code-sculpting skill after compression.

        Compression drops old messages including the skill content loaded via
        recall. Without re-injection the model forgets the L0-L8 workflow and
        defaults to generic behavior. This reads the skill file and inserts
        a condensed version (~4K chars) of the core model + non-negotiable
        principles directly after the base system prompt.

        Skips if the skill content is already present in recent messages (dedup).
        """
        if not state.active_project:
            return

        skill_path = os.path.join(
            os.path.dirname(__file__),
            "..", "knowledge", "raw_skills", "idea-to-code-sculpting.md",
        )
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                skill_text = f.read()
        except (FileNotFoundError, PermissionError, OSError):
            print("[SkillReinject] Skill file not found, skipping", file=sys.stderr)
            return

        # Extract core sections: the layer model (L0-L8), quick path, crystal
        # system, approval guidelines, and non-negotiable principles.
        # We skip the detailed per-phase instructions (Phase 1/2/3) since the
        # crystal context covers the current phase specifics.
        lines = skill_text.split("\n")
        sections = []
        in_section = False
        section_buf = []
        keep_sections = {
            "核心模型：逐层去噪", "快速路径选择", "Crystal Memory System",
            "审批助手行为准则", "不可违背的工作原则",
        }
        current_heading = None

        for line in lines:
            if line.startswith("## "):
                if in_section and section_buf:
                    sections.append("\n".join(section_buf))
                    section_buf = []
                heading = line[3:].strip()
                in_section = heading in keep_sections
                current_heading = heading
                if in_section:
                    section_buf.append(line)
            elif in_section:
                section_buf.append(line)

        if section_buf:
            sections.append("\n".join(section_buf))

        if not sections:
            return

        condensed = "\n\n".join(sections)

        # Cap at ~4000 chars to avoid re-filling the context we just freed
        if len(condensed) > 4200:
            condensed = condensed[:4000] + "\n\n[... skill truncated, use recall for full content ...]"

        # Dedup: skip if any recent message already contains a substantial
        # portion of this skill (checked via the "核心模型：逐层去噪" marker)
        for m in self.messages[-6:]:
            if isinstance(m.get("content"), str) and "核心模型：逐层去噪" in m["content"]:
                print("[SkillReinject] Skill already present, skipping", file=sys.stderr)
                return

        skill_msg = {
            "role": "system",
            "content": (
                "## 📋 核心开发工作流（压缩后重新注入）\n\n"
                "Context was compressed. Below is the condensed "
                "idea-to-code-sculpting workflow — follow these rules.\n\n"
                + condensed
            ),
        }
        # Insert at index 1, right after the base system prompt
        if len(self.messages) > 1:
            self.messages.insert(1, skill_msg)
        else:
            self.messages.append(skill_msg)
        print(
            f"[SkillReinject] Core skill re-injected ({len(condensed)} chars)",
            file=sys.stderr,
        )

    def _build_degradation_summary(self, dropped_messages: list[dict],
                                     dropped_count: int) -> dict | None:
        """Build a system message summarising dropped messages after compression.

        Uses LLM-driven compression with the reactive prompt when possible,
        falling back to a static crystal-based summary if the LLM call fails
        or if no crystal store is active.
        """
        if not dropped_messages:
            return None

        # Try LLM-driven compression first
        try:
            msgs_text = "\n\n".join(
                f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:2000]}"
                for m in dropped_messages[-40:]  # cap to avoid blowing the prompt
            )
            prompt = COMPRESSION_PROMPT_REACTIVE + f"\n\nConversation to compress:\n{msgs_text}"
            lw_client, lw_model = self._get_compression_client()
            resp = lw_client.chat.completions.create(
                model=lw_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                stream=False,
            )
            if hasattr(resp, "usage") and resp.usage:
                u = resp.usage
                self._turn_usage["input"] += u.prompt_tokens or 0
                self._turn_usage["output"] += u.completion_tokens or 0
                self._turn_usage["total"] += u.total_tokens or 0
            summary_text = resp.choices[0].message.content
            if summary_text and len(summary_text) > 50:
                return {"role": "system", "content": summary_text}
        except Exception as e:
            print(f"[Compression] LLM summary failed ({e}), falling back to static",
                  file=sys.stderr)

        # Fallback: static crystal-based summary
        if not self.crystal_store or not state.active_project:
            return None

        project_id = state.active_project.get("project_id", "")
        module = state.active_project.get("module", "")
        contracts = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal", module=module or None
        )
        if not contracts:
            contracts = self.crystal_store.get_active_crystals(
                project_id=project_id, crystal_type="ContractCrystal"
            )
        traces = self.crystal_store.get_active_crystals(
            project_id=project_id, crystal_type="TraceCrystal", module=module or None
        )

        if not contracts and not traces:
            return None

        lines = [
            f"[Context compressed: ~{dropped_count} earlier messages removed]",
            "",
            "Engineering decisions below remain locked. Do not redesign or contradict:",
        ]
        if module:
            lines.append(f"(Module: {module})")
        for c in contracts[:8]:
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            sig = content.get("signature", c["name"])
            lines.append(f"- [{c['module']}.{c['name']}] {sig}")

        if traces:
            lines.append("")
            lines.append("Known failure patterns — avoid these root causes:")
            for t in traces[:5]:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                root = content.get("root_cause") or ""
                if root:
                    lines.append(f"- {t['name']}: {root}")

        return {"role": "system", "content": "\n".join(lines)}

    def _compress_module_done(self, module_name: str) -> tuple[str | None, int]:
        """Generate an LLM summary after a module completes L7.

        Called when the user confirms module completion.  The summary
        condenses the L4-L7 design process into a compact record so the
        next module starts with a clean context.

        Returns (summary, max_idx) where max_idx is the highest message
        index covered by this compression, used by _proactive_cut to find
        the nearest safe cut point.
        """
        if not self.crystal_store or not state.active_project:
            return None, 0

        project_id = state.active_project.get("project_id", "")

        # Gather module-specific messages (L4-L7 for this module)
        relevant = []
        max_idx = 0
        for i, msg in enumerate(self.messages):
            meta = self.message_meta.get(i, {})
            if meta.get("module") == module_name and meta.get("chain_id"):
                relevant.append(msg)
                max_idx = max(max_idx, i)

        if len(relevant) < 3:
            return None, max_idx

        msgs_text = "\n\n".join(
            f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:2000]}"
            for m in relevant[-30:]
        )
        prompt = (COMPRESSION_PROMPT_MODULE_DONE
                  .replace("[ModuleName]", module_name)
                  + f"\n\nModule conversation:\n{msgs_text}")

        try:
            lw_client, lw_model = self._get_compression_client()
            resp = lw_client.chat.completions.create(
                model=lw_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                stream=False,
            )
            if hasattr(resp, "usage") and resp.usage:
                u = resp.usage
                self._turn_usage["input"] += u.prompt_tokens or 0
                self._turn_usage["output"] += u.completion_tokens or 0
                self._turn_usage["total"] += u.total_tokens or 0
            return resp.choices[0].message.content, max_idx
        except Exception as e:
            print(f"[Compression] Module-done summary failed: {e}", file=sys.stderr)
            return None, max_idx

    def _compress_l3_done(self) -> tuple[str | None, int]:
        """Generate an LLM summary after all L3 contracts are approved.

        Called when transitioning from L3 to per-module implementation.
        Condenses all L3 negotiation into a compact contract catalog.

        Returns (summary, max_idx) where max_idx is the highest message
        index covered by this compression, used by _proactive_cut to find
        the nearest safe cut point.
        """
        if not self.crystal_store or not state.active_project:
            return None, 0

        project_id = state.active_project.get("project_id", "")

        # Gather L3-related messages
        relevant = []
        max_idx = 0
        for i, msg in enumerate(self.messages):
            meta = self.message_meta.get(i, {})
            if meta.get("skill_layer") == "L3" and meta.get("project_id") == project_id:
                relevant.append(msg)
                max_idx = max(max_idx, i)

        if len(relevant) < 5:
            return None, max_idx

        msgs_text = "\n\n".join(
            f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:2000]}"
            for m in relevant[-40:]
        )
        prompt = COMPRESSION_PROMPT_L3_DONE + f"\n\nL3 negotiation history:\n{msgs_text}"

        try:
            lw_client, lw_model = self._get_compression_client()
            resp = lw_client.chat.completions.create(
                model=lw_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                stream=False,
            )
            if hasattr(resp, "usage") and resp.usage:
                u = resp.usage
                self._turn_usage["input"] += u.prompt_tokens or 0
                self._turn_usage["output"] += u.completion_tokens or 0
                self._turn_usage["total"] += u.total_tokens or 0
            return resp.choices[0].message.content, max_idx
        except Exception as e:
            print(f"[Compression] L3-done summary failed: {e}", file=sys.stderr)
            return None, max_idx

    def _find_nearest_safe_cut(self, target_idx: int) -> int:
        """Find the nearest index to target_idx that doesn't break any tool pair.

        Extremely relaxed compared to _find_skill_safe_cut_index — only
        protects tool_call/tool_result pairs, no chain interval protection.
        Searches bidirectionally from target_idx so the cut happens as close
        as possible to the desired location.
        """
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

        if not paired_ids:
            return target_idx

        max_offset = len(self.messages)
        for offset in range(max_offset):
            for candidate in (target_idx - offset, target_idx + offset):
                if candidate < 2 or candidate >= len(self.messages):
                    continue
                safe = True
                for cid in paired_ids:
                    call_before = call_positions[cid] < candidate
                    result_before = result_positions[cid] < candidate
                    if call_before != result_before:
                        safe = False
                        break
                if safe:
                    return candidate
        return target_idx

    def _proactive_cut(self, target_idx: int):
        """Proactive compression cut near target_idx with relaxed safety.

        Used by phase-transition and module-switch compression paths where
        the summarised message range is known. Only protects tool pairs
        (no chain interval protection) since the summary already preserves
        the essential content of the dropped messages.
        """
        if len(self.messages) <= 5:
            return

        orig_len = len(self.messages)
        self._clean_orphan_tool_messages()

        cut_idx = self._find_nearest_safe_cut(target_idx)
        if cut_idx <= 1 or cut_idx >= len(self.messages) - 1:
            cut_idx = max(2, target_idx)

        dropped = cut_idx - 1
        print(
            f"[Memory] Proactive cut: target={target_idx}, actual={cut_idx}, "
            f"dropping {dropped} of {orig_len} messages",
            file=sys.stderr,
        )

        dropped_msgs = self.messages[1:cut_idx]
        summary = self._build_degradation_summary(dropped_msgs, dropped)

        self.messages = [self.messages[0]] + self.messages[cut_idx:]
        self._rebuild_meta_after_cut(cut_idx)

        if summary:
            self.messages.insert(1, summary)
            shifted_meta = {}
            for idx, meta in self.message_meta.items():
                if idx >= 1:
                    shifted_meta[idx + 1] = meta
                else:
                    shifted_meta[idx] = meta
            self.message_meta = shifted_meta

        # Re-inject core skill after proactive compression
        self._reinject_core_skill()

        self._clean_orphan_tool_messages()

        print(
            f"[Memory] Proactive result: {orig_len}→{len(self.messages)} "
            f"(dropped {dropped})",
            file=sys.stderr,
        )

    def memory(self):
        """Hierarchical memory compression with cooldown and skill protection.

        Flow:
        0. If cooldown is active, skip to force-cut (deeper, one-shot)
        1. Try skill-safe cut (protects approval chains + tool pairs)
        2. If no safe point, archive completed modules to free space, retry
        3. Fallback: original tool-pair-only protection
        4. Last resort: force-cut at midpoint with warning

        After compression, re-injects the core idea-to-code-sculpting skill
        so the model doesn't forget the workflow after context is dropped.

        Called from two sites:
        - Reactively: when the API returns a context-length error (preferred)
        - Proactively: when a module switch is detected (module_switch_notice)
        """
        self._clean_orphan_tool_messages()

        if len(self.messages) <= 5:
            return

        orig_len = len(self.messages)
        forced = False

        # Cooldown: if we already compressed recently, skip conservative steps
        # and force a deeper cut to avoid rapid back-to-back compressions.
        if self._compression_cooldown > 0:
            self._compression_cooldown -= 1
            cut_idx = max(2, len(self.messages) // 3)  # Cut deeper on re-trigger
            forced = True
            print(
                f"[Memory] Cooldown active — force-cut at {cut_idx} "
                f"({orig_len} messages, dropping ~{cut_idx - 1})",
                file=sys.stderr,
            )
        else:
            print(
                f"[Memory] Attempting compression ({orig_len} messages)...",
                file=sys.stderr,
            )

            # Step 1: Try skill-safe cut
            cut_idx = self._find_skill_safe_cut_index()
            if cut_idx is not None:
                print(
                    f"[Memory] Step 1 (skill-safe cut): cut_idx={cut_idx}, "
                    f"dropping {cut_idx - 1} of {orig_len} messages",
                    file=sys.stderr,
                )

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
                print(
                    "[Memory] Step 2 failed, falling back to Step 3 (tool-pair protection)",
                    file=sys.stderr,
                )
                cut_idx = self._find_safe_cut_index()

            # Step 4: Last resort
            if cut_idx is None or cut_idx >= len(self.messages) - 1 or cut_idx <= 1:
                print(
                    "[Memory] Step 3 failed, using Step 4 (force-cut at midpoint)",
                    file=sys.stderr,
                )
                cut_idx = len(self.messages) // 2 + 1
                forced = True

        dropped = cut_idx - 1

        # Build degradation summary before dropping messages (LLM-driven with fallback)
        dropped_msgs = self.messages[1:cut_idx]
        summary = self._build_degradation_summary(dropped_msgs, dropped)

        self.messages = [self.messages[0]] + self.messages[cut_idx:]

        # Rebuild metadata after cut
        self._rebuild_meta_after_cut(cut_idx)

        # Inject crystal summary after the base system prompt
        if summary:
            self.messages.insert(1, summary)
            # Shift metadata indices >= 1 by +1; system prompt at 0 stays
            shifted_meta = {}
            for idx, meta in self.message_meta.items():
                if idx >= 1:
                    shifted_meta[idx + 1] = meta
                else:
                    shifted_meta[idx] = meta
            self.message_meta = shifted_meta

        # Re-inject core skill — compression drops loaded skill content
        self._reinject_core_skill()

        # Set cooldown: prevent another compression this turn
        self._compression_cooldown = 1

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

    def full_compress(self) -> dict:
        """Full compression: replace all non-system messages with one LLM summary.

        Keeps messages[0] (base system prompt), feeds everything else to an LLM
        for comprehensive summarization, then appends the summary as a single
        system message. After that, re-injects the core skill.

        This is the most aggressive mode — use when the context is bloated and
        modular/safe modes can't free enough space.

        Returns:
            {"archived_modules": [], "cut_messages": int, "remaining_messages": int}
        """
        if len(self.messages) <= 5:
            return {"archived_modules": [], "cut_messages": 0, "remaining_messages": len(self.messages)}

        orig_len = len(self.messages)
        self._clean_orphan_tool_messages()

        # Keep system prompt, summarize everything else
        system_prompt = self.messages[0]
        to_summarize = self.messages[1:]

        # Build summary text from messages
        msgs_text = []
        for i, msg in enumerate(to_summarize[-80:]):  # last 80 messages max
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:1500]
            if msg.get("tool_calls"):
                tool_names = [tc.get("function", {}).get("name", "?")
                              for tc in msg["tool_calls"]]
                content = f"[Tool calls: {', '.join(tool_names)}] " + content
            msgs_text.append(f"[{role}] {content}")

        combined = "\n\n---\n\n".join(msgs_text)
        if len(combined) > 30000:
            combined = combined[-30000:]

        summary = self._build_degradation_summary(
            to_summarize, len(to_summarize)
        )

        # Rebuild messages: system prompt + summary + (if compression summary isn't a dict, wrap it)
        new_messages = [system_prompt]
        if summary and isinstance(summary, dict) and summary.get("content"):
            new_messages.append(summary)
        elif summary and isinstance(summary, str):
            new_messages.append({"role": "system", "content": summary})
        else:
            # LLM summary failed — fall back to a static crystal-based summary
            static = self._static_full_summary()
            if static:
                new_messages.append({"role": "system", "content": static})

        self.messages = new_messages
        self.message_meta = {0: self.message_meta.get(0, {})}
        if len(new_messages) > 1:
            self.message_meta[1] = {"skill_layer": "L8", "is_approval": False}

        self._reinject_core_skill()

        after = len(self.messages)
        cut = orig_len - after
        print(
            f"[FullCompress] {orig_len} → {after} messages "
            f"(dropped {cut}, full summarization)",
            file=sys.stderr,
        )
        return {
            "archived_modules": [],
            "cut_messages": cut,
            "remaining_messages": after,
        }

    def _static_full_summary(self) -> str | None:
        """Build a static full-compression summary from CrystalStore data.

        Used when the LLM summarization call fails during full_compress().
        """
        if not self.crystal_store:
            return None

        parts = ["## 上下文全量压缩\n"]
        parts.append("以下是从 CrystalStore 恢复的项目状态摘要：\n")

        # Active project overview
        all_crystals = self.crystal_store.get_active_crystals()
        if all_crystals:
            # Group by module
            modules: dict[str, dict] = {}
            for c in all_crystals:
                mod = c.get("module", "__unknown__")
                if mod not in modules:
                    modules[mod] = {"types": set(), "count": 0}
                modules[mod]["types"].add(c.get("crystal_type", "?"))
                modules[mod]["count"] += 1

            for mod, info in sorted(modules.items()):
                types_str = ", ".join(sorted(info["types"]))
                parts.append(f"- **{mod}**: {info['count']} crystals ({types_str})")

        # Key contracts
        contracts = self.crystal_store.get_active_crystals(crystal_type="ContractCrystal")
        if contracts:
            parts.append("\n### 关键契约")
            for c in contracts[:5]:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                sig = content.get("signature", c.get("name", "?"))
                mod = c.get("module", "?")
                parts.append(f"- [{mod}] `{str(sig)[:200]}`")

        # Active traces
        traces = self.crystal_store.get_active_crystals(crystal_type="TraceCrystal")
        if traces:
            parts.append("\n### 已知问题")
            for t in traces[:5]:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                parts.append(f"- {t.get('name', '?')}: {content.get('symptom', '?')[:120]}")

        return "\n".join(parts)

    def modular_compress(self) -> dict:
        """Module-level compression: archive every completed module in-place.

        Unlike memory() which tries to find a single global cut point, this method
        discovers completed modules from two sources:
          1. message_meta chain_id entries (format: {project}/{module}/L3-L7)
          2. CrystalStore ImplCrystal records (fallback when chain_id not tracked)

        Each completed module chain is replaced with a crystal-based summary message,
        then a lightweight final trim is applied.

        Returns:
            {"archived_modules": [...], "cut_messages": int, "remaining_messages": int}
        """
        if len(self.messages) <= 5:
            return {"archived_modules": [], "cut_messages": 0, "remaining_messages": len(self.messages)}

        self._clean_orphan_tool_messages()
        before = len(self.messages)

        # ── Step 1: Discover completed modules ──
        # Source A: chain_id entries in message_meta
        chain_modules: dict[str, str] = {}  # module_name -> project_id
        for idx_str, meta in self.message_meta.items():
            cid = meta.get("chain_id", "")
            if not cid or not cid.endswith("/L3-L7"):
                continue
            parts = cid.split("/")
            if len(parts) >= 3:
                p_id = parts[0]
                mod = "/".join(parts[1:-1])
                if mod not in chain_modules:
                    chain_modules[mod] = p_id

        # Source B: CrystalStore ImplCrystal — catches modules whose chain_id
        # was never recorded in message_meta (e.g. early-phase projects)
        crystal_modules: dict[str, str] = {}  # module_name -> project_id
        if self.crystal_store:
            all_impls = self.crystal_store.get_active_crystals(
                crystal_type="ImplCrystal"
            )
            for c in all_impls:
                mod = c.get("module", "")
                pid = c.get("project_id", "")
                if mod and pid and mod not in chain_modules and mod not in crystal_modules:
                    crystal_modules[mod] = pid

        # Merge: chain_id entries take priority (they have precise message ranges)
        all_targets = dict(chain_modules)
        for mod, pid in crystal_modules.items():
            if mod not in all_targets:
                all_targets[mod] = pid

        if not all_targets:
            return {"archived_modules": [], "cut_messages": 0, "remaining_messages": before}

        print(
            f"[ModularCompress] Found {len(all_targets)} module(s) to check "
            f"({len(chain_modules)} from chain_id, {len(crystal_modules)} from CrystalStore)",
            file=sys.stderr,
        )

        # ── Step 2: Archive each module ──
        archived = []
        for module_name, project_id in all_targets.items():
            if self._archive_module(project_id, module_name):
                archived.append({"project_id": project_id, "module": module_name})
                continue

            # Fallback: if chain-based archive fails but ImplCrystal exists,
            # try scanning by module metadata range
            if module_name in crystal_modules and module_name not in chain_modules:
                if self._archive_module_by_meta_range(project_id, module_name):
                    archived.append({"project_id": project_id, "module": module_name})

        # ── Step 3: Final lightweight trim ──
        self._compact_messages()

        after = len(self.messages)
        cut_messages = before - after

        if after > 50:
            print(
                f"[ModularCompress] {after} messages remain after archiving, "
                f"running memory() for final trim",
                file=sys.stderr,
            )
            self.memory()
            after = len(self.messages)
            cut_messages = before - after

        print(
            f"[ModularCompress] {before} → {after} messages "
            f"({len(archived)} modules archived, {cut_messages} total removed)",
            file=sys.stderr,
        )

        return {
            "archived_modules": archived,
            "cut_messages": cut_messages,
            "remaining_messages": after,
        }

    def _archive_module_by_meta_range(self, project_id: str, module_name: str) -> bool:
        """Archive a module by finding its message range from module metadata.

        Fallback for _archive_module() when no chain_id exists in message_meta.
        Scans message_meta for all indices tagged with this (project_id, module),
        then replaces the range with a crystal-based summary.
        """
        if not self.message_meta:
            return False

        indices = sorted(
            int(idx) for idx, meta in self.message_meta.items()
            if meta.get("project_id") == project_id and meta.get("module") == module_name
        )
        if len(indices) < 3:
            return False

        chain_start = indices[0]
        chain_end = indices[-1]

        summary = self._build_module_summary(project_id, module_name)
        if not summary:
            return False

        summary_msg = {"role": "assistant", "content": summary}

        self.messages = (
            self.messages[:chain_start]
            + [summary_msg]
            + self.messages[chain_end + 1:]
        )

        # Rebuild metadata
        new_meta = {}
        replaced_count = chain_end - chain_start + 1
        offset = replaced_count - 1
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
            f"[Archive] Module {module_name}: meta-range compressed "
            f"({replaced_count} messages → 1, no chain_id)",
            file=sys.stderr,
        )
        return True

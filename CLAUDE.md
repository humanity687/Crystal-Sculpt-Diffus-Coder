# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# First-time setup (creates venv, installs deps, copies config)
./init.sh              # macOS/Linux
./init.bat             # Windows

# Run the app
source .venv/bin/activate && python3 -m src.app   # macOS/Linux
run.bat                                            # Windows
```

No test suite or linter is configured for this project.

## Architecture

Crystal-Sculpt-Diffus-Coder is a Flask web app that provides a chat interface for an AI agent with tool-calling capabilities. The app runs on `127.0.0.1:5000` and exposes itself via Cloudflare Tunnel for remote access.

### Core flow

1. **`src/app.py`** — Entry point. Creates the Flask app, registers blueprints, initializes two `BaseAgent` instances (`chat_agent` and `tasks_agent`), and starts the Cloudflare tunnel in a background thread.
2. **`src/agent.py`** — The `BaseAgent` class. Wraps an OpenAI-compatible client, manages the message history, and implements a streaming generator (`input()`) that yields text chunks and tool-call events. Uses a two-level loop: an outer `while restart` loop (re-builds context on state changes) wrapping an inner tool-calling loop (call model → if tool_calls, execute tools → send results back → repeat until no more tool calls). `_build_context()` is re-invoked on every restart iteration to pick up fresh crystal/phase state.
3. **`src/state.py`** — Shared mutable state: the two agent instances, a `pending_confirmations` dict keyed by `confirm_id`, the `active_project` dict (set by `set_project` tool, read by agent context methods), the shared `CrystalStore` instance, and `load_config()`/`save_config()` helpers that read/write `config.json`.

### Request lifecycle (chat)

`POST /chat` (SSE stream) in `src/routes/chat.py`:
- Calls `state.chat_agent.input(user_message)` to get the generator
- Iterates the generator, wrapping each yielded item into `data:` SSE events
- Text chunks → `{"type": "content", "text": ...}`
- Tool calls → `{"type": "tool_call", ...}`
- Tool results → `{"type": "tool_result", ...}`
- **Confirmation required** (for `command` tools), **write proposal** (for `write` tools), and **approval required** (for `request_approval`): the route pauses the generator, stores the generator + a `queue.Queue` in `state.pending_confirmations`, and blocks until the frontend calls `/api/confirm_tool` with the decision or final content. The result is fed back into the generator via `agent_gen.send()`. `request_approval` rejection supports `rejection_reason` for guided revision; `write` tool rejection also supports user feedback via a textarea.
- **project_state** events (from `set_project`) are forwarded to the frontend for the status bar.
- **context_restart** events signal the frontend to create a new assistant message bubble when the outer loop restarts mid-stream.

### Tool system

All tools are invoked through a single `tools` function registered as `tool_functions["tools"]` and declared as the only tool in `tools_metadata`. The model calls `tools(tool_name="xxx", arguments={...})`, and the loader dispatches to the appropriate handler.

- **Built-in tools** live in `knowledge/tools/<name>/`. Each tool is a directory with a `tool.py` that exports `execute(**kwargs) -> str` and a `README.md` that becomes part of the knowledge base. Loaded by `knowledge/loader.py` → `load_builtin_tools()`. Current tools: `read`, `write`, `command`, `search`, `time`, `add_skill`, `set_project`, `crystallize`, `dependency`, `recall`, `request_approval`, `archive_project`, `review_approval`.
- **`set_project`** — Activates the crystal-aware engineering context. Takes `project_id`, `phase` (L0-L8, L3.1), and optional `module`. Writes `state.active_project`, which enables phase-aware crystal context injection in subsequent turns.
- **`crystallize`** — Crystal management with two sub-commands:
  - `store` (default): Stores a thought crystal into CrystalStore. Takes `crystal_type`, `module`, `name`, and `content` (JSON string). Requires an active project.
  - `find`: Search for existing crystals by `crystal_type`, `module`, `layer` (structured filter), or `query` (vector similarity search across ContractCrystal signatures and TraceCrystal symptoms).
- **`dependency`** — Agent-driven dependency graph management. Four sub-commands via `command` parameter:
  - `define` (primary): Agent declares `modules` + `dependencies` directly after L2 approval. Builds graph, detects cycles, stores `DependencyGraphCrystal`.
  - `analyze` (fallback): Reads ModMap crystals and reconciles graph from stored data.
  - `recommend`: Given `completed` module list, returns which modules are ready for L3.
  - `impact`: BFS downstream traversal — given a changed module, lists all affected downstream modules. Used at L3.1 renegotiation and L8 bug backtracking.
  All sub-commands return formatted Markdown reports with Mermaid diagrams. `recommend` and `impact` read from the stored `DependencyGraphCrystal`.
- **MCP tools** are loaded from `config.json` → `mcp_servers[]`. Each server is started as a subprocess via `MCPStdioClient` (`knowledge/mcps.py`), which speaks JSON-RPC 2.0 over stdio. MCP tools are registered with the prefix `server_name/tool_name`.

### Knowledge base (Two-Level Summary Memory)

The project uses a two-level summary memory system that replaces the old "full-text RAG" approach:

- **Level 1 — Summary index**: Only structured summaries are embedded and indexed in the vector DB. The `search()` function returns `list[dict]` with `memory_id`, `text`, `type`, `score`, `title`, `icon` for each result. Summaries are formatted in context with `memory_id` references so the model can call `recall(memory_id="...")` to fetch full details.
- **Level 2 — Recall tool**: `knowledge/tools/recall/tool.py` — `execute(memory_id, query?, lines?)` fetches original full-text content from disk by its `memory_id`. Only accesses files under `knowledge/`. Default return limit: 8000 chars.

**Summary types and weights:**
| Type | Weight | Description |
|------|--------|-------------|
| `conversation_summary` | 0.3 | Conversation turn summary (LLM-generated or extractive) |
| `tool_summary` | 1.0 | Tool documentation summary (from README or summary.json) |
| `skill_summary` | 0.8 | Skill documentation summary (from skill .md or summary.json) |
| `hyw` (legacy) | 1.0 | Other documentation — full-text indexed |

**memory_id format**: `{type_prefix}:{identifier}`
- Conversations: `conv:20260115-143022-a1b2c3`
- Tools: `tool:read`
- Skills: `skill:idea-to-code-sculpting`

**Key files:**
- `knowledge/summarizer.py` — Summary generation (LLM probe or extractive fallback)
- `knowledge/vector.py` — `add_summary(memory_id, text, doc_type, source, summary_json)` stores summary in vector DB; `incremental_update()` auto-extracts summaries from tool/skill files
- `knowledge/search.py` — `search(query, k)` returns structured dicts; `search_texts(query, k)` is the backward-compatible wrapper returning `list[str]`
- `knowledge/memory.py` — `add_conversation(user_msg, ai_msg)` writes backup to `knowledge/memories/`, generates summary (extractive), stores in vector DB; `add_conversation_with_llm(client, model)` does the same with an LLM-generated summary in a background thread

**Legacy backward compatibility**: Old `vectors` table entries without `memory_id` still work — they're returned by `search()` with `memory_id=None` and formatted without the recall reference line. `search_texts()` provides the old `list[str]` interface for callers that haven't been updated.

Document types affect retrieval weight: `tool` = 1.0, `skill` = 0.8, `conversation` = 0.2.

### Crystal memory system (engineering memory)

`knowledge/crystals.py` — `CrystalStore` class, a SQLite-backed engineering memory system for the idea-to-code-sculpting workflow. Stores structured "thought crystals" extracted from each skill layer (L0-L8).

**Seven crystal types** map to skill layers:
- L1 → `ArchCrystal` (architecture_summary, tech_stack, core_flow)
- L2 → `ModMap` (modules[], dependencies{})
- L3 → `ContractCrystal` (signature, preconditions, postconditions, constraints) — **central type**, anchors L3→L4→L6→L7→L8 chain
- L4 → `LogicCrystal` (algorithm_steps, boundary_handling)
- L6 → `SkeletonCrystal` (code_skeleton, language)
- L7 → `ImplCrystal` (code, tests, language)
- L8 → `TraceCrystal` (symptom, root_cause, fix)

**Key behaviors:**
- **Vitality scoring**: Each successful reuse +1; retrieval sorted by vitality descending
- **Phase-aware context injection**: `working_context(project_id, phase, module)` returns formatted text matching the current skill phase — L0-L2 sees all contracts, L3 sees similar contracts + related traces, L4 sees current contract + logic crystals, L6-L7 sees contract + failure traces, L8 sees all traces + full contract chain
- **Trace chain**: `get_full_trace(crystal_id)` follows `parent_ids` with cycle detection
- **Vector similarity**: `find_similar_contracts()` and `find_related_traces()` use SentenceTransformer embeddings with vitality bonus (min(v*0.05, 0.3))
- **Thread safety**: Write operations use `threading.Lock`; connections use `check_same_thread=False`
- Database: `crystals.db` (separate from RAG vector DB)

**Eighth crystal type — DependencyGraphCrystal** (stored by `dependency define`/`analyze`, not via `crystallize`):
- Stored at L2 after module decomposition approval
- Content: `graph` (adjacency list), `topological_order`, `cycles`, `module_status`, `mermaid`
- Read by `dependency recommend` (before L3) and `dependency impact` (L3.1 / L8)
- Replaced on re-define — old DependencyGraphCrystal deprecated, new one created

### Dependency graph (engineering memory)

`knowledge/dependency.py` — Pure Python graph algorithms, zero external dependencies:
- `build_graph(modmap_crystals)` → adjacency list from ModMap crystals
- `detect_cycles(graph)` → DFS with color marking (white/gray/black), returns cycle lists
- `topological_sort(graph)` → Kahn's algorithm, returns dependency-first ordering
- `compute_impact(graph, module)` → BFS downstream traversal, returns all affected modules
- `recommend_next(graph, completed)` → modules with all deps satisfied
- `generate_mermaid(graph, cycles?)` → Mermaid `graph TD` with cycle edges marked red dashed

`knowledge/tools/dependency/tool.py` — Built-in tool wrapping the algorithms. `define` is the primary entry point (agent declares modules+dependencies directly). `analyze` is the fallback (reads ModMap crystals). Both store a `DependencyGraphCrystal`. `recommend` and `impact` query the stored crystal.

`knowledge/crystal_observer.py` — `CrystalObserver` class. Auto-extracts crystals from conversation turns using a lightweight LLM probe (temperature=0.1, stream=False). Only activates when `state.active_project` is set. Called from `BaseAgent.input()` at turn completion. Failures are silently caught — never blocks the chat flow.

**Activation flow:**
1. Agent calls `set_project(project_id, phase, module)` → writes `state.active_project`
2. `_build_context()` and `_get_relevant_knowledge()` read `state.active_project` → phase-aware crystal injection
3. Agent calls `crystallize(crystal_type, module, name, content)` after each layer approval → stores crystal
4. At L2 approval, agent calls `dependency(command="define", ...)` → stores `DependencyGraphCrystal`
5. Before L3, agent calls `dependency(command="recommend", ...)` → confirms dependencies ready
6. At L3.1 / L8, agent calls `dependency(command="impact", ...)` → traces downstream affected modules
7. `CrystalObserver.analyze_turn()` runs after each turn completion as a supplementary extraction mechanism

### Authentication

`src/auth.py` — ECIES (ECDH + HKDF + AES-256-GCM) for password transmission, NIST P-256 ECC keys, bcrypt for password hashing, JWT (HS256, 1-hour expiry) for session tokens. Passwords are set on first visit via `/api/setup`.

### Scheduled tasks

`src/scheduler.py` — A daemon thread polls `tasks.json` every 10 seconds, matches `HH:MM` times, and spawns threads that call `state.tasks_agent.input()`. Progress is broadcast to the frontend via SSE (`/events` endpoint). Tasks can be cancelled via `/cancel_task/<task_id>`.

### Key behaviors

- **Loop restart mechanism**: `input()` wraps the tool-calling loop in a `while restart` outer loop. When `set_project` changes `state.active_project` or `request_approval` is approved, `restart = True` triggers a new iteration that re-calls `_build_context()` and `_get_relevant_knowledge()` with fresh phase/crystal state. A `first_entry` flag prevents duplicate user message appending. On restart, a `context_restart` SSE event is sent so the frontend creates a new assistant bubble. Max 3 restarts per request.
- **Context compression (v2 — hierarchical safety)**: When the API returns a context-length error, `BaseAgent.memory()` uses a multi-tier strategy:
  1. **Skill-safe cut** (`_find_skill_safe_cut_index`): Scans `message_meta` to build atomic intervals from approval chains (L3→L7, tracked via `chain_id`) and tool_call/tool_result pairs. The cut point must not fall inside any interval — an entire chain is kept or dropped as a unit.
  2. **Archive to free space**: If no safe cut exists, `_archive_completed_modules()` replaces completed module chains with summary messages, then retries.
  3. **Original tool-pair fallback** (`_find_safe_cut_index`): Legacy protection that only prevents breaking (tool_call, tool_result) pairs.
  4. **Force-cut with warning**: Last resort — cuts at midpoint and injects a warning message.
  After compression, `_rebuild_meta_after_cut()` realigns metadata indices. `_build_degradation_summary()` now uses LLM-driven compression via `COMPRESSION_PROMPT_REACTIVE` (fallback to static crystal summary). Three compression prompt constants cover reactive (context overflow), L3-done (all contracts approved), and module-done (L7 complete) scenarios. Compression notification only shown when `cut_count > 0`.
- **Message metadata**: Every appended message is auto-tagged via `_build_meta()` with `skill_layer`, `module`, `project_id`, `is_approval` (detected from approval conclusion patterns like "符合你的预期吗？"), and `chain_id` (generated on L3 approval, inherited by same-module messages). Metadata persists in `messages.json` under `_meta` key. Old-format `messages.json` (plain list) loads with empty metadata — degrades gracefully to tool-pair-only compression.
- **Module archiving**: When `crystallize(ImplCrystal)` is called, the module is marked `pending_completion`. On the next user turn, if the reply contains a confirmation pattern ("通过", "归档", "ok" etc.), `_archive_module()` replaces the entire L3→L7 chain with a summary message built from CrystalStore (contract signature + algorithm steps + implementation file). Modules can opt out via `module_archive_policy[module_name] = False`.
- **Write tool rejection feedback**: The `CodeReviewPanel` rejection flow now includes a textarea for user feedback (mirroring `ApprovalPanel`). The `rejection_reason` is fed back to the model as `"User feedback: {reason}"`, enabling targeted revision instead of guessing why the proposal was rejected.
- **Orphan cleanup**: `_clean_orphan_tool_messages()` removes tool messages without a matching assistant tool_call and vice versa, called on generator exit and before compression.
- **Message persistence**: Full message history is saved to `messages.json` on every complete assistant response and on exit.
- The `write` tool no longer writes files directly — it returns the AI's proposed content, which flows through the review panel flow where the user can edit before the frontend writes to disk.

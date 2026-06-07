# Crystal-Sculpt-Diffus-Coder

**English** | [中文](docs/zh/README.md)

An AI agent framework with a Flask web interface that lets AI read files, execute commands, search the web, and collaborate on engineering projects. Remote access via Cloudflare Tunnel — no public IP needed.

---

## Features

- **Chat with tool-calling AI** — model calls tools autonomously: read/write files, run commands, search the web
- **Code Review Panel** — AI proposes file changes as diffs; you review, edit, and approve before anything touches disk
- **Engineering crystal memory** — L0-L8 workflow with structured artifacts (contracts, logic, traces) stored in SQLite, retrieved via vector similarity
- **Dependency graph management** — AI defines module dependencies at L2; impact analysis and topological ordering for implementation sequencing
- **MCP protocol** — integrate any stdio MCP server; tools auto-discovered as `server_name/tool_name`
- **Two-level summary memory** — summaries indexed for retrieval, full text available via `recall` tool
- **Scheduled tasks** — background daemon runs commands at HH:MM times
- **Secure auth** — ECIES (ECDH + AES-256-GCM) + bcrypt + JWT (1h expiry)
- **Cross-platform** — Windows / Linux / macOS

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/humanity687/Crystal-Sculpt-Diffus-Coder.git
cd Crystal-Sculpt-Diffus-Coder

# 2. Setup (creates venv, installs deps)
./init.sh       # macOS/Linux
init.bat        # Windows

# 3. Edit config.json (api_key, base_url, model)

# 4. Run
./run.sh        # macOS/Linux
run.bat         # Windows
```

After startup, the terminal shows a public Cloudflare Tunnel URL. Open it on any device — first visit guides you through password setup.

---

## Configuration (`config.json`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `api_key` | string | — | API key (required). For Ollama, any value works. |
| `base_url` | string | — | API base URL. Ollama: `http://localhost:11434/v1` |
| `model` | string | — | Model name. Recommended: `glm-4.7-flash` |
| `temperature` | float | `0.8` | Randomness 0-2. Lower = deterministic. |
| `thinking` | bool | `false` | Deep thinking (GLM models only). |
| `knowledge_k` | int | `5` | Knowledge snippets per retrieval. |
| `language` | string | `"en"` | UI language (`en` / `zh`). |
| `mcp_servers` | list | `[]` | MCP server configs. Each: `{name, command, args}`. |
| `memory_weights` | object | — | Per-type retrieval weight overrides. |
| `tools.ett` | object | — | Multimodal model config (requires GLM vision model). |

---

## Built-in Tools

| Tool | Purpose |
|------|---------|
| `read` | Read files, directories, images, documents |
| `write` | Propose file changes — diff review before writing (overwrite, edit, replace, insert modes) |
| `command` | Execute shell commands (whitelist-based; deletion blocked) |
| `search` | Web search via DuckDuckGo (free, no API key) |
| `time` | Current date/time |
| `recall` | Fetch full-text content by memory_id from the knowledge base |
| `add_skill` | Save reusable skill .md files into the vector DB |
| `set_project` | Activate phase-aware engineering context (project_id, phase, module) |
| `crystallize` | Store/find thought crystals (ContractCrystal, LogicCrystal, TraceCrystal, etc.) |
| `dependency` | Manage module dependency graph (define, recommend, impact analysis) |
| `request_approval` | Present Lx content for user approval with snapshot recording |

All tools are called through a single `tools` function. MCP tools use `server_name/tool_name` format.

---

## Knowledge Base

Two-level summary memory: summaries are embedded in the vector DB; full content lives on disk and is retrieved via the `recall` tool.

| Type | Weight | Description |
|------|--------|-------------|
| `tool_summary` | 1.0 | Tool documentation |
| `skill_summary` | 0.8 | Skill documentation |
| `experience_crystal` | 0.6 | Cross-project engineering experience |
| `conversation_summary` | 0.3 | Conversation turn summary |

Search uses hybrid retrieval: vector similarity + FTS5 keyword search with RRF fusion.

---

## Engineering Crystal System (L0-L8)

SQLite-backed structured memory for the idea-to-code-sculpting workflow:

| Layer | Crystal Type | Content |
|-------|-------------|---------|
| L1 | ArchCrystal | architecture_summary, tech_stack, core_flow |
| L2 | ModMap | modules[], dependencies{} |
| L3 | ContractCrystal | signature, preconditions, postconditions, constraints |
| L4 | LogicCrystal | algorithm_steps, boundary_handling |
| L6 | SkeletonCrystal | code_skeleton, language |
| L7 | ImplCrystal | code, tests, language |
| L8 | TraceCrystal | symptom, root_cause, fix |

Plus `DependencyGraphCrystal` for module dependency tracking (define → recommend → impact).

Key behaviors: vitality scoring, phase-aware context injection, vector similarity search, trace chain traversal.

---

## Security

- ECIES (ECDH + HKDF + AES-256-GCM) for password transmission
- bcrypt password hashing, JWT session tokens (1h expiry, memory-only storage)
- `command` tool: whitelist-based allowlist, deletion commands blocked, safe commands auto-execute, dangerous commands require confirmation
- `write` tool: never writes directly — always goes through Code Review Panel

---

## Disclaimer

Cloudflare Tunnel remote access is provided as a technical convenience. Users assume all risks associated with network exposure, device loss, password leakage, or third-party attacks. Use strong passwords, enable remote access only on trusted networks, and understand that any networked service may have unknown security vulnerabilities.

The project authors and contributors accept no liability for any direct or indirect losses arising from the use of this software. By using this software, you indicate that you have read and agreed to this disclaimer.

---

## License

[AGPL v3](COPYING)

---


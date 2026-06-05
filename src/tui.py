#!/usr/bin/env python3
# This file is part of BaseAgent.
# BaseAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# BaseAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with BaseAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
BaseAgent TUI — Mock LLM Debug Console.

Replaces agent.client.chat.completions.create with a human-in-the-loop
interface. ALL messages sent to the LLM are displayed in the terminal
with role-based coloring and source detection (base/phase/crystal/
knowledge/rollback/switch). The user responds as the agent:

  Plain text  → returned as model text response
  /tool args  → returned as tool_calls, agent executes tool, loop continues

Start:  python3 -m src.tui
Config: set "debug": true in config.json (warns if false)
"""

import sys
import os
import json
import re
import uuid
import shlex
import threading
import time
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

# ── Globals ──────────────────────────────────────────────────────────────
console = Console()
_turn = 0
_last_context = []        # messages from the most recent API call
_agent_instance = None     # BaseAgent handle
_expanded = False          # toggle full message display


# ═══════════════════════════════════════════════════════════════════════════
# Mock OpenAI streaming chunk classes
# ═══════════════════════════════════════════════════════════════════════════

class ToolCallFunction:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class ToolCallDelta:
    def __init__(self, index=0, id=None, function_name="", function_args=""):
        self.index = index
        self.id = id
        self.function = ToolCallFunction(function_name, function_args)


class MockChoice:
    __slots__ = ("content", "tool_calls", "finish_reason", "delta")

    def __init__(self, content=None, tool_calls=None, finish_reason=None):
        self.delta = self
        self.content = content
        self.tool_calls = tool_calls
        self.finish_reason = finish_reason


class MockChunk:
    __slots__ = ("choices",)

    def __init__(self, content=None, tool_calls=None, finish_reason=None):
        self.choices = [MockChoice(content, tool_calls, finish_reason)]


# ═══════════════════════════════════════════════════════════════════════════
# Tool-call argument parser
# ═══════════════════════════════════════════════════════════════════════════

def _parse_tool_args(raw: str) -> dict:
    """Parse '/tool_name k1="v1", k2={"j":1}' into a dict.

    Uses shlex to split, then matches key=value pairs.
    Values are eval'd for JSON/dict/list support, falling back to str.
    """
    if not raw:
        return {}
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.replace(",", " ").split()

    result = {}
    current_key = None
    current_val = ""

    for part in parts:
        # Remove trailing comma
        part = part.rstrip(",")
        if "=" in part:
            # Flush previous
            if current_key:
                result[current_key] = _coerce_value(current_val.strip())
            key, val = part.split("=", 1)
            current_key = key.strip()
            current_val = val
        else:
            current_val += " " + part

    if current_key:
        result[current_key] = _coerce_value(current_val.strip())

    return result


def _coerce_value(val: str):
    """Try to parse as JSON/number/bool, fallback to string."""
    if not val:
        return ""
    # Already quoted string
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    # Try JSON (dict/list)
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try number
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    # Boolean
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    # null
    if val.lower() == "null" or val.lower() == "none":
        return None
    return val


# ═══════════════════════════════════════════════════════════════════════════
# Context display
# ═══════════════════════════════════════════════════════════════════════════

# Color registry: (role_color, border_style)
ROLE_STYLES = {
    "system:base":     ("dim cyan", "dim cyan"),
    "system:phase":    ("yellow", "yellow"),
    "system:crystal":  ("green", "green"),
    "system:knowledge":("magenta", "magenta"),
    "system:rollback": ("red", "red"),
    "system:switch":   ("blue", "blue"),
    "system:other":    ("dim white", "dim white"),
    "user":            ("bright_white", "bright_white"),
    "assistant":       ("bright_cyan", "bright_cyan"),
    "tool":            ("bright_blue", "bright_blue"),
}

SOURCE_MARKERS = [
    ("Locked Engineering", "crystal"),
    ("Dependency Contracts", "crystal"),
    ("Current Contract", "crystal"),
    ("Own Module L3 Contract", "crystal"),
    ("Module L3 Contract", "crystal"),
    ("Dependency Contracts (auto-injected", "crystal"),
    ("## 不可违背", "phase"),
    ("## L", "phase"),   # L0, L1, ... headers
    ("📚 相关记忆", "knowledge"),
    ("⚠️ 相位回退", "rollback"),
    ("🔄 模块切换", "switch"),
]


def _detect_source(msg: dict) -> str:
    """Identify the source of a system message by content patterns."""
    content = msg.get("content", "") or ""
    role = msg.get("role", "system")

    if role != "system":
        return role

    # Check against known phase guidance (state.phase_guidance)
    from src import state
    if state.phase_guidance and content == state.phase_guidance:
        return "system:phase"

    # Check against base system prompt
    global _agent_instance
    if _agent_instance and content == _agent_instance.base_system_prompt:
        return "system:base"

    for marker, source in SOURCE_MARKERS:
        if marker in content:
            return f"system:{source}"

    return "system:other"


def _truncate(text: str, max_len: int = 100) -> str:
    """Truncate long text for display."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... [truncated, {len(text)} chars total, /expand to see full]"


# Messages whose source is a system-context category — always visible.
_CONTEXT_SOURCES = frozenset({
    "system:base", "system:phase", "system:crystal",
    "system:knowledge", "system:rollback", "system:switch",
})

# How many trailing conversation messages to show before collapsing older ones.
_CONVERSATION_TAIL = 8


def _is_context_msg(source: str) -> bool:
    """Return True if this message is system-level context (always visible)."""
    return source in _CONTEXT_SOURCES


def _display_context(messages: list[dict], turn: int):
    """Display messages sent to the LLM with smart collapsing.

    System context messages (phase guidance, crystal contracts, knowledge
    summaries, rollback/switch notices, base prompt) are always shown in
    full because they carry the decision-relevant context.

    Conversation messages (user, assistant, tool, misc system) are collapsed:
    only the last N are shown; older ones are summarized in one line.
    /expand toggles full display of everything.
    """
    global _last_context, _expanded
    _last_context = messages
    truncate_len = 999_999 if _expanded else 100

    from src import state

    # ── Header ────────────────────────────────────────────────────────
    header_parts = []
    if state.active_project:
        ap = state.active_project
        header_parts.append(
            f"[bold]Project:[/] {ap['project_id']} / {ap['phase']}"
            + (f" / {ap.get('module')}" if ap.get('module') else "")
        )
    if state.crystal_store:
        crystals = state.crystal_store.get_active_crystals()
        header_parts.append(f"[bold]Crystals:[/] {len(crystals)} active")

    header_parts.append(f"[bold]Messages:[/] {len(messages)} total")

    if _expanded:
        header_parts.append("[bold red]EXPANDED[/]")

    notices = []
    if state.phase_rollback_notice:
        n = state.phase_rollback_notice
        notices.append(f"[red]rollback {n['from']}→{n['to']}[/]")
    if state.module_switch_notice:
        n = state.module_switch_notice
        notices.append(f"[blue]switch {n['old_module']}→{n['new_module']}[/]")
    if state.phase_transition_notice:
        n = state.phase_transition_notice
        notices.append(f"[green]phase {n['from']}→{n['to']}[/]")
    if notices:
        header_parts.append(f"[bold]Notices:[/] {', '.join(notices)}")

    header = " │ ".join(header_parts)

    console.print()
    console.print(
        Panel(header, title=f"[bold]Turn #{turn}[/]", border_style="bright_black",
              box=box.ROUNDED, padding=(0, 2))
    )

    # ── Pre-scan: classify every message ──────────────────────────────
    # Build (index, source, badge, role_color, border, content_str) tuples.
    badge_map = {
        "system:base": "SYS:BASE", "system:phase": "SYS:PHASE",
        "system:crystal": "SYS:CRYSTAL", "system:knowledge": "SYS:MEMORY",
        "system:rollback": "SYS:ROLLBACK", "system:switch": "SYS:SWITCH",
        "system:other": "SYS", "user": "USER", "assistant": "ASSISTANT",
        "tool": "TOOL",
    }

    parsed: list[dict] = []
    for i, msg in enumerate(messages):
        source = _detect_source(msg)
        role_color, border = ROLE_STYLES.get(source, ROLE_STYLES["system:other"])
        content = msg.get("content", "") or ""

        badge = badge_map.get(source, source.upper())
        tool_name = msg.get("name", "")
        if msg.get("role") == "tool" and tool_name:
            badge = f"TOOL:{tool_name}"

        if not content:
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                content = f"[tool_calls: {', '.join(tc_names)}]"
            else:
                content = "(empty)"

        parsed.append({
            "idx": i, "source": source, "badge": badge,
            "role_color": role_color, "border": border,
            "content": content, "is_ctx": _is_context_msg(source),
        })

    # ── Decide what to render ─────────────────────────────────────────
    if _expanded:
        # Show everything, no collapsing.
        visible = set(range(len(parsed)))
        collapsed_count = 0
    else:
        # Always show context messages + the last _CONVERSATION_TAIL conversation msgs.
        ctx_indices = {p["idx"] for p in parsed if p["is_ctx"]}
        conv_indices = [p["idx"] for p in parsed if not p["is_ctx"]]
        tail_indices = set(conv_indices[-_CONVERSATION_TAIL:]) if conv_indices else set()
        visible = ctx_indices | tail_indices
        collapsed_count = len(parsed) - len(visible)

    # ── Render ────────────────────────────────────────────────────────
    last_rendered = -1
    for p in parsed:
        if p["idx"] not in visible:
            continue

        # Insert collapse marker before the first visible message
        # that comes after a gap of hidden messages.
        gap = p["idx"] - last_rendered - 1
        if gap > 0 and last_rendered >= 0:
            # Count what kind of messages were hidden in this gap.
            hidden_ctx = sum(
                1 for h in parsed if h["idx"] > last_rendered
                and h["idx"] < p["idx"] and h["is_ctx"]
            )
            hidden_conv = gap - hidden_ctx
            parts = []
            if hidden_conv > 0:
                parts.append(f"{hidden_conv} conversation")
            if hidden_ctx > 0:
                parts.append(f"{hidden_ctx} context")
            label = " + ".join(parts)
            console.print(
                f"  ── [{label} messages collapsed, /expand to show] ──",
                style="dim",
            )

        displayed = _truncate(p["content"], truncate_len)
        text = Text()
        text.append(f"[{p['border']}][{p['badge']}][/] ", style=f"bold {p['role_color']}")
        text.append(displayed, style=p['role_color'])
        console.print(text)
        last_rendered = p["idx"]

    # Trailing collapse marker (hidden messages after the last visible one).
    if collapsed_count > 0 and last_rendered < len(parsed) - 1:
        trailing = len(parsed) - 1 - last_rendered
        console.print(
            f"  ── [{trailing} more messages collapsed, /expand to show] ──",
            style="dim",
        )

    if collapsed_count > 0:
        console.print(
            f"  [dim]Displaying {len(visible)}/{len(parsed)} messages "
            f"({collapsed_count} collapsed).[/]"
        )

    console.print(Rule(style="dim"))


# ═══════════════════════════════════════════════════════════════════════════
# TUI command registry — exact-match (no prefix ambiguity).
# ═══════════════════════════════════════════════════════════════════════════

_TUI_COMMANDS = {
    "/help", "/state", "/crystals", "/context", "/save",
    "/clear", "/expand", "/done",
    "/quit", "/exit", "/q",
}


def _command_name(raw: str) -> str | None:
    """Return the TUI command name if raw is an exact TUI command (possibly
    with trailing arguments).  Returns None for tool calls and plain text.
    """
    if not raw.startswith("/"):
        return None
    # Split on first space: "/context 3" → cmd="/context"
    space = raw.find(" ")
    cmd = raw if space == -1 else raw[:space]
    if cmd in _TUI_COMMANDS:
        return cmd
    return None


# ═══════════════════════════════════════════════════════════════════════════
# User input
# ═══════════════════════════════════════════════════════════════════════════

def _get_user_response() -> tuple[str | None, list[dict] | None]:
    """Read user input. Returns (text, tool_calls).

    - Plain text → text=<response>, tool_calls=None
    - /tool_name args → text=None, tool_calls=[...]
    - /done → text="", tool_calls=None
    """
    while True:
        try:
            raw = console.input("[bold yellow]Agent >[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting...[/]")
            sys.exit(0)

        raw = raw.strip()
        if not raw:
            continue

        # ── Special commands (TUI-internal, exact match) ──────────────
        cmd = _command_name(raw)
        if cmd == "/help":
            _show_help()
            continue
        if cmd == "/state":
            _show_state()
            continue
        if cmd == "/crystals":
            _show_crystals(raw)
            continue
        if cmd == "/context":
            _show_context_detail(raw)
            continue
        if cmd == "/save":
            _save_messages()
            continue
        if cmd == "/clear":
            console.clear()
            console.print("[dim]Terminal cleared.[/]")
            continue
        if cmd == "/expand":
            global _expanded
            _expanded = not _expanded
            status = "ON — showing full messages" if _expanded else "OFF — showing 100-char summaries"
            console.print(f"[green]Expand: {status}[/]")
            if _last_context:
                _display_context(_last_context, _turn)
            continue
        if cmd == "/done":
            return "", None
        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/]")
            sys.exit(0)

        # ── Tool call ─────────────────────────────────────────────────
        if raw.startswith("/"):
            tool_calls = _parse_tool_call(raw)
            if tool_calls:
                return None, tool_calls
            console.print("[red]Failed to parse tool call. Use /help for syntax.[/]")
            continue

        # ── Plain text ────────────────────────────────────────────────
        return raw, None


def _parse_tool_call(raw: str) -> list[dict] | None:
    """Parse '/tool_name key1="val1", key2={"j":1}' into tool_calls.

    Wraps the result as a 'tools' call (the unified interface).
    """
    # Extract tool_name and args string
    raw = raw[1:]  # strip leading /
    if not raw:
        return None

    # Find first space to split tool_name from args
    space_idx = raw.find(" ")
    if space_idx == -1:
        tool_name = raw.strip()
        args_dict = {}
    else:
        tool_name = raw[:space_idx].strip()
        args_str = raw[space_idx + 1:].strip()
        args_dict = _parse_tool_args(args_str)

    # Validate tool_name
    if not tool_name:
        return None

    call_id = f"call_{uuid.uuid4().hex[:12]}"

    # Agent auto-wraps non-'tools' calls into tools() — see agent.py line ~990
    return [{
        "id": call_id,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(args_dict, ensure_ascii=False),
        },
    }]


# ═══════════════════════════════════════════════════════════════════════════
# Mock stream generators
# ═══════════════════════════════════════════════════════════════════════════

def _mock_text_stream(text: str):
    """Yield text character-by-character, then finish."""
    for char in text:
        yield MockChunk(content=char)
        time.sleep(0.002)
    # yield a final empty chunk to signal end
    yield MockChunk()


def _mock_tool_stream(tool_calls: list[dict]):
    """Yield tool_call chunks matching OpenAI streaming format.

    Agent expects: tc.index, tc.id (first chunk), tc.function.name, tc.function.arguments.
    """
    for i, tc in enumerate(tool_calls):
        func = tc["function"]
        # First chunk: id + name
        yield MockChunk(tool_calls=[
            ToolCallDelta(index=i, id=tc["id"], function_name=func["name"], function_args="")
        ])
        time.sleep(0.002)
        # Second chunk: arguments
        yield MockChunk(tool_calls=[
            ToolCallDelta(index=i, id=None, function_name="", function_args=func["arguments"])
        ])
    time.sleep(0.002)
    yield MockChunk()


# ═══════════════════════════════════════════════════════════════════════════
# Special command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _show_help():
    t = Table(title="BaseAgent TUI Commands", box=box.ROUNDED, border_style="dim")
    t.add_column("Command", style="cyan")
    t.add_column("Description", style="white")
    t.add_row("/help", "Show this help")
    t.add_row("/state", "Show current state snapshot")
    t.add_row("/crystals [type]", "List active crystals (optional type filter)")
    t.add_row("/context [N]", "Show full content of context message N (0-indexed)")
    t.add_row("/expand", "Toggle full message display (default: 100-char summary)")
    t.add_row("/clear", "Clear terminal output")
    t.add_row("/save", "Force-save messages.json")
    t.add_row("/done", "End current tool-call loop (send empty text)")
    t.add_row("/quit, /exit, /q", "Exit TUI")
    t.add_row("", "")
    t.add_row("/<tool> key=val, ...", "Send tool call to agent", style="yellow")
    t.add_row("  Example", "/crystallize crystal_type=\"ContractCrystal\", "
              "module=\"auth\", name=\"x\", content='{\"sig\":\"f()\"}'",
              style="dim")
    t.add_row("plain text", "Send text as agent response", style="green")
    console.print(t)


def _show_state():
    from src import state
    console.print(Panel(
        f"[bold]active_project:[/] {json.dumps(state.active_project, ensure_ascii=False, indent=2) if state.active_project else 'None'}\n"
        f"[bold]phase_rollback_notice:[/] {json.dumps(state.phase_rollback_notice, ensure_ascii=False) if state.phase_rollback_notice else 'None'}\n"
        f"[bold]module_switch_notice:[/] {json.dumps(state.module_switch_notice, ensure_ascii=False) if state.module_switch_notice else 'None'}\n"
        f"[bold]phase_transition_notice:[/] {json.dumps(state.phase_transition_notice, ensure_ascii=False) if state.phase_transition_notice else 'None'}\n"
        f"[bold]phase_guidance:[/] {len(state.phase_guidance)} chars" if state.phase_guidance else "None",
        title="State Snapshot",
        border_style="cyan",
    ))


def _show_crystals(raw: str):
    from src import state
    if not state.crystal_store:
        console.print("[red]CrystalStore not initialized.[/]")
        return
    parts = raw.split()
    filter_type = parts[1] if len(parts) > 1 else None
    crystals = state.crystal_store.get_active_crystals(crystal_type=filter_type)

    t = Table(title=f"Active Crystals ({len(crystals)})", box=box.ROUNDED, border_style="dim")
    t.add_column("ID", style="dim")
    t.add_column("Type", style="cyan")
    t.add_column("Module", style="green")
    t.add_column("Name", style="yellow")
    t.add_column("Layer", style="magenta")
    t.add_column("Vitality", style="dim")
    for c in crystals[:30]:
        t.add_row(
            str(c["id"]), c["crystal_type"], c.get("module", ""),
            c.get("name", ""), c.get("layer", ""), str(c.get("vitality", 0))
        )
    console.print(t)


def _show_context_detail(raw: str):
    global _last_context
    parts = raw.split()
    try:
        idx = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        console.print("[red]Usage: /context [message_index][/]")
        return

    if not _last_context:
        console.print("[dim]No context yet. Send a message first.[/]")
        return

    if idx < 0 or idx >= len(_last_context):
        console.print(f"[red]Index {idx} out of range (0-{len(_last_context)-1}).[/]")
        return

    msg = _last_context[idx]
    source = _detect_source(msg)
    content = msg.get("content", "") or ""

    console.print(Panel(
        content if content else "(empty)",
        title=f"Context [{idx}] — {source}",
        border_style="cyan",
    ))


def _save_messages():
    global _agent_instance
    if _agent_instance:
        _agent_instance._save_messages()
        console.print("[green]messages.json saved.[/]")
    else:
        console.print("[red]No agent instance.[/]")


# ═══════════════════════════════════════════════════════════════════════════
# Initialization (mirrors app.py init_agents)
# ═══════════════════════════════════════════════════════════════════════════

def _init_agents(config: dict):
    """Initialize CrystalStore, CrystalObserver, and BaseAgent."""
    from src import state
    from src.agent import BaseAgent
    from knowledge.crystals import CrystalStore
    from knowledge.crystal_observer import CrystalObserver

    crystal_path = config.get("crystal_db_path", "./crystals.db")
    state.crystal_store = CrystalStore(crystal_path)

    crystal_observer = CrystalObserver(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        crystal_store=state.crystal_store,
    )

    agent = BaseAgent(
        key=config["api_key"],
        url=config["base_url"],
        model=config["model"],
        settings=config.get("settings", "You are a helpful AI assistant."),
        temperature=config.get("temperature", 0.8),
        thinking=config.get("thinking", False),
        knowledge_k=config.get("knowledge_k", 5),
        crystal_k=config.get("crystal_k", 3),
        crystal_store=state.crystal_store,
        crystal_observer=crystal_observer,
    )

    state.chat_agent = agent
    return agent


def _load_tools():
    """Ensure built-in tools are loaded."""
    from knowledge.loader import load_builtin_tools, load_mcp_servers
    load_builtin_tools()
    try:
        load_mcp_servers()
    except Exception as e:
        console.print(f"[dim]MCP servers skipped: {e}[/]")


# ═══════════════════════════════════════════════════════════════════════════
# Monkey-patch
# ═══════════════════════════════════════════════════════════════════════════

def _install_mock(agent):
    """Replace agent.client.chat.completions.create with TUI mock."""
    global _turn, _agent_instance
    _agent_instance = agent
    _turn = 0

    original_create = agent.client.chat.completions.create

    def mock_create(model, messages, temperature, tools,
                    tool_choice, stream, extra_body=None, **kwargs):
        global _turn
        _turn += 1
        _display_context(messages, _turn)
        text, tool_calls = _get_user_response()

        if tool_calls:
            return _mock_tool_stream(tool_calls)
        return _mock_text_stream(text or "")

    agent.client.chat.completions.create = mock_create
    console.print("[green]Mock LLM installed. All API calls will be routed to TUI.[/]")


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if not config.get("debug"):
        console.print(
            "[yellow]⚠ 'debug' is false in config.json. "
            "TUI will still run, but the real agent would use the actual API.[/]"
        )

    console.print(Panel(
        "[bold]BaseAgent TUI — Mock LLM Debug Console[/]\n\n"
        "All messages sent to the LLM are displayed above each prompt.\n"
        "Type plain text to respond as the agent.\n"
        "Type [cyan]/tool_name key=val, ...[/] to invoke a tool.\n"
        "Type [cyan]/help[/] for all commands.",
        title="Welcome", border_style="green",
    ))

    # 1. Load tools
    _load_tools()
    console.print("[dim]Tools loaded.[/]")

    # 2. Initialize agent + crystal store
    agent = _init_agents(config)
    console.print("[dim]Agent initialized.[/]")

    # 3. Show crystal inventory
    from src import state
    crystals = state.crystal_store.get_active_crystals()
    if crystals:
        from collections import Counter
        by_type = Counter(c["crystal_type"] for c in crystals)
        type_summary = ", ".join(f"{t}={n}" for t, n in sorted(by_type.items()))
        console.print(f"[dim]CrystalStore: {len(crystals)} crystals ({type_summary})[/]")
    else:
        console.print("[dim]CrystalStore: empty[/]")

    # 4. Install mock
    _install_mock(agent)

    # 5. Main loop
    console.print("\n[dim]Enter your first message (as the user):[/]")
    while True:
        try:
            user_input = console.input("[bold green]User >[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/]")
            break

        # Send to agent — this will trigger mock_create for each LLM call
        console.print("[dim]Processing...[/]")
        try:
            for event in agent.input(user_input):
                if isinstance(event, str):
                    console.print(event, end="", style="bright_cyan", highlight=False)
                elif isinstance(event, dict):
                    etype = event.get("type", "")
                    if etype == "tool_call":
                        console.print(
                            f"\n[bold magenta][TOOL:{event.get('tool_name')}][/] ",
                            end="", highlight=False,
                        )
                    elif etype == "tool_result":
                        result = event.get("result", "")
                        if isinstance(result, str) and len(result) > 200:
                            result = result[:200] + "..."
                        console.print(
                            f"[bold blue]→ {result}[/]", highlight=False,
                        )
                sys.stdout.flush()
            console.print()  # trailing newline
        except Exception as e:
            console.print(f"\n[red]Agent error: {e}[/]")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

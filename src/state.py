# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Shared State - Global variables and config helpers shared across modules
"""

import json
import os
import threading

# Agent instances (set by init_agents in app.py)
chat_agent = None
tasks_agent = None

# Config read/write lock
_config_lock = threading.Lock()

# CrystalStore instance (shared between chat_agent and tasks_agent)
crystal_store = None

# Tool confirmation state (shared between /chat and /api/confirm_tool)
pending_confirmations = {}
pending_lock = threading.Lock()

# Cloudflare tunnel URL
public_url = None

# Active project state for idea-to-code-sculpting workflow
# Format: {"project_id": "my-app", "phase": "L3", "module": "Auth"}
# Set by set_project tool, read by agent._build_context / _get_relevant_knowledge
active_project = None

# Phase-aware guidance prompt (set by set_project, injected by _build_context)
# Extracted from idea-to-code-sculpting skill — minimal constraints for current phase
phase_guidance = None

# Phase rollback notice — set by set_project when phase moves backward
# Format: {"from": "L4", "to": "L3", "module": "Auth", "previous_record": "..."}
# Consumed by chat.py (SSE event) and agent._build_context(), then cleared
phase_rollback_notice = None

# Module switch notice — set by set_project when module changes within same project
# Format: {"old_module": "Auth", "new_module": "Database", "phase": "L4"}
# Consumed by agent._build_context() to inject comprehensive module entry context
module_switch_notice = None

# Phase transition notice — set by set_project on key phase boundaries
# Format: {"from": "L3", "to": "L4"}
# Currently used for L3→L4 (all contracts done, entering per-module implementation)
# Consumed by agent.input() outer loop to trigger proactive compression
phase_transition_notice = None


def load_config():
    with _config_lock:
        try:
            with open("./config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print(
                "[Config] config.json not found — using empty config",
                file=sys.stderr,
            )
            return {}
        except json.JSONDecodeError as e:
            print(
                f"[Config] config.json is malformed: {e}",
                file=sys.stderr,
            )
            return {}


def save_config(config):
    with _config_lock:
        tmp_path = "./config.json.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, "./config.json")

# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

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


def load_config():
    with _config_lock:
        with open("./config.json", "r", encoding="utf-8") as f:
            return json.load(f)


def save_config(config):
    with _config_lock:
        tmp_path = "./config.json.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, "./config.json")

# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Startup Orchestration and Public Exports
"""

from .loader import (
    load_builtin_tools,
    load_mcp_servers,
    _assemble_tools_metadata,
    tool_functions,
    tools_metadata,
    cleanup_mcp_clients,
)
from .vector import add_document, add_summary, check_and_update
from .search import search, search_texts
from .memory import add_conversation, add_conversation_with_llm
from .crystals import CrystalStore
from .config import (
    VECTOR_DB_PATH, KNOWLEDGE_ROOT, TOOLS_DIR,
    RAW_MEMORIES_DIR, RAW_TOOLS_DIR, RAW_SKILLS_DIR,
)


def _migrate_to_new_structure():
    """One-time migration from old flat directories to raw_* / *_summary layout.

    Old structure (before reorganization):
      knowledge/memories/*.md           → raw_memories/
      knowledge/skills/*.md             → raw_skills/
      knowledge/tools/{name}/README.md  → raw_tools/{name}.md

    This runs once at startup and is idempotent — files are only moved/copied
    if the destination does not already exist.
    """
    old_memories = KNOWLEDGE_ROOT / "memories"
    old_skills = KNOWLEDGE_ROOT / "skills"

    # 1. Move old memories → raw_memories/
    if old_memories.exists() and old_memories.is_dir():
        for f in old_memories.glob("*.md"):
            dest = RAW_MEMORIES_DIR / f.name
            if not dest.exists():
                f.rename(dest)
                print(f"[Migrate] {f.name} → raw_memories/")
        if not any(old_memories.iterdir()):
            old_memories.rmdir()
            print("[Migrate] Removed empty memories/")

    # 2. Move old skills → raw_skills/
    if old_skills.exists() and old_skills.is_dir():
        for f in old_skills.glob("*.md"):
            dest = RAW_SKILLS_DIR / f.name
            if not dest.exists():
                f.rename(dest)
                print(f"[Migrate] {f.name} → raw_skills/")
        if not any(old_skills.iterdir()):
            old_skills.rmdir()
            print("[Migrate] Removed empty skills/")

    # 3. Copy tools/{name}/README.md → raw_tools/{name}.md
    for tool_dir in TOOLS_DIR.iterdir():
        if not tool_dir.is_dir() or tool_dir.name.startswith("__"):
            continue
        readme = tool_dir / "README.md"
        if readme.exists():
            dest = RAW_TOOLS_DIR / f"{tool_dir.name}.md"
            if not dest.exists():
                dest.write_text(readme.read_text(encoding="utf-8"))
                print(f"[Migrate] {tool_dir.name}/README.md → raw_tools/{tool_dir.name}.md")


# Run migration once, before the vector DB check
_migrate_to_new_structure()

# Startup sequence
load_builtin_tools()
load_mcp_servers()

# Assemble tools_metadata from collected schemas
tools_metadata[:] = _assemble_tools_metadata()

check_and_update()

# Print status
from .loader import _internal_tools, _mcp_tools, _internal_schemas, _mcp_schemas

print(f"Built-in tools: {list(_internal_tools.keys())} ({len(_internal_schemas)} with schemas)")
print(f"MCP tools: {len(_mcp_tools)} ({len(_mcp_schemas)} with schemas)")
print(f"Total function definitions in tools_metadata: {len(tools_metadata)}")
print("Knowledge base incremental update completed.")

__all__ = [
    "tools_metadata",
    "tool_functions",
    "search",
    "search_texts",
    "cleanup_mcp_clients",
    "add_conversation",
    "add_conversation_with_llm",
    "add_document",
    "add_summary",
    "CrystalStore",
    "VECTOR_DB_PATH",
    "KNOWLEDGE_ROOT",
]

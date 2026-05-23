# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Shared Constants and Model Singleton
"""

from pathlib import Path
from sentence_transformers import SentenceTransformer

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_ROOT = Path(__file__).parent
TOOLS_DIR = KNOWLEDGE_ROOT / "tools"
VECTOR_DB_PATH = KNOWLEDGE_ROOT / "knowledge.db"

# ── Raw content directories (original files, read by recall tool) ──────
RAW_MEMORIES_DIR = KNOWLEDGE_ROOT / "raw_memories"
RAW_TOOLS_DIR = KNOWLEDGE_ROOT / "raw_tools"
RAW_SKILLS_DIR = KNOWLEDGE_ROOT / "raw_skills"

# ── Summary directories (extracted summaries, indexed by vector DB) ─────
MEMORIES_SUMMARY_DIR = KNOWLEDGE_ROOT / "memories_summary"
TOOLS_SUMMARY_DIR = KNOWLEDGE_ROOT / "tools_summary"
SKILLS_SUMMARY_DIR = KNOWLEDGE_ROOT / "skills_summary"

# Backward-compat alias (points to new raw_memories)
MEMORIES_DIR = RAW_MEMORIES_DIR

# Create all directories on import
for _d in (RAW_MEMORIES_DIR, RAW_TOOLS_DIR, RAW_SKILLS_DIR,
           MEMORIES_SUMMARY_DIR, TOOLS_SUMMARY_DIR, SKILLS_SUMMARY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Hybrid search weights
HYBRID_VECTOR_WEIGHT = 0.7
HYBRID_FTS_WEIGHT = 0.3

# Global Model (Singleton)
_model = None
MODEL_NAME = "all-MiniLM-L12-v2"


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

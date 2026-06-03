# Copyright (C) 2026 humanity687
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Knowledge Module - Shared Constants and Model Singleton
"""

import threading
import numpy as np
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
_model_lock = threading.Lock()
MODEL_NAME = "all-MiniLM-L12-v2"
MODEL_CACHE_DIR = str(Path.home() / ".cache" / "huggingface" / "hub")


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # double-checked locking
                try:
                    _model = SentenceTransformer(
                        MODEL_NAME,
                        cache_folder=MODEL_CACHE_DIR,
                        local_files_only=True,
                    )
                except Exception:
                    _model = SentenceTransformer(
                        MODEL_NAME, cache_folder=MODEL_CACHE_DIR
                    )
    return _model


def encode_single(text: str) -> "np.ndarray":
    """Thread-safe single-text encoding."""
    model = get_model()
    with _model_lock:
        return model.encode(text)


def encode_batch(texts: list[str]) -> "np.ndarray":
    """Thread-safe batch encoding. Use this instead of model.encode() directly."""
    model = get_model()
    with _model_lock:
        return model.encode(texts)

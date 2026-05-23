# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
CrystalStore — SQLite-backed engineering memory for idea-to-code-sculpting.

Stores structured "thought crystals" (engineering artifacts) extracted from
each skill layer (L0-L8) so the agent can recall locked decisions, interface
contracts, algorithm designs, and failure patterns across sessions.

ContractCrystal (L3) is the central type — it anchors the full
L3→L4→L6→L7→L8 engineering chain via parent_ids.
"""

import sqlite3
import json
import threading
import numpy as np
from pathlib import Path

from .config import get_model


CREATE_CRYSTALS_TABLE = """
CREATE TABLE IF NOT EXISTS crystals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crystal_type TEXT NOT NULL,
    project_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    module TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    version TEXT DEFAULT '1.0',
    parent_ids TEXT DEFAULT '[]',
    vitality INTEGER DEFAULT 0,
    deprecated INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_crystals_type ON crystals(crystal_type);",
    "CREATE INDEX IF NOT EXISTS idx_crystals_project ON crystals(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_crystals_module ON crystals(module);",
    "CREATE INDEX IF NOT EXISTS idx_crystals_vitality ON crystals(vitality DESC);",
    "CREATE INDEX IF NOT EXISTS idx_crystals_deprecated ON crystals(deprecated);",
    "CREATE INDEX IF NOT EXISTS idx_crystals_layer ON crystals(layer);",
]


class CrystalStore:
    """SQLite-backed crystal repository for engineering memory."""

    def __init__(self, db_path: str = "./crystals.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(CREATE_CRYSTALS_TABLE)
        for stmt in CREATE_INDICES:
            try:
                cursor.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ━━━ 写入 API ━━━

    def put_crystal(
        self,
        crystal_type: str,
        project_id: str,
        layer: str,
        module: str,
        name: str,
        content: dict,
        parent_ids: list[int] | None = None,
    ) -> str:
        """Insert a crystal. Returns the formatted crystal_id string."""
        content_json = json.dumps(content, ensure_ascii=False)
        pids_json = json.dumps(parent_ids or [])

        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO crystals
                   (crystal_type, project_id, layer, module, name, content, parent_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (crystal_type, project_id, layer, module, name, content_json, pids_json),
            )
            conn.commit()
            row_id = cursor.lastrowid
            conn.close()

        return f"{crystal_type}:{project_id}:{module}.{name}:v1.0"

    def deprecate_crystal(self, crystal_id: int) -> None:
        """Mark a crystal as deprecated (never delete)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE crystals SET deprecated = 1, updated_at = datetime('now') WHERE id = ?",
                (crystal_id,),
            )
            conn.commit()
            conn.close()

    def increment_vitality(self, crystal_id: int) -> None:
        """Increment vitality when a crystal is successfully reused."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE crystals SET vitality = vitality + 1, updated_at = datetime('now') WHERE id = ?",
                (crystal_id,),
            )
            conn.commit()
            conn.close()

    def set_has_implementation(self, crystal_id: int) -> None:
        """Mark a ContractCrystal as having a completed implementation."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM crystals WHERE id = ?", (crystal_id,))
            row = cursor.fetchone()
            if row:
                content = json.loads(row["content"])
                content["has_implementation"] = True
                cursor.execute(
                    "UPDATE crystals SET content = ?, updated_at = datetime('now') WHERE id = ?",
                    (json.dumps(content, ensure_ascii=False), crystal_id),
                )
            conn.commit()
            conn.close()

    # ━━━ 查询 API ━━━

    def get_crystal(self, crystal_id: int) -> dict | None:
        """Get a single crystal by its integer ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crystals WHERE id = ?", (crystal_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_active_crystals(
        self,
        project_id: str | None = None,
        crystal_type: str | None = None,
        layer: str | None = None,
        module: str | None = None,
    ) -> list[dict]:
        """Query active (non-deprecated) crystals, ordered by vitality descending."""
        conn = self._get_conn()
        cursor = conn.cursor()
        where = ["deprecated = 0"]
        params = []

        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        if crystal_type is not None:
            where.append("crystal_type = ?")
            params.append(crystal_type)
        if layer is not None:
            where.append("layer = ?")
            params.append(layer)
        if module is not None:
            where.append("module = ?")
            params.append(module)

        query = f"SELECT * FROM crystals WHERE {' AND '.join(where)} ORDER BY vitality DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def find_similar_contracts(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Find ContractCrystals similar to the query using vector similarity.
        Results weighted by vitality for ranking.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM crystals WHERE crystal_type = 'ContractCrystal' AND deprecated = 0"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        model = get_model()
        q_emb = model.encode(query)

        scored = []
        for row in rows:
            crystal = self._row_to_dict(row)
            content = crystal.get("content", {})
            signature = content.get("signature", "") if isinstance(content, dict) else ""
            if not signature:
                continue

            sig_emb = model.encode(signature)
            dot = np.dot(q_emb, sig_emb)
            norm_q = np.linalg.norm(q_emb)
            norm_s = np.linalg.norm(sig_emb)
            sim = dot / (norm_q * norm_s) if norm_q * norm_s != 0 else 0

            vitality_bonus = min(crystal["vitality"] * 0.05, 0.3)
            final_score = sim + vitality_bonus
            scored.append((final_score, crystal))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def find_related_traces(self, module_or_signature: str, top_k: int = 3) -> list[dict]:
        """Find TraceCrystals related to a module or function signature."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM crystals WHERE crystal_type = 'TraceCrystal' AND deprecated = 0"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        crystals = [self._row_to_dict(row) for row in rows]

        model = get_model()
        q_emb = model.encode(module_or_signature)

        scored = []
        for c in crystals:
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            symptom = content.get("symptom", "")
            root_cause = content.get("root_cause", "")
            combined = f"{symptom} {root_cause}"

            if not combined.strip():
                continue

            emb = model.encode(combined)
            dot = np.dot(q_emb, emb)
            norm_q = np.linalg.norm(q_emb)
            norm_d = np.linalg.norm(emb)
            sim = dot / (norm_q * norm_d) if norm_q * norm_d != 0 else 0

            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def get_full_trace(self, crystal_id: int) -> list[dict]:
        """Follow parent_ids chain from a crystal back to its earliest ancestor."""
        trace = []
        visited = set()
        current_id = crystal_id

        while current_id is not None and current_id not in visited:
            crystal = self.get_crystal(current_id)
            if crystal is None:
                break
            visited.add(current_id)
            trace.append(crystal)

            pids = crystal.get("parent_ids", [])
            if isinstance(pids, str):
                try:
                    pids = json.loads(pids)
                except json.JSONDecodeError:
                    pids = []
            current_id = pids[0] if pids else None

        return trace

    # ━━━ 上下文组装 ━━━

    def working_context(
        self,
        project_id: str,
        phase: str,
        module: str | None = None,
    ) -> str:
        """
        Build a phase-aware engineering state string for LLM context injection.

        Phase strategies:
        - L0/L1/L2: active ContractCrystals for the current project
        - L3: similar ContractCrystals (cross-project, ranked by vitality) + related Traces
        - L4: current module's ContractCrystal + its LogicCrystals
        - L6/L7: current module's ContractCrystal + related TraceCrystals
        - L8: all TraceCrystals for the project + full contract chain
        Returns "" when no relevant crystals exist.
        """
        if phase in ("L0", "L1", "L2"):
            return self._ctx_project_contracts(project_id)
        elif phase == "L3":
            return self._ctx_contract_design(project_id, module)
        elif phase == "L4":
            return self._ctx_algorithm_design(project_id, module)
        elif phase in ("L6", "L7"):
            return self._ctx_implementation(project_id, module)
        elif phase == "L8":
            return self._ctx_integration(project_id, module)
        return ""

    def _ctx_project_contracts(self, project_id: str) -> str:
        """L0/L1/L2: Show all active contracts to establish foundational constraints."""
        contracts = self.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal"
        )
        if not contracts:
            return ""

        lines = [
            "## Locked Engineering State",
            "",
            "The following interface contracts are locked for this project.",
            "Do not contradict or redesign them unless explicitly asked.",
            "",
            "### Active Contracts",
        ]
        for c in contracts:
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            sig = content.get("signature", c["name"])
            consts = content.get("constraints", [])
            lines.append(f"- [{c['layer']}] {c['module']}.{c['name']}: `{sig}`")
            for constraint in consts:
                lines.append(f"  - Constraint: {constraint}")
        return "\n".join(lines) + "\n"

    def _ctx_contract_design(self, project_id: str, module: str | None = None) -> str:
        """L3: Show similar contracts from past projects + related failure traces."""
        parts = []

        existing = self.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal", module=module
        )
        if existing:
            lines = [
                "## Existing Contracts for This Module",
                "",
                "These contracts are already locked. New design must be compatible:",
                "",
            ]
            for c in existing:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                sig = content.get("signature", "")
                lines.append(f"- {c['name']}: `{sig}` (vitality={c['vitality']})")
            parts.append("\n".join(lines))

        query = module or project_id
        similar = self.find_similar_contracts(query, top_k=3)
        if similar:
            lines = [
                "## Similar Contracts from Past Projects",
                "",
                "Reference these high-quality contracts when designing new interfaces:",
                "",
            ]
            for c in similar:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                sig = content.get("signature", "")
                lines.append(
                    f"- [{c['project_id']}] {c['module']}.{c['name']}: `{sig}` "
                    f"(vitality={c['vitality']})"
                )
            parts.append("\n".join(lines))

        traces = self.find_related_traces(module or project_id, top_k=2)
        if traces:
            lines = [
                "## Related Failure Traces",
                "",
                "Past failures in similar modules — avoid these patterns:",
                "",
            ]
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                lines.append(f"- **{t['name']}**: {content.get('root_cause', '')}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def _ctx_algorithm_design(self, project_id: str, module: str | None = None) -> str:
        """L4: Show current module's contract + any attached LogicCrystals."""
        parts = []

        if module:
            contracts = self.get_active_crystals(
                project_id=project_id,
                crystal_type="ContractCrystal",
                module=module,
            )
            if contracts:
                c = contracts[0]
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                lines = [
                    "## Current Contract",
                    "",
                    f"**{c['name']}**: `{content.get('signature', '')}`",
                    "",
                ]
                for precond in content.get("preconditions", []):
                    lines.append(f"- Pre: {precond}")
                for postcond in content.get("postconditions", []):
                    lines.append(f"- Post: {postcond}")
                lines.append("")
                lines.append("Respect the contract above. Do not change the interface.")
                parts.append("\n".join(lines))

        logics = self.get_active_crystals(
            project_id=project_id, crystal_type="LogicCrystal", module=module
        )
        if logics:
            lines = [
                "## Attached Logic Crystals",
                "",
            ]
            for l in logics:
                content = l.get("content", {}) if isinstance(l.get("content"), dict) else {}
                steps = content.get("algorithm_steps", [])
                lines.append(f"### {l['name']}")
                for step in steps:
                    lines.append(f"- {step}")
                lines.append("")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def _ctx_implementation(self, project_id: str, module: str | None = None) -> str:
        """L6/L7: Show current module's contract + related failure traces."""
        parts = []

        if module:
            contracts = self.get_active_crystals(
                project_id=project_id,
                crystal_type="ContractCrystal",
                module=module,
            )
            if contracts:
                c = contracts[0]
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                lines = [
                    "## Active Contract",
                    "",
                    f"**{c['name']}**: `{content.get('signature', '')}`",
                ]
                consts = content.get("constraints", [])
                if consts:
                    lines.append("")
                    lines.append("**Constraints:**")
                    for constraint in consts:
                        lines.append(f"- {constraint}")
                lines.append("")
                lines.append("Do not violate the contract. Use `edit` mode for surgical changes.")
                parts.append("\n".join(lines))

        traces = self.find_related_traces(module or project_id, top_k=3)
        if traces:
            lines = [
                "## Related Failure Traces (Common Pitfalls)",
                "",
            ]
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                lines.append(
                    f"- **{t['name']}**: {content.get('root_cause', '')} → {content.get('fix', '')}"
                )
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def _ctx_integration(self, project_id: str, module: str | None = None) -> str:
        """L8: Full contract chain + all TraceCrystals."""
        parts = []

        all_traces = self.get_active_crystals(
            project_id=project_id, crystal_type="TraceCrystal"
        )
        if all_traces:
            lines = [
                "## All Failure Traces for This Project",
                "",
            ]
            for t in all_traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                lines.append(
                    f"- **{t['name']}**: {content.get('symptom', '')} "
                    f"→ root: {content.get('root_cause', '')}"
                )
            parts.append("\n".join(lines))

        all_contracts = self.get_active_crystals(
            project_id=project_id, crystal_type="ContractCrystal"
        )
        if all_contracts:
            lines = [
                "## Full Contract Chain",
                "",
            ]
            for c in all_contracts:
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                sig = content.get("signature", "")
                has_impl = "✅" if content.get("has_implementation") else "⏳"
                lines.append(f"- {has_impl} {c['module']}.{c['name']}: `{sig}`")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    # ━━━ 项目归档 ━━━

    def archive_project(self, project_id: str) -> str:
        """Pack all project crystals into an ArchCrystal. Returns its ID string."""
        all_crystals = self.get_active_crystals(project_id=project_id)
        child_ids = [c["id"] for c in all_crystals]

        contracts = [c for c in all_crystals if c["crystal_type"] == "ContractCrystal"]
        modules = list({c["module"] for c in all_crystals})

        content = {
            "architecture_summary": f"Archived project with {len(modules)} modules",
            "module_topology": {m: [] for m in modules},
            "child_crystal_ids": child_ids,
            "tech_stack": [],
            "core_flow": "",
        }

        return self.put_crystal(
            crystal_type="ArchCrystal",
            project_id=project_id,
            layer="L1",
            module="__archive__",
            name=f"archive_{project_id}",
            content=content,
            parent_ids=child_ids,
        )

    # ━━━ Helpers ━━━

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["content"] = json.loads(d["content"])
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            d["parent_ids"] = json.loads(d["parent_ids"])
        except (json.JSONDecodeError, TypeError):
            d["parent_ids"] = []
        return d

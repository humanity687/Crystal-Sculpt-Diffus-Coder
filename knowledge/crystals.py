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

from .config import encode_batch


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
    persistent INTEGER DEFAULT 0,
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
        # Add missing columns for databases created before schema upgrades
        try:
            cursor.execute("ALTER TABLE crystals ADD COLUMN persistent INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
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

    def set_persistent(self, crystal_id: int, persistent: bool = True) -> None:
        """Mark or unmark a crystal as persistent (survives project archiving)."""
        val = 1 if persistent else 0
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE crystals SET persistent = ?, updated_at = datetime('now') WHERE id = ?",
                (val, crystal_id),
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

        # Collect crystals with valid signatures
        crystals = []
        signatures = []
        for row in rows:
            c = self._row_to_dict(row)
            content = c.get("content", {})
            sig = content.get("signature", "") if isinstance(content, dict) else ""
            if sig and isinstance(sig, str):
                crystals.append(c)
                signatures.append(sig)

        if not crystals:
            return []

        # Batch encode: query + all signatures in one call
        try:
            embs = encode_batch([query] + signatures)
            q_emb = embs[0]

            scored = []
            for i, c in enumerate(crystals):
                sig_emb = embs[i + 1]
                dot = np.dot(q_emb, sig_emb)
                norm_q = np.linalg.norm(q_emb)
                norm_s = np.linalg.norm(sig_emb)
                sim = dot / (norm_q * norm_s) if norm_q * norm_s != 0 else 0

                vitality_bonus = min(c["vitality"] * 0.05, 0.3)
                final_score = sim + vitality_bonus
                scored.append((final_score, c))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, c in scored[:top_k]:
                c["_score"] = round(float(score), 4)
                results.append(c)
            return results
        except Exception as e:
            import sys
            print(f"[CrystalStore] find_similar_contracts failed: {e}", file=sys.stderr)
            return []

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

        # Collect crystals with valid symptom/root_cause text
        crystals = []
        combined_texts = []
        for row in rows:
            c = self._row_to_dict(row)
            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
            combined = f"{content.get('symptom') or ''} {content.get('root_cause') or ''}"
            if combined.strip():
                crystals.append(c)
                combined_texts.append(combined)

        if not crystals:
            return []

        # Batch encode: query + all combined texts in one call
        try:
            embs = encode_batch([module_or_signature] + combined_texts)
            q_emb = embs[0]

            scored = []
            for i, c in enumerate(crystals):
                emb = embs[i + 1]
                dot = np.dot(q_emb, emb)
                norm_q = np.linalg.norm(q_emb)
                norm_d = np.linalg.norm(emb)
                sim = dot / (norm_q * norm_d) if norm_q * norm_d != 0 else 0
                scored.append((sim, c))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, c in scored[:top_k]:
                c["_score"] = round(float(score), 4)
                results.append(c)
            return results
        except Exception as e:
            import sys
            print(f"[CrystalStore] find_related_traces failed: {e}", file=sys.stderr)
            return []

    def get_full_trace(self, crystal_id: int) -> list[dict]:
        """Follow parent_ids chain from a crystal back to all ancestors (BFS)."""
        trace = []
        visited = set()
        queue = [crystal_id]

        while queue:
            current_id = queue.pop(0)
            if current_id is None or current_id in visited:
                continue
            crystal = self.get_crystal(current_id)
            if crystal is None:
                continue
            visited.add(current_id)
            trace.append(crystal)

            pids = crystal.get("parent_ids", [])
            if isinstance(pids, str):
                try:
                    pids = json.loads(pids)
                except json.JSONDecodeError:
                    pids = []
            queue.extend(pids)

        return trace

    def get_persistent_crystals(
        self, crystal_type: str | None = None
    ) -> list[dict]:
        """Get all persistent crystals across projects, ordered by vitality."""
        conn = self._get_conn()
        cursor = conn.cursor()
        if crystal_type:
            cursor.execute(
                "SELECT * FROM crystals WHERE persistent = 1 AND deprecated = 0 "
                "AND crystal_type = ? ORDER BY vitality DESC",
                (crystal_type,),
            )
        else:
            cursor.execute(
                "SELECT * FROM crystals WHERE persistent = 1 AND deprecated = 0 "
                "ORDER BY vitality DESC"
            )
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def get_module_records(self, project_id: str) -> list[dict]:
        """Get all ModuleRecord crystals for a project."""
        return self.get_active_crystals(
            project_id=project_id, crystal_type="ModuleRecord"
        )

    @staticmethod
    def _format_record_message(message) -> str:
        """Format a stored record message to readable text.

        Handles three formats:
          - Plain string
          - Old dict with 'text' and 'tool_calls' keys (set_project record)
          - New dict with 'content' key (request_approval)
        """
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            parts = []
            text = message.get("text", "")
            if text:
                parts.append(text)
            for tc in message.get("tool_calls", []):
                fn = tc.get("function", {})
                parts.append(
                    f"\n[TOOL_CALL: {fn.get('name', '?')}"
                    f"({fn.get('arguments', '')[:500]})]"
                )
            # request_approval stores raw markdown in 'content'
            if not parts and message.get("content"):
                parts.append(str(message["content"]))
            return "\n".join(parts) if parts else ""
        return str(message)

    def get_phase_record_message(
        self, project_id: str, phase: str, module: str
    ) -> str | None:
        """Get the raw recorded message for a phase+module combination.

        Used for rollback injection — when the agent rolls back to a phase,
        the previously recorded message is injected as reference.
        """
        snapshot_type = f"{phase}_snapshot"
        records = self.get_active_crystals(
            project_id=project_id, crystal_type="ModuleRecord", module=module,
        )
        matching = [r for r in records
                    if isinstance(r.get("content"), dict)
                    and r.get("content", {}).get("record_type") == snapshot_type]
        if matching:
            c = matching[0].get("content", {})
            raw = c.get("message") or c.get("content")
            return self._format_record_message(raw) if raw else None
        return None

    def get_module_entry_context(self, project_id: str, module: str) -> str:
        """Build comprehensive context when entering a module.

        Called on module switch. Returns the module's own L3 snapshot plus
        all dependency module L3 snapshots, formatted as a context block
        that replaces less relevant conversation history for the new module.
        """
        parts = []

        def _safe_list(val):
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                return [val] if val else []
            return [str(val)] if val else []

        # 1. Own module's recorded snapshots (most recent first)
        records = self.get_active_crystals(
            project_id=project_id, crystal_type="ModuleRecord", module=module,
        )
        own_snapshots = [r for r in records
                         if isinstance(r.get("content"), dict)
                         and r.get("content", {}).get("record_type", "").startswith("L")
                         and (r.get("content", {}).get("message")
                              or r.get("content", {}).get("content"))]
        if own_snapshots:
            for r in own_snapshots[:3]:  # Up to 3 most recent
                content = r.get("content", {})
                rt = content.get("record_type", "")
                raw_msg = content.get("message") or content.get("content", "")
                msg = self._format_record_message(raw_msg)
                parts.append(
                    f"## {module} — {rt}\n\n{msg[:3000]}\n"
                )

        # 2. Dependency module L3 contracts
        dep_contracts = self._get_dependency_contracts(project_id, module)
        if dep_contracts:
            lines = [
                "## 依赖模块的 L3 契约",
                "",
                "以下为本模块直接依赖的模块接口契约，实现时必须严格遵循：",
                "",
            ]
            for dc in dep_contracts:
                lines.append(f"### {dc['module']}")
                lines.append(f"签名: `{dc.get('signature', 'N/A')}`")
                for precond in _safe_list(dc.get("preconditions", [])):
                    lines.append(f"- Pre: {precond}")
                for postcond in _safe_list(dc.get("postconditions", [])):
                    lines.append(f"- Post: {postcond}")
                for constraint in _safe_list(dc.get("constraints", [])):
                    lines.append(f"- Constraint: {constraint}")
                lines.append("")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def get_crystal_by_string_id(self, crystal_id_str: str) -> dict | None:
        """Look up a crystal by its string ID.

        Format: "{crystal_type}:{project_id}:{module}.{name}:v{version}"
        The version suffix is ignored; matches by type + project + module + name.
        """
        parts = crystal_id_str.split(":")
        if len(parts) < 4:
            return None
        ctype = parts[0]
        proj_id = parts[1]
        # parts[2] = "module.name", parts[3] = "v1.0"
        mod_name = parts[2].rsplit(".", 1)
        module = mod_name[0] if len(mod_name) > 1 else parts[2]
        name = mod_name[-1] if len(mod_name) > 1 else parts[2]

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM crystals WHERE crystal_type = ? AND project_id = ? "
            "AND module = ? AND name = ? AND deprecated = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (ctype, proj_id, module, name),
        )
        row = cursor.fetchone()
        conn.close()
        return self._row_to_dict(row) if row else None

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
        elif phase in ("L3", "L3.1"):
            return self._ctx_contract_design(project_id, module)
        elif phase == "L4":
            return self._ctx_algorithm_design(project_id, module)
        elif phase == "L5":
            return self._ctx_pseudocode(project_id, module)
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
            consts = content.get("constraints") or []
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
        similar = self.find_similar_contracts(query, top_k=3) if query else []
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

        # v2.1: Inject other modules' L3 snapshots as reference
        all_records = self.get_module_records(project_id)
        other_l3 = [r for r in all_records
                    if isinstance(r.get("content"), dict)
                    and r.get("content", {}).get("record_type") == "L3_snapshot"
                    and r.get("module") != module]
        if other_l3:
            ref_lines = [
                "## Other Modules' L3 Contracts (recorded snapshots)",
                "",
                "Reference these when designing the current module's contract:",
                "",
            ]
            for r in other_l3:
                raw_msg = r.get("content", {}).get("message", "")
                msg = self._format_record_message(raw_msg)
                ref_lines.append(f"### {r['module']}")
                ref_lines.append(msg[:2000])
                ref_lines.append("")
            parts.append("\n".join(ref_lines))

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
        """L4: Show current module's contract + dependency contracts + LogicCrystals."""
        parts = []

        def _safe_list(val):
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                return [val] if val else []
            return [str(val)] if val else []

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
                for precond in _safe_list(content.get("preconditions", [])):
                    lines.append(f"- Pre: {precond}")
                for postcond in _safe_list(content.get("postconditions", [])):
                    lines.append(f"- Post: {postcond}")
                lines.append("")
                lines.append("Respect the contract above. Do not change the interface.")
                parts.append("\n".join(lines))

            # v2.1: Inject own module's L3 snapshot (recorded agent message)
            records = self.get_active_crystals(
                project_id=project_id, crystal_type="ModuleRecord", module=module
            )
            own_l3 = [r for r in records
                      if isinstance(r.get("content"), dict)
                      and r.get("content", {}).get("record_type") == "L3_snapshot"]
            if own_l3:
                r = own_l3[0]
                raw_msg = r.get("content", {}).get("message", "")
                msg = self._format_record_message(raw_msg)
                if msg:
                    parts.append(
                        "## Own Module L3 Contract (recorded snapshot)\n\n"
                        + msg[:3000]
                        + "\n"
                    )

        # v2.1: Inject dependency module L3 contracts for L4 algorithm design
        dep_contracts = self._get_dependency_contracts(project_id, module)
        if dep_contracts:
            lines = [
                "## Dependency Contracts (auto-injected for L4)",
                "",
                "You must respect these interfaces when designing the algorithm.",
                "Do not change any of these contracts — they are already locked.",
                "",
            ]
            for dc in dep_contracts:
                lines.append(f"### {dc['module']}")
                lines.append(f"**{dc.get('name', '')}**: `{dc.get('signature', '')}`")
                for precond in _safe_list(dc.get("preconditions", [])):
                    lines.append(f"- Pre: {precond}")
                for postcond in _safe_list(dc.get("postconditions", [])):
                    lines.append(f"- Post: {postcond}")
                if dc.get("constraints"):
                    for constraint in _safe_list(dc.get("constraints", [])):
                        lines.append(f"- Constraint: {constraint}")
                lines.append("")
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
                steps = content.get("algorithm_steps") or []
                if steps and isinstance(steps[0], dict):
                    steps = [s.get("step", s.get("description", str(s))) for s in steps]
                lines.append(f"### {l['name']}")
                for step in steps:
                    lines.append(f"- {step}")
                lines.append("")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def _ctx_pseudocode(self, project_id: str, module: str | None = None) -> str:
        """L5: Bridge between L4 algorithm and L6 code skeleton.

        Shows L3 contract + L4 algorithm steps + existing SkeletonCrystals
        so the pseudocode is grounded in the locked interface and algorithm.
        """
        parts = []

        def _safe_list(val):
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                return [val] if val else []
            return [str(val)] if val else []

        # 1. L3 contract (the interface the pseudocode must satisfy)
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
                    "## Interface Contract (L3)",
                    "",
                    f"**{c['name']}**: `{content.get('signature', '')}`",
                    "",
                ]
                for precond in _safe_list(content.get("preconditions", [])):
                    lines.append(f"- Pre: {precond}")
                for postcond in _safe_list(content.get("postconditions", [])):
                    lines.append(f"- Post: {postcond}")
                for constraint in _safe_list(content.get("constraints", [])):
                    lines.append(f"- Constraint: {constraint}")
                lines.append("")
                lines.append("Pseudocode must implement this contract exactly.")
                parts.append("\n".join(lines))

            # L3 snapshot (recorded message with full context)
            records = self.get_active_crystals(
                project_id=project_id, crystal_type="ModuleRecord", module=module
            )
            own_l3 = [r for r in records
                      if isinstance(r.get("content"), dict)
                      and r.get("content", {}).get("record_type") == "L3_snapshot"]
            if own_l3:
                r = own_l3[0]
                raw_msg = r.get("content", {}).get("message", "")
                msg = self._format_record_message(raw_msg)
                if msg:
                    parts.append(
                        "## Module L3 Contract (recorded snapshot)\n\n"
                        + msg[:3000] + "\n"
                    )

        # 2. L4 LogicCrystals (algorithm steps to translate)
        logics = self.get_active_crystals(
            project_id=project_id, crystal_type="LogicCrystal", module=module
        )
        if logics:
            lines = ["## Algorithm Design (L4)", ""]
            for lc in logics[:3]:
                content = lc.get("content", {}) if isinstance(lc.get("content"), dict) else {}
                lines.append(f"### {lc['name']}")
                for step in _safe_list(content.get("algorithm_steps", [])):
                    lines.append(f"- {step}")
                boundary = content.get("boundary_handling", "")
                if boundary:
                    lines.append(f"  Boundary: {boundary}")
                lines.append("")
            lines.append("Translate these steps into strict pseudocode.")
            parts.append("\n".join(lines))

        # 3. Existing SkeletonCrystals for reference
        skeletons = self.get_active_crystals(
            project_id=project_id, crystal_type="SkeletonCrystal", module=module
        )
        if skeletons:
            lines = ["## Existing Code Skeletons (L6)", ""]
            for sk in skeletons[:2]:
                content = sk.get("content", {}) if isinstance(sk.get("content"), dict) else {}
                code = content.get("code_skeleton", "")
                if code:
                    lines.append(f"### {sk['name']}")
                    lines.append(f"```\n{code[:2000]}\n```")
                    lines.append("")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) + "\n" if parts else ""

    def _get_dependency_contracts(self, project_id: str, module: str | None) -> list[dict]:
        """Get L3 contracts for all direct dependencies of a module.

        Reads DependencyGraphCrystal to find dependencies, then fetches each
        dependency's ModuleRecord (L3_snapshot) or ContractCrystal.
        Returns list of dicts with module, name, signature, pre/postconditions.
        """
        if not module:
            return []

        dep_graphs = self.get_active_crystals(
            project_id=project_id, crystal_type="DependencyGraphCrystal"
        )
        if not dep_graphs:
            return []

        graph_data = dep_graphs[0].get("content", {})
        if isinstance(graph_data, str):
            try:
                graph_data = json.loads(graph_data)
            except (json.JSONDecodeError, TypeError):
                return []

        graph = graph_data.get("graph", {})
        deps = graph.get(module, [])
        if not deps:
            return []

        results = []
        for dep_module in deps:
            # Try ContractCrystal first (structured data)
            contracts = self.get_active_crystals(
                project_id=project_id,
                crystal_type="ContractCrystal",
                module=dep_module,
            )
            if contracts:
                c = contracts[0]
                content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                results.append({
                    "module": dep_module,
                    "name": c.get("name", dep_module),
                    "signature": content.get("signature", ""),
                    "preconditions": content.get("preconditions", []),
                    "postconditions": content.get("postconditions", []),
                    "constraints": content.get("constraints", []),
                })
                continue

            # Fallback to ModuleRecord (L3_snapshot) — raw agent message
            records = self.get_active_crystals(
                project_id=project_id,
                crystal_type="ModuleRecord",
                module=dep_module,
            )
            l3_records = [r for r in records
                          if isinstance(r.get("content"), dict)
                          and r.get("content", {}).get("record_type") == "L3_snapshot"]
            if l3_records:
                r = l3_records[0]
                content = r.get("content", {})
                raw_msg = content.get("message", "")
                signature_text = self._format_record_message(raw_msg)
                results.append({
                    "module": dep_module,
                    "name": r.get("name", dep_module),
                    "signature": signature_text[:500],
                    "preconditions": [],
                    "postconditions": [],
                    "constraints": [],
                })

        return results

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
                consts = content.get("constraints") or []
                if consts:
                    lines.append("")
                    lines.append("**Constraints:**")
                    for constraint in consts:
                        lines.append(f"- {constraint}")
                lines.append("")
                lines.append("Do not violate the contract. Use `edit` mode for surgical changes.")
                parts.append("\n".join(lines))

            # v2.1: Inject own module's L3 snapshot as contract reference
            records = self.get_active_crystals(
                project_id=project_id, crystal_type="ModuleRecord", module=module
            )
            own_l3 = [r for r in records
                      if isinstance(r.get("content"), dict)
                      and r.get("content", {}).get("record_type") == "L3_snapshot"]
            if own_l3:
                r = own_l3[0]
                raw_msg = r.get("content", {}).get("message", "")
                msg = self._format_record_message(raw_msg)
                if msg:
                    parts.append(
                        "## Module L3 Contract (recorded snapshot)\n\n"
                        + msg[:3000]
                        + "\n"
                    )

        traces = self.find_related_traces(module or project_id, top_k=3)
        if traces:
            lines = [
                "## Related Failure Traces (Common Pitfalls)",
                "",
            ]
            for t in traces:
                content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                lines.append(
                    f"- **{t['name']}**: {content.get('root_cause') or ''} → {content.get('fix') or ''}"
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
                    f"- **{t['name']}**: {content.get('symptom') or ''} "
                    f"→ root: {content.get('root_cause') or ''}"
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

    def archive_project(
        self, project_id: str, persistent_crystal_ids: list[int] | None = None
    ) -> str:
        """Archive a project: deprecate non-persistent crystals, keep persistent.

        Args:
            project_id: The project to archive.
            persistent_crystal_ids: Optional list of crystal IDs to mark as
                persistent before archiving (e.g., ExperienceCrystals generated
                during the archive process).

        Returns:
            The string ID of the archive ArchCrystal.
        """
        # Mark specified crystals as persistent
        if persistent_crystal_ids:
            for cid in persistent_crystal_ids:
                self.set_persistent(cid, True)

        all_crystals = self.get_active_crystals(project_id=project_id)

        # Deprecate non-persistent crystals
        for c in all_crystals:
            if not c.get("persistent", 0):
                self.deprecate_crystal(c["id"])

        # Collect child IDs (only persistent ones remain active)
        child_ids = [
            c["id"] for c in all_crystals
            if c.get("persistent", 0) or c["id"] in (persistent_crystal_ids or [])
        ]

        modules = list({c["module"] for c in all_crystals})
        module_records = [
            c for c in all_crystals if c["crystal_type"] == "ModuleRecord"
        ]

        content = {
            "architecture_summary": (
                f"Archived project with {len(modules)} modules, "
                f"{len(module_records)} module records"
            ),
            "module_topology": {m: [] for m in modules},
            "child_crystal_ids": child_ids,
            "persistent_count": len([c for c in all_crystals if c.get("persistent", 0)]),
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

    def embed_experience_crystal(self, crystal_id: int) -> bool:
        """Embed an ExperienceCrystal into the vector DB for cross-project search.

        Builds searchable text from title + summary (the root node),
        then stores it in the vector DB with doc_type='experience_crystal'.
        Returns True on success, False on failure.
        """
        crystal = self.get_crystal(crystal_id)
        if not crystal or crystal.get("crystal_type") != "ExperienceCrystal":
            return False

        content = crystal.get("content", {})
        if not isinstance(content, dict):
            return False

        title = content.get("title", crystal.get("name", ""))
        summary = content.get("summary", "")
        searchable = f"{title} {summary}".strip()
        if not searchable:
            return False

        # Import vector module (lazy to avoid circular imports)
        from . import vector

        crystal_id_str = (
            f"ExperienceCrystal:{crystal.get('project_id', '')}:"
            f"{crystal.get('module', '')}.{crystal.get('name', '')}:v1.0"
        )
        summary_json = json.dumps({
            "title": title,
            "main_summary": summary,
            "dimensions": [
                {"dim": k, "summary": v[:60]}
                for k, v in (content.get("reference_values") or {}).items()
                if v and isinstance(v, str) and len(v) > 5
            ],
            "tags": content.get("tags", []),
            "source_project": content.get("source_project", ""),
        }, ensure_ascii=False)

        try:
            vector.add_summary(
                memory_id=crystal_id_str,
                text=searchable,
                doc_type="experience_crystal",
                source=f"crystal:{crystal_id_str}",
                summary_json=summary_json,
            )
            return True
        except Exception as e:
            import sys
            print(f"[CrystalStore] Failed to embed ExperienceCrystal: {e}", file=sys.stderr)
            return False

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

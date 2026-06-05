# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
DevelopmentJournal — SQLite-backed persistence for development toolchain data.

Four tables:
  - project_state:  Runtime state (active project/phase/module) for restart recovery
  - events:         Event journal for all development toolchain activities
  - module_progress: Per-module per-phase completion tracking
  - projects:       Project registry index
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone


CREATE_PROJECT_STATE = """
CREATE TABLE IF NOT EXISTS project_state (
    project_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    module TEXT,
    phase_guidance TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    project_id TEXT,
    phase TEXT,
    module TEXT,
    data TEXT NOT NULL DEFAULT '{}'
);
"""

CREATE_MODULE_PROGRESS = """
CREATE TABLE IF NOT EXISTS module_progress (
    project_id TEXT NOT NULL,
    module TEXT NOT NULL,
    current_phase TEXT,
    l1_done_at TEXT,
    l2_done_at TEXT,
    l3_done_at TEXT,
    l3_1_done_at TEXT,
    l4_done_at TEXT,
    l5_done_at TEXT,
    l6_done_at TEXT,
    l7_done_at TEXT,
    l8_incidents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, module)
);
"""

CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT DEFAULT 'active',
    total_modules INTEGER DEFAULT 0,
    completed_modules INTEGER DEFAULT 0
);
"""

CREATE_JOURNAL_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_module_progress_project ON module_progress(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_module_progress_status ON module_progress(status);",
]


class DevelopmentJournal:
    """SQLite-backed journal for development toolchain data persistence."""

    def __init__(self, db_path: str = "./journal.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        # Keep a persistent connection for :memory: DBs so tables survive
        # across _get_conn() calls (SQLite destroys :memory: when last conn closes)
        self._holder: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._holder = sqlite3.connect(
                "file:journal_mem?mode=memory&cache=shared", uri=True
            )
        self._init_tables()

    def _init_tables(self):
        conn = self._get_conn()
        self._ensure_tables(conn)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            db_uri = "file:journal_mem?mode=memory&cache=shared"
            conn = sqlite3.connect(db_uri, uri=True)
        else:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        self._ensure_tables(conn)
        return conn

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        """Create tables if they don't exist (idempotent)."""
        conn.execute(CREATE_PROJECT_STATE)
        conn.execute(CREATE_EVENTS)
        conn.execute(CREATE_MODULE_PROGRESS)
        conn.execute(CREATE_PROJECTS)
        for stmt in CREATE_JOURNAL_INDICES:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ======================================================================
    #  Project State (runtime state persistence for restart recovery)
    # ======================================================================

    def save_project_state(self, project_id: str, phase: str,
                           module: str | None, phase_guidance: str) -> None:
        """Upsert the active project runtime state (single row)."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            # Single-row table: delete existing then insert
            cursor.execute("DELETE FROM project_state")
            cursor.execute(
                """INSERT INTO project_state (project_id, phase, module, phase_guidance, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, phase, module or "", phase_guidance, self._now()),
            )
            conn.commit()
            conn.close()

    def load_project_state(self) -> dict | None:
        """Load the saved project state for restart recovery. Returns None if no state."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT project_id, phase, module, phase_guidance FROM project_state LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return {
            "project_id": row["project_id"],
            "phase": row["phase"],
            "module": row["module"] or None,
            "phase_guidance": row["phase_guidance"] or "",
        }

    def clear_project_state(self) -> None:
        """Remove saved project state (called on deactivate)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM project_state")
            conn.commit()
            conn.close()

    # ======================================================================
    #  Events
    # ======================================================================

    def record_event(self, event_type: str, project_id: str | None = None,
                     phase: str | None = None, module: str | None = None,
                     data: dict | None = None) -> int:
        """Record a development event. Returns the event row id."""
        data_json = json.dumps(data or {}, ensure_ascii=False)
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO events (event_type, project_id, phase, module, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_type, project_id, phase, module, data_json),
            )
            conn.commit()
            row_id = cursor.lastrowid
            conn.close()
        return row_id

    def get_events(self, project_id: str | None = None,
                   event_type: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
        """Query events with optional filters, ordered by most recent first."""
        conn = self._get_conn()
        cursor = conn.cursor()
        clauses = []
        params: list = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_recent_events(self, project_id: str, limit: int = 20) -> list[dict]:
        """Get the most recent events for a project."""
        return self.get_events(project_id=project_id, limit=limit, offset=0)

    # ======================================================================
    #  Module Progress
    # ======================================================================

    def upsert_module_progress(self, project_id: str, module: str,
                               phase_field: str | None = None,
                               status: str | None = None,
                               current_phase: str | None = None) -> None:
        """Insert or update a module progress row.

        phase_field: one of l1_done_at, l2_done_at, ..., l7_done_at. If set,
                     that column is populated with the current timestamp.
        status: if set, updates the status column.
        current_phase: if set, updates current_phase.
        """
        now = self._now()
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM module_progress WHERE project_id = ? AND module = ?",
                (project_id, module),
            )
            exists = cursor.fetchone() is not None

            if exists:
                set_parts = ["updated_at = ?"]
                params: list = [now]
                if phase_field:
                    set_parts.append(f"{phase_field} = ?")
                    params.append(now)
                if status:
                    set_parts.append("status = ?")
                    params.append(status)
                if current_phase:
                    set_parts.append("current_phase = ?")
                    params.append(current_phase)
                params += [project_id, module]
                cursor.execute(
                    f"UPDATE module_progress SET {', '.join(set_parts)} "
                    f"WHERE project_id = ? AND module = ?",
                    params,
                )
            else:
                fields = ["project_id", "module", "current_phase", "status", "updated_at"]
                values: list = [project_id, module, current_phase or "", status or "active", now]
                if phase_field:
                    fields.append(phase_field)
                    values.append(now)
                placeholders = ", ".join("?" for _ in values)
                cursor.execute(
                    f"INSERT INTO module_progress ({', '.join(fields)}) VALUES ({placeholders})",
                    values,
                )
            conn.commit()
            conn.close()

    def increment_l8_incidents(self, project_id: str, module: str) -> None:
        """Increment L8 incident counter for a module."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """UPDATE module_progress SET l8_incidents = l8_incidents + 1,
                   updated_at = ? WHERE project_id = ? AND module = ?""",
                (self._now(), project_id, module),
            )
            conn.commit()
            conn.close()

    def get_module_progress(self, project_id: str, module: str) -> dict | None:
        """Get progress for a specific module."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM module_progress WHERE project_id = ? AND module = ?",
            (project_id, module),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_module_progress(self, project_id: str) -> list[dict]:
        """Get progress for all modules in a project."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM module_progress WHERE project_id = ? ORDER BY module",
            (project_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def mark_modules_archived(self, project_id: str) -> None:
        """Mark all modules in a project as archived."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE module_progress SET status = 'archived', updated_at = ? WHERE project_id = ?",
                (self._now(), project_id),
            )
            conn.commit()
            conn.close()

    # ======================================================================
    #  Project Registry
    # ======================================================================

    def register_project(self, project_id: str) -> None:
        """Register a project (idempotent — INSERT OR IGNORE + update last_active_at)."""
        now = self._now()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR IGNORE INTO projects (project_id, created_at, last_active_at)
                   VALUES (?, ?, ?)""",
                (project_id, now, now),
            )
            conn.execute(
                "UPDATE projects SET last_active_at = ? WHERE project_id = ?",
                (now, project_id),
            )
            conn.commit()
            conn.close()

    def mark_project_archived(self, project_id: str) -> None:
        """Mark a project as archived."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE projects SET status = 'archived', last_active_at = ? WHERE project_id = ?",
                (self._now(), project_id),
            )
            conn.commit()
            conn.close()

    def get_project_summary(self, project_id: str) -> dict | None:
        """Get project registry info + module counts."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        result = dict(row)

        # Count modules
        cursor.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
            "FROM module_progress WHERE project_id = ?",
            (project_id,),
        )
        counts = cursor.fetchone()
        conn.close()
        if counts:
            result["total_modules"] = counts["total"] or 0
            result["completed_modules"] = counts["completed"] or 0
        return result

    def get_all_projects(self) -> list[dict]:
        """List all registered projects."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects ORDER BY last_active_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_project_module_counts(self, project_id: str) -> None:
        """Recalculate and update total_modules/completed_modules from module_progress."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
                "FROM module_progress WHERE project_id = ?",
                (project_id,),
            )
            counts = cursor.fetchone()
            if counts:
                conn.execute(
                    "UPDATE projects SET total_modules = ?, completed_modules = ? WHERE project_id = ?",
                    (counts["total"] or 0, counts["completed"] or 0, project_id),
                )
            conn.commit()
            conn.close()

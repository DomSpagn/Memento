"""
task_db.py
SQLite data-access layer for the Task Tracker.

Database location:
    <OutputPath>/Memento/TaskTracker/db/tasks.db
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILENAME = "tasks.db"

STATUSES = ["Open", "In Progress", "On Hold", "Closed"]

# Only these column names may be touched by update_task, preventing any
# accidental (or injected) writes to unintended columns.
_UPDATABLE_FIELDS = {"title", "project", "status", "modified_at", "closed_at", "description"}


def _db_path(output_path: str) -> Path:
    return Path(output_path) / "Memento" / "TaskTracker" / "db" / DB_FILENAME


def _connect(output_path: str) -> sqlite3.Connection:
    path = _db_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _attachments_path(output_path: str) -> Path:
    return Path(output_path) / "Memento" / "TaskTracker" / "attachments"


def init_db(output_path: str) -> None:
    """Create tables and migrate schema if needed."""
    with _connect(output_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                project     TEXT    NOT NULL DEFAULT '',
                status      TEXT    NOT NULL DEFAULT 'Open',
                description TEXT    NOT NULL DEFAULT '',
                opened_at   TEXT    NOT NULL,
                modified_at TEXT    NOT NULL,
                closed_at   TEXT
            )
        """)
        # Migration: add description column for existing databases
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "description" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        # Attachments table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id   INTEGER NOT NULL,
                filename  TEXT    NOT NULL,
                orig_name TEXT    NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        conn.commit()


def fetch_all_tasks(output_path: str) -> list[dict]:
    """Return all tasks ordered by id ascending."""
    with _connect(output_path) as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def fetch_distinct_projects(output_path: str) -> list[str]:
    """Return the sorted list of distinct non-empty project names."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT project FROM tasks"
            " WHERE project != '' ORDER BY project ASC"
        ).fetchall()
    return [r[0] for r in rows]


def create_task(output_path: str, title: str, project: str,
                status: str = "Open") -> int:
    """Insert a new task and return its assigned id."""
    now = _now()
    with _connect(output_path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, project, status, opened_at, modified_at)"
            " VALUES (?, ?, ?, ?, '')",
            (title, project, status, now),
        )
        conn.commit()
        return cur.lastrowid


def update_task(output_path: str, task_id: int, **fields) -> None:
    """Update arbitrary columns of a task (whitelisted only)."""
    safe = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not safe:
        return
    # Only touch timestamps when the status is explicitly being updated
    if "status" in safe:
        new_status = safe["status"]
        if new_status == "Closed":
            safe["closed_at"]   = _now()
            safe["modified_at"] = ""
        else:
            safe["modified_at"] = _now()
            safe["closed_at"]   = None
    set_clause = ", ".join(f"{col} = ?" for col in safe)
    values = list(safe.values()) + [task_id]
    with _connect(output_path) as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        conn.commit()


def delete_task(output_path: str, task_id: int) -> None:
    """Permanently remove a task by id."""
    with _connect(output_path) as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()


# ── Attachment helpers ────────────────────────────────────────────────────────

def fetch_task_attachments(output_path: str, task_id: int) -> list[dict]:
    """Return all attachments for a task ordered by insertion order."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT * FROM attachments WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_attachment(output_path: str, task_id: int, filename: str, orig_name: str) -> int:
    """Insert an attachment record and return its assigned id."""
    with _connect(output_path) as conn:
        cur = conn.execute(
            "INSERT INTO attachments (task_id, filename, orig_name) VALUES (?, ?, ?)",
            (task_id, filename, orig_name),
        )
        conn.commit()
        return cur.lastrowid


def remove_attachment(output_path: str, attachment_id: int) -> str | None:
    """Delete attachment record and return its stored filename, or None if not found."""
    with _connect(output_path) as conn:
        row = conn.execute(
            "SELECT filename FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        conn.commit()
    return row[0]


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

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

STATUSES = ["Open", "In Progress", "Closed"]

# Only these column names may be touched by update_task, preventing any
# accidental (or injected) writes to unintended columns.
_UPDATABLE_FIELDS = {"title", "project", "status", "modified_at", "closed_at"}


def _db_path(output_path: str) -> Path:
    return Path(output_path) / "Memento" / "TaskTracker" / "db" / DB_FILENAME


def _connect(output_path: str) -> sqlite3.Connection:
    path = _db_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(output_path: str) -> None:
    """Create the tasks table if it does not exist yet."""
    with _connect(output_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                project     TEXT    NOT NULL DEFAULT '',
                status      TEXT    NOT NULL DEFAULT 'Open',
                opened_at   TEXT    NOT NULL,
                modified_at TEXT    NOT NULL,
                closed_at   TEXT
            )
        """)
        conn.commit()


def fetch_all_tasks(output_path: str) -> list[dict]:
    """Return all tasks ordered by id ascending."""
    with _connect(output_path) as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def create_task(output_path: str, title: str, project: str,
                status: str = "Open") -> int:
    """Insert a new task and return its assigned id."""
    now = _now()
    with _connect(output_path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, project, status, opened_at, modified_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (title, project, status, now, now),
        )
        conn.commit()
        return cur.lastrowid


def update_task(output_path: str, task_id: int, **fields) -> None:
    """Update arbitrary columns of a task (whitelisted only)."""
    safe = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not safe:
        return
    safe["modified_at"] = _now()
    # Auto-stamp closed_at when task moves to Closed (if not already set).
    if safe.get("status") == "Closed" and "closed_at" not in safe:
        safe["closed_at"] = _now()
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


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")

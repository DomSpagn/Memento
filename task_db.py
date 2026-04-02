"""
task_db.py
SQLite data-access layer for the Task Tracker.

Database location:
    <OutputPath>/Memento/TaskTracker/db/tasks.db
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_FILENAME = "tasks.db"

STATUSES = ["Open", "In Progress", "On Hold", "Closed"]

# Only these column names may be touched by update_task, preventing any
# accidental (or injected) writes to unintended columns.
_UPDATABLE_FIELDS = {
    "title", "project", "status", "modified_at", "closed_at", "description",
    "alarm_at", "alarm_before", "alarm_fired",
}


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
        # Migration: add columns for existing databases
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "description" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if "alarm_at" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN alarm_at TEXT NOT NULL DEFAULT ''")
        if "alarm_before" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN alarm_before INTEGER NOT NULL DEFAULT 0")
        if "alarm_fired" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN alarm_fired INTEGER NOT NULL DEFAULT 0")
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
        # Related tasks table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS related_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL,
                related_id  INTEGER NOT NULL,
                UNIQUE (task_id, related_id),
                FOREIGN KEY (task_id)    REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (related_id) REFERENCES tasks(id) ON DELETE CASCADE
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
    new_status = safe.get("status")
    if new_status == "Closed":
        safe["closed_at"]   = _now()
        safe["modified_at"] = ""
    else:
        safe["modified_at"] = _now()
        if "status" in safe:
            safe["closed_at"] = None
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
        conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), task_id))
        conn.commit()
        return cur.lastrowid


def remove_attachment(output_path: str, attachment_id: int) -> str | None:
    """Delete attachment record and return its stored filename, or None if not found."""
    with _connect(output_path) as conn:
        row = conn.execute(
            "SELECT task_id, filename FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), row["task_id"]))
        conn.commit()
    return row["filename"]


def find_tasks_with_attachment(output_path: str, orig_name: str) -> list[dict]:
    """Return [{task_id, title, in_history}] for each task attachment with orig_name."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT a.task_id, t.title FROM attachments a "
            "JOIN tasks t ON t.id = a.task_id WHERE a.orig_name = ?",
            (orig_name,),
        ).fetchall()
        result = [{"task_id": r[0], "title": r[1], "in_history": False} for r in rows]
        try:
            rows2 = conn.execute(
                "SELECT h.task_id, t.title FROM history_attachments ha "
                "JOIN history h ON h.id = ha.history_id "
                "JOIN tasks t ON t.id = h.task_id WHERE ha.orig_name = ?",
                (orig_name,),
            ).fetchall()
            result += [{"task_id": r[0], "title": r[1], "in_history": True} for r in rows2]
        except Exception:
            pass
    return result


# ── History helpers ───────────────────────────────────────────────────────────

def _ensure_history_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id    INTEGER NOT NULL,
            body       TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL,
            modified_at TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    # migration: add modified_at to existing databases
    try:
        conn.execute("ALTER TABLE history ADD COLUMN modified_at TEXT")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_attachments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id  INTEGER NOT NULL,
            filename    TEXT    NOT NULL,
            orig_name   TEXT    NOT NULL,
            FOREIGN KEY (history_id) REFERENCES history(id) ON DELETE CASCADE
        )
    """)


def fetch_history(output_path: str, task_id: int) -> list[dict]:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        rows = conn.execute(
            "SELECT * FROM history WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_history(output_path: str) -> list[dict]:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        rows = conn.execute("SELECT * FROM history ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def add_history_entry(output_path: str, task_id: int, body: str) -> int:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        cur = conn.execute(
            "INSERT INTO history (task_id, body, created_at, modified_at) VALUES (?, ?, ?, ?)",
            (task_id, body, _now(), None),
        )
        conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), task_id))
        conn.commit()
        return cur.lastrowid


def update_history_entry(output_path: str, entry_id: int, body: str) -> None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        row = conn.execute("SELECT task_id FROM history WHERE id = ?", (entry_id,)).fetchone()
        conn.execute("UPDATE history SET body = ?, modified_at = ? WHERE id = ?", (body, _now(), entry_id))
        if row:
            conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), row["task_id"]))
        conn.commit()


def delete_history_entry(output_path: str, entry_id: int) -> None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        row = conn.execute("SELECT task_id FROM history WHERE id = ?", (entry_id,)).fetchone()
        conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
        if row:
            conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), row["task_id"]))
        conn.commit()


def fetch_history_attachments(output_path: str, history_id: int) -> list[dict]:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        rows = conn.execute(
            "SELECT * FROM history_attachments WHERE history_id = ? ORDER BY id ASC",
            (history_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_history_attachment(output_path: str, history_id: int,
                           filename: str, orig_name: str) -> int:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        cur = conn.execute(
            "INSERT INTO history_attachments (history_id, filename, orig_name)"
            " VALUES (?, ?, ?)",
            (history_id, filename, orig_name),
        )
        row = conn.execute("SELECT task_id FROM history WHERE id = ?", (history_id,)).fetchone()
        if row:
            conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), row["task_id"]))
        conn.commit()
        return cur.lastrowid


def remove_history_attachment(output_path: str, att_id: int) -> str | None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        row = conn.execute(
            "SELECT ha.filename, h.task_id FROM history_attachments ha"
            " JOIN history h ON h.id = ha.history_id WHERE ha.id = ?", (att_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM history_attachments WHERE id = ?", (att_id,))
        conn.execute("UPDATE tasks SET modified_at = ? WHERE id = ?", (_now(), row["task_id"]))
        conn.commit()
    return row["filename"]


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# ── Bulk fetch helpers (used for search indexing) ────────────────────────────

def fetch_all_task_attachments(output_path: str) -> list[dict]:
    """Return every attachment row (all tasks)."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT task_id, orig_name FROM attachments ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_history_attachments_bulk(output_path: str) -> list[dict]:
    """Return every history-attachment row joined with its history entry (gives task_id)."""
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        rows = conn.execute(
            "SELECT ha.orig_name, h.task_id "
            "FROM history_attachments ha "
            "JOIN history h ON h.id = ha.history_id "
            "ORDER BY ha.id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_related_task_links(output_path: str) -> list[dict]:
    """Return every related-task link with the related task's title."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT r.task_id, t.title AS related_title "
            "FROM related_tasks r JOIN tasks t ON t.id = r.related_id "
            "ORDER BY r.id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Related tasks helpers ─────────────────────────────────────────────────────

def fetch_related_tasks(output_path: str, task_id: int) -> list[dict]:
    """Return tasks related to task_id, ordered by related_id."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.title, t.status
            FROM related_tasks r
            JOIN tasks t ON t.id = r.related_id
            WHERE r.task_id = ?
            ORDER BY r.related_id ASC
            """,
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_related_task(output_path: str, task_id: int, related_id: int) -> bool:
    """Link related_id to task_id. Returns False if already exists or invalid."""
    if task_id == related_id:
        return False
    with _connect(output_path) as conn:
        # Verify the related task exists
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (related_id,)).fetchone()
        if row is None:
            return False
        try:
            conn.execute(
                "INSERT INTO related_tasks (task_id, related_id) VALUES (?, ?)",
                (task_id, related_id),
            )
            conn.commit()
        except Exception:
            return False
    return True


def remove_related_task(output_path: str, task_id: int, related_id: int) -> None:
    """Remove the link between task_id and related_id."""
    with _connect(output_path) as conn:
        conn.execute(
            "DELETE FROM related_tasks WHERE task_id = ? AND related_id = ?",
            (task_id, related_id),
        )
        conn.commit()


# ── Alarm helpers ─────────────────────────────────────────────────────────────

def get_pending_alarms(output_path: str) -> list[dict]:
    """Return tasks whose alarm is due and hasn't been fired yet."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE alarm_at != '' AND alarm_fired = 0"
        ).fetchall()
    now = datetime.now()
    result = []
    for r in rows:
        t = dict(r)
        try:
            before = int(t.get("alarm_before") or 0)
            trigger = datetime.fromisoformat(t["alarm_at"]) - timedelta(minutes=before)
            if now >= trigger:
                result.append(t)
        except (ValueError, TypeError):
            pass
    return result


def mark_alarm_fired(output_path: str, task_id: int) -> None:
    """Mark a task alarm as fired so it won't fire again."""
    with _connect(output_path) as conn:
        conn.execute("UPDATE tasks SET alarm_fired = 1 WHERE id = ?", (task_id,))
        conn.commit()

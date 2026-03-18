"""
design_db.py
SQLite data-access layer for the Design Tracker.

Database location:
    <OutputPath>/Memento/DesignTracker/db/designs.db
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILENAME = "designs.db"

STATUSES   = ["Open", "In Progress", "On Hold", "Closed"]
CATEGORIES = ["Schematic", "PCB", "Block Diagram", "Other"]
FUNCTIONS  = ["Connectivity", "Logic", "HIL", "Other"]

_UPDATABLE_FIELDS = {
    "title", "project", "board", "revision", "category", "category_custom",
    "function", "function_custom", "status",
    "modified_at", "closed_at", "description",
}


def _db_path(output_path: str) -> Path:
    return Path(output_path) / "Memento" / "DesignTracker" / "db" / DB_FILENAME


def _connect(output_path: str) -> sqlite3.Connection:
    path = _db_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _attachments_path(output_path: str) -> Path:
    return Path(output_path) / "Memento" / "DesignTracker" / "attachments"


def init_db(output_path: str) -> None:
    """Create tables and migrate schema if needed."""
    with _connect(output_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS designs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                title            TEXT    NOT NULL,
                project          TEXT    NOT NULL DEFAULT '',
                board            TEXT    NOT NULL DEFAULT '',
                revision         TEXT    NOT NULL DEFAULT '',
                category         TEXT    NOT NULL DEFAULT 'Schematic',
                category_custom  TEXT    NOT NULL DEFAULT '',
                function         TEXT    NOT NULL DEFAULT 'Connectivity',
                function_custom  TEXT    NOT NULL DEFAULT '',
                status           TEXT    NOT NULL DEFAULT 'Open',
                description      TEXT    NOT NULL DEFAULT '',
                opened_at        TEXT    NOT NULL,
                modified_at      TEXT    NOT NULL DEFAULT '',
                closed_at        TEXT
            )
        """)
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(designs)").fetchall()]
        for col, definition in [
            ("description",     "TEXT NOT NULL DEFAULT ''"),
            ("board",           "TEXT NOT NULL DEFAULT ''"),
            ("revision",        "TEXT NOT NULL DEFAULT ''"),
            ("category_custom", "TEXT NOT NULL DEFAULT ''"),
            ("function_custom", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE designs ADD COLUMN {col} {definition}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                design_id INTEGER NOT NULL,
                filename  TEXT    NOT NULL,
                orig_name TEXT    NOT NULL,
                FOREIGN KEY (design_id) REFERENCES designs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS related_designs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                design_id   INTEGER NOT NULL,
                related_id  INTEGER NOT NULL,
                UNIQUE (design_id, related_id),
                FOREIGN KEY (design_id)  REFERENCES designs(id) ON DELETE CASCADE,
                FOREIGN KEY (related_id) REFERENCES designs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS design_task_links (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                design_id  INTEGER NOT NULL,
                task_id    INTEGER NOT NULL,
                UNIQUE (design_id, task_id),
                FOREIGN KEY (design_id) REFERENCES designs(id) ON DELETE CASCADE
            )
        """)
        conn.commit()


def fetch_all_designs(output_path: str) -> list[dict]:
    with _connect(output_path) as conn:
        rows = conn.execute("SELECT * FROM designs ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def fetch_distinct_projects(output_path: str) -> list[str]:
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT project FROM designs"
            " WHERE project != '' ORDER BY project ASC"
        ).fetchall()
    return [r[0] for r in rows]


def create_design(output_path: str, title: str, project: str, board: str = "",
                  revision: str = "",
                  category: str = "Schematic", category_custom: str = "",
                  function: str = "Connectivity", function_custom: str = "",
                  status: str = "Open") -> int:
    now = _now()
    with _connect(output_path) as conn:
        cur = conn.execute(
            "INSERT INTO designs (title, project, board, revision, category, category_custom,"
            " function, function_custom, status, opened_at, modified_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
            (title, project, board, revision, category, category_custom,
             function, function_custom, status, now),
        )
        conn.commit()
        return cur.lastrowid


def update_design(output_path: str, design_id: int, **fields) -> None:
    safe = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not safe:
        return
    if "status" in safe:
        new_status = safe["status"]
        if new_status == "Closed":
            safe["closed_at"]   = _now()
            safe["modified_at"] = ""
        else:
            safe["modified_at"] = _now()
            safe["closed_at"]   = None
    set_clause = ", ".join(f"{col} = ?" for col in safe)
    values = list(safe.values()) + [design_id]
    with _connect(output_path) as conn:
        conn.execute(f"UPDATE designs SET {set_clause} WHERE id = ?", values)
        conn.commit()


def delete_design(output_path: str, design_id: int) -> None:
    with _connect(output_path) as conn:
        conn.execute("DELETE FROM designs WHERE id = ?", (design_id,))
        conn.commit()


# ── Attachment helpers ────────────────────────────────────────────────────────

def fetch_design_attachments(output_path: str, design_id: int) -> list[dict]:
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT * FROM attachments WHERE design_id = ? ORDER BY id ASC",
            (design_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_attachment(output_path: str, design_id: int, filename: str, orig_name: str) -> int:
    with _connect(output_path) as conn:
        cur = conn.execute(
            "INSERT INTO attachments (design_id, filename, orig_name) VALUES (?, ?, ?)",
            (design_id, filename, orig_name),
        )
        conn.commit()
        return cur.lastrowid


def remove_attachment(output_path: str, attachment_id: int) -> str | None:
    with _connect(output_path) as conn:
        row = conn.execute(
            "SELECT filename FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        conn.commit()
    return row[0]


# ── History helpers ───────────────────────────────────────────────────────────

def _ensure_history_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            design_id  INTEGER NOT NULL,
            body       TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL,
            FOREIGN KEY (design_id) REFERENCES designs(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_attachments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id  INTEGER NOT NULL,
            filename    TEXT    NOT NULL,
            orig_name   TEXT    NOT NULL,
            FOREIGN KEY (history_id) REFERENCES history(id) ON DELETE CASCADE
        )
    """)


def fetch_history(output_path: str, design_id: int) -> list[dict]:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        rows = conn.execute(
            "SELECT * FROM history WHERE design_id = ? ORDER BY id ASC",
            (design_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_history_entry(output_path: str, design_id: int, body: str) -> int:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        cur = conn.execute(
            "INSERT INTO history (design_id, body, created_at) VALUES (?, ?, ?)",
            (design_id, body, _now()),
        )
        conn.commit()
        return cur.lastrowid


def update_history_entry(output_path: str, entry_id: int, body: str) -> None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        conn.execute("UPDATE history SET body = ? WHERE id = ?", (body, entry_id))
        conn.commit()


def delete_history_entry(output_path: str, entry_id: int) -> None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
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
        conn.commit()
        return cur.lastrowid


def remove_history_attachment(output_path: str, att_id: int) -> str | None:
    with _connect(output_path) as conn:
        _ensure_history_tables(conn)
        row = conn.execute(
            "SELECT filename FROM history_attachments WHERE id = ?", (att_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM history_attachments WHERE id = ?", (att_id,))
        conn.commit()
    return row[0]


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# ── Related designs helpers ───────────────────────────────────────────────────

def fetch_related_designs(output_path: str, design_id: int) -> list[dict]:
    with _connect(output_path) as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.title, d.status
            FROM related_designs r
            JOIN designs d ON d.id = r.related_id
            WHERE r.design_id = ?
            ORDER BY r.related_id ASC
            """,
            (design_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_related_design(output_path: str, design_id: int, related_id: int) -> bool:
    if design_id == related_id:
        return False
    with _connect(output_path) as conn:
        row = conn.execute("SELECT id FROM designs WHERE id = ?", (related_id,)).fetchone()
        if row is None:
            return False
        try:
            conn.execute(
                "INSERT INTO related_designs (design_id, related_id) VALUES (?, ?)",
                (design_id, related_id),
            )
            conn.commit()
        except Exception:
            return False
    return True


def remove_related_design(output_path: str, design_id: int, related_id: int) -> None:
    with _connect(output_path) as conn:
        conn.execute(
            "DELETE FROM related_designs WHERE design_id = ? AND related_id = ?",
            (design_id, related_id),
        )
        conn.commit()


# ── Design-Task link helpers ──────────────────────────────────────────────

def fetch_design_task_links(output_path: str, design_id: int) -> list[dict]:
    """Return all task IDs linked to this design."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT * FROM design_task_links WHERE design_id = ? ORDER BY id ASC",
            (design_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_design_task_link(output_path: str, design_id: int, task_id: int) -> bool:
    """Link a task to this design. Returns False if already linked."""
    with _connect(output_path) as conn:
        try:
            conn.execute(
                "INSERT INTO design_task_links (design_id, task_id) VALUES (?, ?)",
                (design_id, task_id),
            )
            conn.commit()
        except Exception:
            return False
    return True


def remove_design_task_link(output_path: str, design_id: int, task_id: int) -> None:
    """Remove the link between design_id and task_id."""
    with _connect(output_path) as conn:
        conn.execute(
            "DELETE FROM design_task_links WHERE design_id = ? AND task_id = ?",
            (design_id, task_id),
        )
        conn.commit()


def fetch_task_design_links(output_path: str, task_id: int) -> list[dict]:
    """Return all design IDs linked to this task (reverse lookup)."""
    with _connect(output_path) as conn:
        rows = conn.execute(
            "SELECT * FROM design_task_links WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_task_design_link(output_path: str, task_id: int, design_id: int) -> bool:
    """Link a design to this task. Returns False if already linked."""
    with _connect(output_path) as conn:
        try:
            conn.execute(
                "INSERT INTO design_task_links (design_id, task_id) VALUES (?, ?)",
                (design_id, task_id),
            )
            conn.commit()
        except Exception:
            return False
    return True


def remove_task_design_link(output_path: str, task_id: int, design_id: int) -> None:
    """Remove the link between task_id and design_id."""
    with _connect(output_path) as conn:
        conn.execute(
            "DELETE FROM design_task_links WHERE design_id = ? AND task_id = ?",
            (design_id, task_id),
        )
        conn.commit()

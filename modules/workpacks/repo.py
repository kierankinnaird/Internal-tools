"""All database access for workpacks. Plain sqlite3, no web code."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .fields import WORKPACK_COLUMNS


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value) -> str:
    """Whatever was typed or pasted, as tidy text. Blank stays blank; line breaks inside text are kept."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


class Repo:
    def __init__(self, db_path: Path, audit: Callable[[str, str], None] = lambda a, d: None):
        self.db_path = Path(db_path)
        self._audit = audit

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ---- workpacks -------------------------------------------------------------------------
    def list_workpacks(self) -> List[Dict]:
        with self._db() as db:
            rows = db.execute(
                "SELECT w.*, (SELECT COUNT(*) FROM certificate c WHERE c.workpack_id = w.id) AS certificates "
                "FROM workpack w ORDER BY w.id DESC").fetchall()
        return [dict(r) for r in rows]

    def get_workpack(self, wp_id: int) -> Optional[Dict]:
        with self._db() as db:
            r = db.execute("SELECT * FROM workpack WHERE id=?", (wp_id,)).fetchone()
        return dict(r) if r else None

    def create_workpack(self, data: Dict, user: str) -> int:
        values = {c: clean(data.get(c)) for c in WORKPACK_COLUMNS}
        if not values["title"]:
            raise ValueError("Project title is required")
        stamp = now()
        columns = WORKPACK_COLUMNS + ["created_at", "created_by", "updated_at", "updated_by"]
        params = [values[c] for c in WORKPACK_COLUMNS] + [stamp, user, stamp, user]
        with self._db() as db:
            cur = db.execute(f"INSERT INTO workpack ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})", params)
        self._audit("workpack_created", values["title"])
        return cur.lastrowid

    def update_workpack(self, wp_id: int, data: Dict, user: str) -> Dict:
        """Change only the fields present in data; anything else is left as it was."""
        old = self.get_workpack(wp_id)
        if not old:
            raise ValueError("No such workpack")
        changes = {c: clean(data[c]) for c in WORKPACK_COLUMNS if c in data}
        if "title" in changes and not changes["title"]:
            raise ValueError("Project title is required")
        changes.update(updated_at=now(), updated_by=user)
        with self._db() as db:
            db.execute(f"UPDATE workpack SET {','.join(c + '=?' for c in changes)} WHERE id=?", [*changes.values(), wp_id])
        self._audit("workpack_updated", old["title"])
        return self.get_workpack(wp_id)

    def delete_workpack(self, wp_id: int) -> None:
        wp = self.get_workpack(wp_id)
        with self._db() as db:
            db.execute("DELETE FROM workpack WHERE id=?", (wp_id,))
        self._audit("workpack_deleted", wp["title"] if wp else str(wp_id))
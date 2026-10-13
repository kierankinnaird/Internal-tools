"""All database access for workpacks. Plain sqlite3, no web code."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .fields import CERTIFICATE_COLUMNS, WORKPACK_COLUMNS


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

    def _touch(self, db, wp_id: int, user: str) -> None:
        """Record that something under this workpack changed."""
        db.execute("UPDATE workpack SET updated_at=?, updated_by=? WHERE id=?", (now(), user, wp_id))

    # ---- certificates ----------------------------------------------------------------------
    def list_certificates(self, wp_id: int) -> List[Dict]:
        with self._db() as db:
            rows = db.execute(
                "SELECT c.*, "
                "(SELECT COUNT(*) FROM line  x WHERE x.certificate_id = c.id) AS line_count, "
                "(SELECT COUNT(*) FROM joint x WHERE x.certificate_id = c.id) AS joint_count, "
                "(SELECT COUNT(*) FROM tag   x WHERE x.certificate_id = c.id) AS tag_count "
                "FROM certificate c WHERE c.workpack_id=? ORDER BY c.position, c.id", (wp_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_certificate(self, cert_pk: int) -> Optional[Dict]:
        with self._db() as db:
            r = db.execute("SELECT * FROM certificate WHERE id=?", (cert_pk,)).fetchone()
        return dict(r) if r else None

    def add_certificate(self, wp_id: int, data: Dict, user: str) -> int:
        cert_id, form = clean(data.get("cert_id")), clean(data.get("form"))
        if not cert_id:
            raise ValueError("Certificate ID is required")
        if not form:
            raise ValueError("Form is required")
        values = {c: clean(data.get(c)) for c in CERTIFICATE_COLUMNS}
        with self._db() as db:
            if not db.execute("SELECT 1 FROM workpack WHERE id=?", (wp_id,)).fetchone():
                raise ValueError("No such workpack")
            if db.execute("SELECT 1 FROM certificate WHERE workpack_id=? AND cert_id=?", (wp_id, cert_id)).fetchone():
                raise ValueError(f"Certificate {cert_id} already exists in this workpack")
            position = (db.execute("SELECT MAX(position) FROM certificate WHERE workpack_id=?", (wp_id,)).fetchone()[0] or 0) + 1
            columns = ["workpack_id", "position", "cert_id", "form"] + CERTIFICATE_COLUMNS
            params = [wp_id, position, cert_id, form] + [values[c] for c in CERTIFICATE_COLUMNS]
            cur = db.execute(f"INSERT INTO certificate ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})", params)
            self._touch(db, wp_id, user)
        self._audit("certificate_added", f"{form} {cert_id}")
        return cur.lastrowid

    def update_certificate(self, cert_pk: int, data: Dict, user: str) -> Dict:
        """Change only the fields present in data (including cert_id and form)."""
        old = self.get_certificate(cert_pk)
        if not old:
            raise ValueError("No such certificate")
        changes = {c: clean(data[c]) for c in ["cert_id", "form"] + CERTIFICATE_COLUMNS if c in data}
        if "cert_id" in changes and not changes["cert_id"]:
            raise ValueError("Certificate ID is required")
        if "form" in changes and not changes["form"]:
            raise ValueError("Form is required")
        with self._db() as db:
            new_id = changes.get("cert_id")
            if new_id and new_id != old["cert_id"] and db.execute(
                    "SELECT 1 FROM certificate WHERE workpack_id=? AND cert_id=?", (old["workpack_id"], new_id)).fetchone():
                raise ValueError(f"Certificate {new_id} already exists in this workpack")
            if changes:
                db.execute(f"UPDATE certificate SET {','.join(c + '=?' for c in changes)} WHERE id=?", [*changes.values(), cert_pk])
            self._touch(db, old["workpack_id"], user)
        self._audit("certificate_updated", f"{old['form']} {old['cert_id']}")
        return self.get_certificate(cert_pk)

    def delete_certificate(self, cert_pk: int, user: str) -> None:
        old = self.get_certificate(cert_pk)
        if not old:
            return
        with self._db() as db:
            db.execute("DELETE FROM certificate WHERE id=?", (cert_pk,))
            self._touch(db, old["workpack_id"], user)
        self._audit("certificate_deleted", f"{old['form']} {old['cert_id']}")
"""What the jobcards module offers other modules as the service "jobcards.link".

A jobcards workpack can optionally belong to a workpack in another module (the workpacks module). The other module's
workpack id is kept in jobcards' own database as `workpacks_ref`; NULL means not linked. Nothing here imports another
module, and everything goes in and out as plain dicts, lists and numbers.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, List

from .constants import TRADES
from .repo import Repo

MAX_CREATE = 100          # most blank jobcards one call may create

_CREATE_KEYS = ("number", "title", "asset", "location", "discipline", "ces_doc_no", "fcp_no", "jobcard_prefix")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ref(value) -> int:
    """The other module's workpack id: a whole number from 1."""
    if not _is_int(value) or value < 1:
        raise ValueError("A workpack is required")
    return value


class JobcardsLink:
    def __init__(self, db_path: Path, audit: Callable[[str, str], None] = lambda a, d: None):
        self.db_path = Path(db_path)
        self._audit = audit
        self._repo = Repo(self.db_path, audit=audit)

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

    def _get(self, jc_wp_id):
        """One jobcards workpack row (number and current link), or ValueError when there is no such workpack."""
        row = None
        if _is_int(jc_wp_id):
            with self._db() as db:
                row = db.execute("SELECT id, number, workpacks_ref FROM workpack WHERE id=?", (jc_wp_id,)).fetchone()
        if not row:
            raise ValueError("No such jobcards workpack")
        return dict(row)

    # ---- reading ---------------------------------------------------------------------------
    def trades(self) -> List[str]:
        return list(TRADES)

    def available(self) -> List[Dict]:
        """Jobcards workpacks that are not linked to anything, newest first."""
        with self._db() as db:
            rows = db.execute(
                "SELECT w.id, w.number, w.title, (SELECT COUNT(*) FROM jobcard j WHERE j.workpack_id = w.id) AS jobcards "
                "FROM workpack w WHERE w.workpacks_ref IS NULL ORDER BY w.id DESC").fetchall()
        return [dict(r) for r in rows]

    def linked(self, ref: int) -> List[Dict]:
        """The jobcards workpacks linked to one workpack, oldest first, each with a summary of its jobcards."""
        ref = _ref(ref)
        with self._db() as db:
            wps = [dict(r) for r in db.execute(
                "SELECT id, number, title, asset, location, discipline, fcp_no FROM workpack "
                "WHERE workpacks_ref=? ORDER BY id", (ref,))]
        for wp in wps:
            wp["jobcards"] = [{"id": j["id"], "number": j["number"], "title": j["title"], "trade": j["trade"],
                               "revision": j["revision"], "tasks": len(j["tasks"]), "warnings": j["warning_count"],
                               "totals": j["totals"]}
                              for j in self._repo.list_jobcards(wp["id"])]
        return wps

    # ---- changing --------------------------------------------------------------------------
    def create_for(self, ref: int, user: str, data: Dict, count: int = 0, trade: str = "") -> int:
        """A new jobcards workpack linked to `ref`, with `count` blank jobcards. All or nothing."""
        ref = _ref(ref)
        if not _is_int(count) or not 0 <= count <= MAX_CREATE:
            raise ValueError(f"The number of jobcards must be a whole number from 0 to {MAX_CREATE}")
        trade = trade if trade in TRADES else ""
        values = {k: str(data.get(k) or "") for k in _CREATE_KEYS}
        wp_id = self._repo.create_workpack(values, user)        # refuses a missing or duplicate number, saving nothing
        try:
            with self._db() as db:
                db.execute("UPDATE workpack SET workpacks_ref=? WHERE id=?", (ref, wp_id))
            for _ in range(count):
                self._repo.create_jobcard(wp_id, user, trade)
        except Exception:
            self._repo.delete_workpack(wp_id)                   # takes its jobcards with it
            raise
        self._audit("workpack_linked", f"{values['number']} -> workpack {ref}")
        return wp_id

    def link(self, jc_wp_id: int, ref: int, user: str) -> None:
        ref = _ref(ref)
        wp = self._get(jc_wp_id)
        if wp["workpacks_ref"] == ref:
            return
        if wp["workpacks_ref"] is not None:
            raise ValueError(f"{wp['number']} is already linked to another workpack. Unlink it there first")
        with self._db() as db:
            changed = db.execute("UPDATE workpack SET workpacks_ref=? WHERE id=? AND workpacks_ref IS NULL",
                                 (ref, wp["id"])).rowcount
        if not changed:                                          # someone linked it between the read and the write
            raise ValueError(f"{wp['number']} is already linked to another workpack. Unlink it there first")
        self._audit("workpack_linked", f"{wp['number']} -> workpack {ref}")

    def unlink(self, jc_wp_id: int, user: str) -> None:
        wp = self._get(jc_wp_id)
        if wp["workpacks_ref"] is None:
            return
        with self._db() as db:
            db.execute("UPDATE workpack SET workpacks_ref=NULL WHERE id=?", (wp["id"],))
        self._audit("workpack_unlinked", f"{wp['number']} (was workpack {wp['workpacks_ref']})")

    def unlink_all(self, ref: int, user: str) -> int:
        """Let go of every jobcards workpack linked to `ref`. The jobcards themselves are kept."""
        ref = _ref(ref)
        with self._db() as db:
            count = db.execute("UPDATE workpack SET workpacks_ref=NULL WHERE workpacks_ref=?", (ref,)).rowcount
        if count:
            self._audit("workpack_unlinked", f"{count} jobcards workpack(s) from workpack {ref}")
        return count

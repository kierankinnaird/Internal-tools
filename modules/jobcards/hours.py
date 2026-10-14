"""What the jobcards module offers other modules as the service "jobcards.hours": the frozen hours in its snapshots.

A snapshot is the hours by trade of one jobcards workpack on the day it was taken, so something built from it (a CTR)
can say which version of the jobcards it used. This is read-only. Everything goes out as plain dicts, lists and numbers;
hours are whole numbers (see calc.tidy_hours), and nothing here imports another module.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List

from . import calc


class JobcardsHours:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def snapshots(self) -> List[Dict]:
        """Every snapshot, newest first, with the workpack it belongs to and its total hours."""
        with self._db() as db:
            rows = db.execute(
                "SELECT s.id, s.label, s.created_at, s.created_by, w.number AS workpack_number, w.title AS workpack_title, "
                "COALESCE((SELECT SUM(l.library_hours + l.manual_hours) FROM snapshot_line l WHERE l.snapshot_id = s.id), 0) AS total "
                "FROM snapshot s JOIN workpack w ON w.id = s.workpack_id ORDER BY s.id DESC").fetchall()
        out = [dict(r) for r in rows]
        for r in out:
            r["total"] = calc.tidy_hours(r["total"])
        return out

    def snapshot(self, snapshot_id) -> Dict:
        """One snapshot with its hours by trade: {'id', 'label', 'created_at', 'created_by', 'workpack_number',
        'workpack_title', 'total', 'lines': [{'trade', 'library', 'manual', 'total'}]}. ValueError when there is none."""
        row = None
        if isinstance(snapshot_id, int) and not isinstance(snapshot_id, bool):
            with self._db() as db:
                row = db.execute(
                    "SELECT s.id, s.label, s.created_at, s.created_by, w.number AS workpack_number, w.title AS workpack_title "
                    "FROM snapshot s JOIN workpack w ON w.id = s.workpack_id WHERE s.id=?", (snapshot_id,)).fetchone()
                lines = [dict(r) for r in db.execute(
                    "SELECT trade, library_hours AS library, manual_hours AS manual FROM snapshot_line "
                    "WHERE snapshot_id=? ORDER BY trade", (snapshot_id,))] if row else []
        if not row:
            raise ValueError("No such snapshot")
        for l in lines:
            l["total"] = calc.tidy_hours(l["library"] + l["manual"])
            l["library"], l["manual"] = calc.tidy_hours(l["library"]), calc.tidy_hours(l["manual"])
        snap = dict(row)
        snap["lines"] = lines
        snap["total"] = calc.tidy_hours(sum(l["total"] for l in lines))
        return snap

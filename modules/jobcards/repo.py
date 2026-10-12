"""All database access for jobcards. Plain sqlite3, no web code."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import calc
from .constants import ALL_FLAGS

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

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
                "SELECT w.*, (SELECT COUNT(*) FROM jobcard j WHERE j.workpack_id = w.id) AS jobcards "
                "FROM workpack w ORDER BY w.id DESC").fetchall()
        return [dict(r) for r in rows]

    def get_workpack(self, wp_id: int) -> Optional[Dict]:
        with self._db() as db:
            r = db.execute("SELECT * FROM workpack WHERE id=?", (wp_id,)).fetchone()
        return dict(r) if r else None

    def create_workpack(self, data: Dict, user: str) -> int:
        number = (data.get("number") or "").strip()
        if not number:
            raise ValueError("Workpack number is required")
        prefix = (data.get("jobcard_prefix") or "").strip() or number + "-"
        with self._db() as db:
            if db.execute("SELECT 1 FROM workpack WHERE number=?", (number,)).fetchone():
                raise ValueError(f"Workpack {number} already exists")
            cur = db.execute(
                "INSERT INTO workpack (number,title,asset,location,discipline,ces_doc_no,fcp_no,jobcard_prefix,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (number, data.get("title", "").strip(), data.get("asset", "").strip(), data.get("location", "").strip(),
                 data.get("discipline", "").strip(), data.get("ces_doc_no", "").strip(), data.get("fcp_no", "").strip(), prefix, user, now()))
        self._audit("workpack_created", number)
        return cur.lastrowid

    def update_workpack(self, wp_id: int, data: Dict) -> None:
        with self._db() as db:
            db.execute("UPDATE workpack SET title=?, asset=?, location=?, discipline=?, ces_doc_no=?, fcp_no=? WHERE id=?",
                       (data.get("title", "").strip(), data.get("asset", "").strip(), data.get("location", "").strip(),
                        data.get("discipline", "").strip(), data.get("ces_doc_no", "").strip(), data.get("fcp_no", "").strip(), wp_id))
        self._audit("workpack_updated", str(wp_id))

    def delete_workpack(self, wp_id: int) -> None:
        wp = self.get_workpack(wp_id)
        with self._db() as db:
            db.execute("DELETE FROM workpack WHERE id=?", (wp_id,))
        self._audit("workpack_deleted", wp["number"] if wp else str(wp_id))

    # ---- jobcards --------------------------------------------------------------------------
    def list_jobcards(self, wp_id: int) -> List[Dict]:
        with self._db() as db:
            jcs = [dict(r) for r in db.execute("SELECT * FROM jobcard WHERE workpack_id=? ORDER BY seq", (wp_id,))]
            for jc in jcs:
                jc["tasks"] = [dict(r) for r in db.execute("SELECT * FROM task WHERE jobcard_id=? ORDER BY pos", (jc["id"],))]
                jc["totals"] = calc.jobcard_totals(jc["tasks"])
                jc["warning_count"] = sum(len(calc.warnings(t)) for t in jc["tasks"])
        return jcs

    def get_jobcard(self, jc_id: int) -> Optional[Dict]:
        with self._db() as db:
            r = db.execute("SELECT * FROM jobcard WHERE id=?", (jc_id,)).fetchone()
            if not r:
                return None
            jc = dict(r)
            jc["flags"] = [x[0] for x in db.execute("SELECT flag FROM jobcard_flag WHERE jobcard_id=?", (jc_id,))]
            jc["drawings"] = [dict(x) for x in db.execute("SELECT number,title FROM drawing WHERE jobcard_id=? ORDER BY pos", (jc_id,))]
            jc["tasks"] = [dict(x) for x in db.execute("SELECT * FROM task WHERE jobcard_id=? ORDER BY pos", (jc_id,))]
        jc["totals"] = calc.jobcard_totals(jc["tasks"])
        return jc

    def create_jobcard(self, wp_id: int, user: str, trade: str = "") -> int:
        with self._db() as db:
            wp = db.execute("SELECT * FROM workpack WHERE id=?", (wp_id,)).fetchone()
            if not wp:
                raise ValueError("No such workpack")
            seq = (db.execute("SELECT MAX(seq) FROM jobcard WHERE workpack_id=?", (wp_id,)).fetchone()[0] or 0) + 1
            number = f"{wp['jobcard_prefix']}{seq:03d}"
            cur = db.execute(
                "INSERT INTO jobcard (workpack_id,seq,number,trade,asset,location,created_by_name,created_date,updated_at,updated_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (wp_id, seq, number, trade, wp["asset"], wp["location"], user, now()[:10], now(), user))
        self._audit("jobcard_created", number)
        return cur.lastrowid

    def duplicate_jobcard(self, jc_id: int, user: str) -> int:
        src = self.get_jobcard(jc_id)
        new_id = self.create_jobcard(src["workpack_id"], user, src["trade"])
        payload = {k: src[k] for k in ("title", "trade", "asset", "location", "additional_info",
                                       "created_by_name", "created_by_position", "created_by_signature", "ans_sh1_no", "created_date", "revision")}
        payload["flags"] = src["flags"]
        payload["drawings"] = src["drawings"]
        payload["tasks"] = [{k: t[k] for k in ("description", "qty", "norm_hours", "basis", "norm_key", "norm_uom",
                                               "norm_desc", "source", "factor", "factor_reason")} for t in src["tasks"]]
        self.save_jobcard(new_id, payload, user)
        return new_id

    def delete_jobcard(self, jc_id: int) -> None:
        jc = self.get_jobcard(jc_id)
        with self._db() as db:
            db.execute("DELETE FROM jobcard WHERE id=?", (jc_id,))
        self._audit("jobcard_deleted", jc["number"] if jc else str(jc_id))

    def save_jobcard(self, jc_id: int, data: Dict, user: str) -> Dict:
        """Replace the editable content. Existing tasks are matched by id so factor stamps survive."""
        old = self.get_jobcard(jc_id)
        if not old:
            raise ValueError("No such jobcard")
        old_tasks = {t["id"]: t for t in old["tasks"]}
        stamp = now()
        factor_events = []
        with self._db() as db:
            db.execute(
                "UPDATE jobcard SET revision=?, title=?, trade=?, asset=?, location=?, additional_info=?, "
                "created_by_name=?, created_by_position=?, created_by_signature=?, ans_sh1_no=?, created_date=?, updated_at=?, updated_by=? WHERE id=?",
                (str(data.get("revision", "A")).strip() or "A", data.get("title", "").strip(), data.get("trade", ""),
                 data.get("asset", "").strip(), data.get("location", "").strip(), data.get("additional_info", ""),
                 data.get("created_by_name", "").strip(), data.get("created_by_position", "").strip(),
                 data.get("created_by_signature", "").strip(), data.get("ans_sh1_no", "").strip(),
                 data.get("created_date", "").strip(), stamp, user, jc_id))
            db.execute("DELETE FROM jobcard_flag WHERE jobcard_id=?", (jc_id,))
            for f in data.get("flags", []):
                if f in ALL_FLAGS:
                    db.execute("INSERT INTO jobcard_flag (jobcard_id, flag) VALUES (?,?)", (jc_id, f))
            db.execute("DELETE FROM drawing WHERE jobcard_id=?", (jc_id,))
            for i, d in enumerate(x for x in data.get("drawings", []) if (x.get("number") or x.get("title"))):
                db.execute("INSERT INTO drawing (jobcard_id,pos,number,title) VALUES (?,?,?,?)",
                           (jc_id, i, d.get("number", "").strip(), d.get("title", "").strip()))
            keep = set()
            pos = 0
            for t in data.get("tasks", []):
                source = "library" if t.get("source") == "library" and t.get("norm_key") else "manual"
                factor = _num(t.get("factor"))
                factor = 1.0 if factor is None else factor
                reason = (t.get("factor_reason") or "").strip()
                row = (pos, (t.get("description") or "").strip(), _num(t.get("qty")), _num(t.get("norm_hours")),
                       (t.get("basis") or "").strip(), t.get("norm_key", "") if source == "library" else "",
                       t.get("norm_uom", "") if source == "library" else "",
                       t.get("norm_desc", "") if source == "library" else "", source, factor, reason)
                prev = old_tasks.get(t.get("id"))
                if prev:
                    changed = prev["factor"] != factor or prev["factor_reason"] != reason
                    setby, setat = (user, stamp) if changed else (prev["factor_set_by"], prev["factor_set_at"])
                    db.execute("UPDATE task SET pos=?,description=?,qty=?,norm_hours=?,basis=?,norm_key=?,norm_uom=?,"
                               "norm_desc=?,source=?,factor=?,factor_reason=?,factor_set_by=?,factor_set_at=? WHERE id=?",
                               row + (setby, setat, prev["id"]))
                    keep.add(prev["id"])
                    if prev["factor"] != factor:
                        factor_events.append(f"{old['number']} line {pos + 1}: factor {prev['factor']:g} -> {factor:g}")
                else:
                    changed = factor != 1.0
                    setby, setat = (user, stamp) if changed else ("", "")
                    cur = db.execute("INSERT INTO task (pos,description,qty,norm_hours,basis,norm_key,norm_uom,norm_desc,"
                                     "source,factor,factor_reason,jobcard_id,factor_set_by,factor_set_at) "
                                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row + (jc_id, setby, setat))
                    keep.add(cur.lastrowid)
                    if changed:
                        factor_events.append(f"{old['number']} line {pos + 1}: factor set to {factor:g}")
                pos += 1
            for tid in set(old_tasks) - keep:
                db.execute("DELETE FROM task WHERE id=?", (tid,))
        self._audit("jobcard_saved", old["number"])
        for e in factor_events:
            self._audit("factor_changed", e)
        return self.get_jobcard(jc_id)

    # ---- rollup and snapshots --------------------------------------------------------------
    def rollup(self, wp_id: int) -> List[Dict]:
        return calc.rollup(self.list_jobcards(wp_id))

    def create_snapshot(self, wp_id: int, label: str, user: str) -> int:
        lines = self.rollup(wp_id)
        with self._db() as db:
            cur = db.execute("INSERT INTO snapshot (workpack_id,label,created_by,created_at) VALUES (?,?,?,?)",
                             (wp_id, label.strip(), user, now()))
            for r in lines:
                db.execute("INSERT INTO snapshot_line (snapshot_id,trade,library_hours,manual_hours) VALUES (?,?,?,?)",
                           (cur.lastrowid, r["trade"], r["library"], r["manual"]))
        self._audit("snapshot_created", f"workpack {wp_id}: {label}")
        return cur.lastrowid

    def list_snapshots(self, wp_id: int) -> List[Dict]:
        with self._db() as db:
            snaps = [dict(r) for r in db.execute("SELECT * FROM snapshot WHERE workpack_id=? ORDER BY id DESC", (wp_id,))]
            for s in snaps:
                s["lines"] = [dict(r) for r in db.execute(
                    "SELECT trade, library_hours AS library, manual_hours AS manual FROM snapshot_line "
                    "WHERE snapshot_id=? ORDER BY trade", (s["id"],))]
                for l in s["lines"]:
                    l["total"] = l["library"] + l["manual"]
        return snaps
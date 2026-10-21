"""All database access for CTRs. Plain sqlite3, no web code. Mistakes a person can make raise ValueError with a plain message."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import calc
from .constants import (DEFAULT_ADDITIONS, DEFAULT_ASSUMPTIONS, DEFAULT_BASIS, DEFAULT_EXCLUSIONS, DEFAULT_POOLS,
                        DEFAULT_SCOPE_INTRO, DISCIPLINES, ESTIMATE_FIELDS, FIELD_LABELS, FLAGS, LONG_FIELDS, MAX_ADDITIONS,
                        MAX_CTRS, MAX_LINES, MAX_RESOURCES, MAX_TEXT, PAYMENT_TERMS, SHARED_FIELDS, SIMPLE_FIELDS)

_SHORT = 200                       # longest a one-line field may be


def _field(column: str, value) -> str:
    return _text(value, FIELD_LABELS[column], MAX_TEXT if column in LONG_FIELDS else _SHORT)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, label: str, limit: int = _SHORT) -> str:
    """Typed text, tidy: no carriage returns, no spaces round the ends. Too long is refused, never cut short."""
    s = "" if value is None else str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(s) > limit:
        raise ValueError(f"{label} is too long (the most is {limit} characters)")
    return s


def _rows(raw, label: str, limit: int) -> List[Dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(r, dict) for r in raw):
        raise ValueError(f"{label} must be a list")
    if len(raw) > limit:
        raise ValueError(f"A CTR can have at most {limit} {label.lower()}")
    return raw


def _clean_lines(raw, keep_blank: bool = False) -> List[Dict]:
    """The scope lines of a payload, checked. Blank rows are dropped, unless keep_blank, which keeps them (flagged
    '_blank') so a preview can answer row for row."""
    out = []
    for n, ln in enumerate(_rows(raw, "Lines", MAX_LINES), 1):
        try:
            row = {
                "kind": "allowance" if ln.get("kind") == "allowance" else "line",
                "description": _text(ln.get("description"), "Description", 500),
                "flag": ln.get("flag") if ln.get("flag") in FLAGS else "",
                "wbs": _text(ln.get("wbs"), "WBS", 60), "grp": _text(ln.get("grp"), "Group", 80),
                "qty": calc.number(ln.get("qty"), "Quantity"),
                "eng_norm": calc.number(ln.get("eng_norm"), "Norm"), "des_norm": calc.number(ln.get("des_norm"), "Norm"),
                "factor": calc.number(ln.get("factor"), "Factor"),
                "eng_override": calc.number(ln.get("eng_override"), "Hours"),
                "des_override": calc.number(ln.get("des_override"), "Hours"),
                "from_snapshot": 1 if ln.get("from_snapshot") else 0,
            }
        except ValueError as e:
            raise ValueError(f"Scope line {n}: {e}") from None
        if row["kind"] == "allowance" and row["qty"] is not None and row["qty"] > 1000:
            raise ValueError(f"Scope line {n}: an allowance cannot be above 1000%")
        row["_blank"] = not (row["description"] or row["grp"] or any(
            row[k] is not None for k in ("qty", "eng_norm", "des_norm", "eng_override", "des_override")))
        if keep_blank or not row["_blank"]:
            out.append(row)
    return out


def _clean_resources(raw, keep_blank: bool = False) -> List[Dict]:
    out = []
    for n, r in enumerate(_rows(raw, "Resources", MAX_RESOURCES), 1):
        try:
            source = _text(r.get("source"), "Source", 100) or calc.POOL1
            if source not in (calc.POOL1, calc.POOL2, calc.FIXED) and not (
                    source.startswith(calc.GROUP) and source[len(calc.GROUP):].strip()):
                raise ValueError("Take hours from: choose a column, a group or typed hours")
            split = calc.number(r.get("split_pct"), "Split", 0, 100)
            row = {"name": _text(r.get("name"), "Resource name", 120), "source": source,
                   "split_pct": 100.0 if split is None else split,
                   "fixed_hours": calc.number(r.get("fixed_hours"), "Hours"), "rate": calc.number(r.get("rate"), "Rate")}
        except ValueError as e:
            raise ValueError(f"Resource {n}: {e}") from None
        row["_blank"] = not (row["name"] or row["rate"] is not None or row["fixed_hours"] is not None)
        if keep_blank or not row["_blank"]:
            out.append(row)
    return out


def _clean_additions(raw, keep_blank: bool = False) -> List[Dict]:
    out = []
    for n, a in enumerate(_rows(raw, "Additions", MAX_ADDITIONS), 1):
        try:
            row = {"name": _text(a.get("name"), "Addition name", 120),
                   "unit_cost": calc.number(a.get("unit_cost"), "Cost per unit"), "units": calc.number(a.get("units"), "Units")}
        except ValueError as e:
            raise ValueError(f"Addition {n}: {e}") from None
        row["_blank"] = not (row["name"] or row["unit_cost"] is not None or row["units"] is not None)
        if keep_blank or not row["_blank"]:
            out.append(row)
    return out


def _align(rows: List[Dict], items: List[Dict], blank: Dict) -> List[Dict]:
    """Results worked out for the non-blank rows, put back in the order of all the rows, a copy of `blank` for each blank one."""
    it = iter(items)
    return [dict(blank) if r["_blank"] else next(it) for r in rows]


class Repo:
    def __init__(self, db_path: Path, audit: Callable[[str, str], None] = lambda a, d: None):
        self.db_path = Path(db_path)
        self._audit = audit

    def audit(self, action: str, detail: str = "") -> None:
        """Write an entry to the audit log, for what is done with a CTR that is not a change to its rows (a download)."""
        self._audit(action, detail)

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

    # ---- reading ---------------------------------------------------------------------------
    def get_ctr(self, ctr_id: int) -> Optional[Dict]:
        """One CTR with its scope lines, resources and additions, in order."""
        with self._db() as db:
            r = db.execute("SELECT * FROM ctr WHERE id=?", (ctr_id,)).fetchone()
            if not r:
                return None
            ctr = dict(r)
            for key, table in (("lines", "ctr_line"), ("resources", "ctr_resource"), ("additions", "ctr_addition")):
                ctr[key] = [dict(x) for x in db.execute(f"SELECT * FROM {table} WHERE ctr_id=? ORDER BY pos, id", (ctr_id,))]
        return ctr

    def list_ctrs(self, estimate_id: Optional[int] = None) -> List[Dict]:
        """Every CTR, newest first; or, given an estimate, the CTRs in it in the order they were made (the sheet order)."""
        with self._db() as db:
            if estimate_id is None:
                ids = [r[0] for r in db.execute("SELECT id FROM ctr ORDER BY id DESC")]
            else:
                ids = [r[0] for r in db.execute("SELECT id FROM ctr WHERE estimate_id=? ORDER BY id", (estimate_id,))]
        out = []
        for ctr_id in ids:
            ctr = self.get_ctr(ctr_id)
            if ctr:
                totals = calc.compute(ctr)["totals"]
                ctr["hours"], ctr["cost"] = totals["hours"], totals["cost"]
                out.append(ctr)
        return out

    # ---- estimates (the workbook) ------------------------------------------------------------
    def get_estimate(self, estimate_id: int, with_ctrs: bool = True) -> Optional[Dict]:
        """One estimate with its CTRs (each with its hours and cost) and the totals across them. `with_ctrs=False` is just
        the estimate's own details, which is quicker when that is all a page needs."""
        with self._db() as db:
            r = db.execute("SELECT * FROM estimate WHERE id=?", (estimate_id,)).fetchone()
        if not r:
            return None
        estimate = dict(r)
        if not with_ctrs:
            return estimate
        estimate["ctrs"] = self.list_ctrs(estimate_id)
        estimate["hours"] = sum(c["hours"] for c in estimate["ctrs"])
        estimate["cost"] = round(sum(c["cost"] for c in estimate["ctrs"]), 2)
        return estimate

    def list_estimates(self) -> List[Dict]:
        with self._db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM estimate ORDER BY id DESC")]
        return [e for e in (self.get_estimate(i) for i in ids) if e]

    def _estimate_values(self, data: Dict, old: Optional[Dict] = None) -> Dict[str, str]:
        values = {c: _text(data.get(c, old[c] if old else ""), label) for c, label in ESTIMATE_FIELDS}
        if not values["title"]:
            raise ValueError("Estimate name is required")
        values["jobcards_workpack"] = _text(data.get("jobcards_workpack", old["jobcards_workpack"] if old else ""),
                                            "Jobcards workpack", 60)
        return values

    def _insert_estimate(self, values: Dict[str, str], user: str) -> int:
        stamp = now()
        columns = list(values) + ["created_by", "created_at", "updated_by", "updated_at"]
        with self._db() as db:
            cur = db.execute(f"INSERT INTO estimate ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                             [*values.values(), user, stamp, user, stamp])
        return cur.lastrowid

    def create_estimate(self, data: Dict, user: str, disciplines=()) -> int:
        """A new workbook, with a CTR already in it for each of the named disciplines (from constants.DISCIPLINES)."""
        values = self._estimate_values(data)
        chosen = [d for d in DISCIPLINES if d in set(disciplines)]
        unknown = [d for d in disciplines if d not in DISCIPLINES]
        if unknown:
            raise ValueError(f"Unknown discipline: {', '.join(map(str, unknown))}")
        estimate_id = self._insert_estimate(values, user)
        self._audit("estimate_created", values["title"])
        for name in chosen:
            self.create_ctr({"title": name}, user, estimate_id=estimate_id)
        return estimate_id

    def save_estimate(self, estimate_id: int, data: Dict, user: str) -> Dict:
        """Save the workbook's own details. The project details are copied onto every CTR in it, so the sheets agree."""
        old = self.get_estimate(estimate_id, with_ctrs=False)
        if not old:
            raise ValueError("No such estimate")
        values = self._estimate_values(data, old)
        with self._db() as db:
            db.execute(f"UPDATE estimate SET {','.join(c + '=?' for c in values)}, updated_by=?, updated_at=? WHERE id=?",
                       [*values.values(), user, now(), estimate_id])
            db.execute(f"UPDATE ctr SET {','.join(c + '=?' for c in SHARED_FIELDS)} WHERE estimate_id=?",
                       [*(values[c] for c in SHARED_FIELDS), estimate_id])
        self._audit("estimate_saved", values["title"])
        return self.get_estimate(estimate_id)

    def delete_estimate(self, estimate_id: int) -> None:
        old = self.get_estimate(estimate_id, with_ctrs=False)
        with self._db() as db:
            db.execute("DELETE FROM estimate WHERE id=?", (estimate_id,))            # its CTRs go with it
        self._audit("estimate_deleted", old["title"] if old else str(estimate_id))

    # ---- writing ---------------------------------------------------------------------------
    def create_ctr(self, data: Dict, user: str, estimate_id: Optional[int] = None) -> int:
        """A new CTR in the given estimate (it takes the estimate's project details). With none given, it gets an estimate of
        its own, named after it."""
        title = _text(data.get("title"), "CTR title")
        if not title:
            raise ValueError("CTR title is required")
        values = {c: _field(c, data.get(c)) for c in SIMPLE_FIELDS}
        if estimate_id is None:
            estimate_id = self._insert_estimate(self._estimate_values({"title": title, **{c: values[c] for c in SHARED_FIELDS}}), user)
        else:
            with self._db() as db:
                estimate = db.execute("SELECT * FROM estimate WHERE id=?", (estimate_id,)).fetchone()
                count = db.execute("SELECT COUNT(*) FROM ctr WHERE estimate_id=?", (estimate_id,)).fetchone()[0]
            if not estimate:
                raise ValueError("No such estimate")
            if count >= MAX_CTRS:
                raise ValueError(f"A workbook can have at most {MAX_CTRS} CTRs")
            values.update({c: estimate[c] for c in SHARED_FIELDS})
        values["prepared_by"] = values["prepared_by"] or user          # whoever starts it, on the day they start it,
        values["ctr_date"] = values["ctr_date"] or date.today().isoformat()   # unless the form says otherwise
        values.update(title=title, scope_intro=DEFAULT_SCOPE_INTRO, assumptions=DEFAULT_ASSUMPTIONS,
                      exclusions=DEFAULT_EXCLUSIONS, basis=DEFAULT_BASIS,
                      pool1_label=DEFAULT_POOLS[0], pool2_label=DEFAULT_POOLS[1], estimate_id=estimate_id)
        stamp = now()
        columns = list(values) + ["created_by", "created_at", "updated_by", "updated_at"]
        params = list(values.values()) + [user, stamp, user, stamp]
        with self._db() as db:
            cur = db.execute(f"INSERT INTO ctr ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})", params)
            db.executemany("INSERT INTO ctr_addition (ctr_id, pos, name) VALUES (?,?,?)",
                           [(cur.lastrowid, i, name) for i, name in enumerate(DEFAULT_ADDITIONS, 1)])
        self._audit("ctr_created", title)
        return cur.lastrowid

    def save_ctr(self, ctr_id: int, data: Dict, user: str) -> Dict:
        """Save what the editor sent: the header and text, and the scope lines, resources and additions (each table is
        replaced as a whole, blank rows dropped, and a table the request leaves out is left as it was). Nothing is saved if
        anything in it is wrong."""
        old = self.get_ctr(ctr_id)
        if not old:
            raise ValueError("No such CTR")
        values = {c: _field(c, data.get(c, old[c])) for c in SIMPLE_FIELDS}
        if not values["title"]:
            raise ValueError("CTR title is required")
        values["pool1_label"] = values["pool1_label"] or DEFAULT_POOLS[0]
        values["pool2_label"] = values["pool2_label"] or DEFAULT_POOLS[1]
        terms = data.get("payment_terms", old["payment_terms"])
        values["payment_terms"] = terms if terms in PAYMENT_TERMS else old["payment_terms"]
        # a table is replaced only when the request sent it; one that is left out is left alone
        lines = _clean_lines(data["lines"]) if "lines" in data else None
        resources = _clean_resources(data["resources"]) if "resources" in data else None
        additions = _clean_additions(data["additions"]) if "additions" in data else None
        with self._db() as db:
            db.execute(f"UPDATE ctr SET {','.join(c + '=?' for c in values)}, updated_by=?, updated_at=? WHERE id=?",
                       [*values.values(), user, now(), ctr_id])
            if lines is not None:
                db.execute("DELETE FROM ctr_line WHERE ctr_id=?", (ctr_id,))
                db.executemany(
                    "INSERT INTO ctr_line (ctr_id,pos,kind,description,flag,wbs,grp,qty,eng_norm,des_norm,factor,eng_override,"
                    "des_override,from_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(ctr_id, i, l["kind"], l["description"], l["flag"], l["wbs"], l["grp"], l["qty"], l["eng_norm"], l["des_norm"],
                      l["factor"], l["eng_override"], l["des_override"], l["from_snapshot"]) for i, l in enumerate(lines, 1)])
            if resources is not None:
                db.execute("DELETE FROM ctr_resource WHERE ctr_id=?", (ctr_id,))
                db.executemany(
                    "INSERT INTO ctr_resource (ctr_id,pos,name,source,split_pct,fixed_hours,rate) VALUES (?,?,?,?,?,?,?)",
                    [(ctr_id, i, r["name"], r["source"], r["split_pct"], r["fixed_hours"], r["rate"]) for i, r in enumerate(resources, 1)])
            if additions is not None:
                db.execute("DELETE FROM ctr_addition WHERE ctr_id=?", (ctr_id,))
                db.executemany(
                    "INSERT INTO ctr_addition (ctr_id,pos,name,unit_cost,units) VALUES (?,?,?,?,?)",
                    [(ctr_id, i, a["name"], a["unit_cost"], a["units"]) for i, a in enumerate(additions, 1)])
        self._audit("ctr_saved", values["title"])
        return self.get_ctr(ctr_id)

    def preview(self, ctr_id: int, data: Dict) -> Dict:
        """What a CTR would show if `data` were saved, without saving: the same checks, the same arithmetic. The answers for
        lines, resources and additions come back one for each row sent, blank rows included, so a page can match them up."""
        old = self.get_ctr(ctr_id)
        if not old:
            raise ValueError("No such CTR")
        def rows(key, clean):                    # what was sent, or what is stored when it was not sent
            return clean(data[key], True) if key in data else [dict(r, _blank=False) for r in old[key]]

        lines, resources, additions = rows("lines", _clean_lines), rows("resources", _clean_resources), rows("additions", _clean_additions)
        old.update(lines=[r for r in lines if not r["_blank"]], resources=[r for r in resources if not r["_blank"]],
                   additions=[r for r in additions if not r["_blank"]])
        for c in ("pool1_label", "pool2_label"):
            old[c] = _field(c, data.get(c, old[c])) or DEFAULT_POOLS[0 if c == "pool1_label" else 1]
        out = calc.compute(old)
        out["lines"] = _align(lines, out["lines"], {"eng": 0, "des": 0})
        out["resources"] = _align(resources, out["resources"], {"name": "", "source_hours": None, "hours": 0, "cost": 0.0})
        out["additions"] = _align(additions, out["additions"], {"name": "", "cost": 0.0})
        return out

    def delete_ctr(self, ctr_id: int) -> None:
        ctr = self.get_ctr(ctr_id)
        with self._db() as db:
            db.execute("DELETE FROM ctr WHERE id=?", (ctr_id,))
        self._audit("ctr_deleted", ctr["title"] if ctr else str(ctr_id))

    def duplicate_ctr(self, ctr_id: int, user: str) -> int:
        """A copy of a CTR (with its lines, resources and additions) under the title '<title> (copy)'."""
        old = self.get_ctr(ctr_id)
        if not old:
            raise ValueError("No such CTR")
        new_id = self.create_ctr({"title": f"{old['title']} (copy)"}, user, estimate_id=old["estimate_id"])
        data = {c: old[c] for c in SIMPLE_FIELDS}
        data.update(title=f"{old['title']} (copy)", payment_terms=old["payment_terms"], lines=old["lines"],
                    resources=old["resources"], additions=old["additions"])
        self.save_ctr(new_id, data, user)
        with self._db() as db:
            db.execute("UPDATE ctr SET source_snapshot_id=?, source_text=? WHERE id=?",
                       (old["source_snapshot_id"], old["source_text"], new_id))
        self._audit("ctr_duplicated", old["title"])
        return new_id

    def import_snapshot(self, ctr_id: int, snapshot: Dict, user: str, only: Optional[List[str]] = None,
                        with_resources: bool = False) -> int:
        """Bring the hours by trade of a jobcards snapshot (as the jobcards.hours service gives it) in as scope lines, one per
        trade, each with the trade as its group. Lines from an earlier import are replaced; lines typed by hand stay.
        With `only` (a list of trades), just those trades are brought in and only their earlier lines are replaced, so other
        trades imported before are kept. With `with_resources`, each trade that no resource takes yet gets one, named after
        it and taking all of it (what the editor's "add a resource for each trade" button does), so the hours show at once.
        Returns how many lines were added."""
        if not self.get_ctr(ctr_id):
            raise ValueError("No such CTR")
        wanted = None if only is None else list(only)
        trades = [l for l in snapshot.get("lines", []) if l.get("total") and (wanted is None or l.get("trade") in wanted)]
        if not trades:
            raise ValueError("That snapshot has no hours in it" if wanted is None
                             else f"That snapshot has no {', '.join(wanted)} hours in it")
        label = (snapshot.get("label") or "").strip() or "Snapshot"
        source = f"{snapshot.get('workpack_number', '')} - {label} ({str(snapshot.get('created_at', ''))[:10]})".strip(" -")
        with self._db() as db:
            if wanted is None:
                db.execute("DELETE FROM ctr_line WHERE ctr_id=? AND from_snapshot=1", (ctr_id,))
            else:
                db.executemany("DELETE FROM ctr_line WHERE ctr_id=? AND from_snapshot=1 AND grp=?", [(ctr_id, t) for t in wanted])
            pos = db.execute("SELECT COALESCE(MAX(pos), 0) FROM ctr_line WHERE ctr_id=?", (ctr_id,)).fetchone()[0]
            db.executemany(
                "INSERT INTO ctr_line (ctr_id,pos,kind,description,grp,eng_override,from_snapshot) VALUES (?,?,'line',?,?,?,1)",
                [(ctr_id, pos + i, t["trade"], t["trade"], t["total"]) for i, t in enumerate(trades, 1)])
            if with_resources:
                taken = {r[0] for r in db.execute("SELECT source FROM ctr_resource WHERE ctr_id=?", (ctr_id,))}
                at = db.execute("SELECT COALESCE(MAX(pos), 0) FROM ctr_resource WHERE ctr_id=?", (ctr_id,)).fetchone()[0]
                for t in trades:
                    if calc.GROUP + t["trade"] not in taken:
                        at += 1
                        db.execute("INSERT INTO ctr_resource (ctr_id,pos,name,source,split_pct) VALUES (?,?,?,?,100)",
                                   (ctr_id, at, t["trade"], calc.GROUP + t["trade"]))
            db.execute("UPDATE ctr SET source_snapshot_id=?, source_text=?, updated_by=?, updated_at=? WHERE id=?",
                       (snapshot.get("id"), source, user, now(), ctr_id))
        self._audit("ctr_hours_imported", f"CTR {ctr_id} from {source}")
        return len(trades)

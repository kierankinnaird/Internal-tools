"""Norm lookup logic. No web code in here, so it runs the same in any host."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_DB = Path(__file__).parent / "data" / "norms.sqlite"
MAX_LIMIT = 500

# A word counts if it is in the line's own description (row, column, unit, key). The item title is only used
# for an item none of whose lines mention the word, so "triple" does not drag in the "pairs" lines that happen
# to share a title like "(PAIRS & TRIPLES)".
_WORD_CLAUSE = (
    "((' ' || line_hay) LIKE ? ESCAPE '\\' OR ((' ' || item_hay) LIKE ? ESCAPE '\\' AND NOT EXISTS "
    "(SELECT 1 FROM norms n2 WHERE n2.item_id = norms.item_id AND (' ' || n2.line_hay) LIKE ? ESCAPE '\\')))"
)


_STOP = {"the", "and", "for", "with", "from", "out", "all", "new", "old", "are", "was", "this", "that", "into",
         "onto", "any", "per", "etc", "as", "to", "of", "in", "on", "at", "by", "or", "an", "a", "is", "be", "it"}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def suggest_tokens(text: str) -> List[str]:
    """Meaningful words from free text: lower-cased, no stop words, light stemming, no repeats."""
    out: List[str] = []
    for raw in re.findall(r"[a-z0-9][a-z0-9./\"-]*", text.lower()):
        raw = raw.strip("./-")
        if not raw or raw in _STOP or (len(raw) < 2 and not raw.isdigit()):
            continue
        t = _stem(raw)
        if t not in out:
            out.append(t)
    return out[:8]

@dataclass
class SearchResult:
    total: int
    rows: List[Dict]


def _like(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"% {escaped}%"   # match at the start of a word: "6" finds 6" but not 16"


class NormsService:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db

    def disciplines(self) -> List[str]:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT discipline FROM norms GROUP BY discipline ORDER BY MIN(ord)")]

    def items(self, discipline: Optional[str] = None) -> List[Dict]:
        sql = "SELECT item_id, discipline, item_no, item FROM norms"
        args: list = []
        if discipline:
            sql += " WHERE discipline = ?"
            args.append(discipline)
        sql += " GROUP BY item_id ORDER BY MIN(ord)"
        with self._db() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def search(self, query: str = "", discipline: Optional[str] = None, item_id: Optional[str] = None,
               usable_only: bool = True, limit: int = 200) -> SearchResult:
        limit = max(1, min(int(limit), MAX_LIMIT))
        where, args = [], []
        for token in query.lower().split():
            like = _like(token)
            where.append(_WORD_CLAUSE)
            args.extend([like, like, like])
        if discipline:
            where.append("discipline = ?")
            args.append(discipline)
        if item_id:
            where.append("item_id = ?")
            args.append(item_id)
        if usable_only:
            where.append("status = 'OK'")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._db() as db:
            total = db.execute(f"SELECT COUNT(*) FROM norms{clause}", args).fetchone()[0]
            rows = db.execute(
                "SELECT key, discipline, item_id, item_no, item, row_desc, col_desc, uom, hours, status, source_cell "
                f"FROM norms{clause} ORDER BY ord LIMIT ?", args + [limit]
            ).fetchall()
        return SearchResult(total=total, rows=[dict(r) for r in rows])

    def suggest(self, text: str, limit: int = 5) -> SearchResult:
        """Norms that fit free text such as a task description. Unlike search(), words are not all required: lines are ranked by how many of the words they contain, and need at least two (one if only one was given)."""
        tokens = suggest_tokens(text)
        if not tokens:
            return SearchResult(0, [])
        need = 1 if len(tokens) == 1 else 2
        score_parts, args = [], []
        for t in tokens:
            like = _like(t)
            score_parts.append("(CASE WHEN " + _WORD_CLAUSE + " THEN 1 ELSE 0 END)")
            args.extend([like, like, like])
        score = " + ".join(score_parts)
        limit = max(1, min(int(limit), 20))
        sql = ("SELECT * FROM (SELECT key, discipline, item_id, item_no, item, row_desc, col_desc, uom, hours, status, "
               f"source_cell, ord, ({score}) AS score FROM norms WHERE status = 'OK') WHERE score >= ? "
               "ORDER BY score DESC, ord LIMIT ?")
        with self._db() as db:
            rows = [dict(r) for r in db.execute(sql, args + [need, limit])]
        return SearchResult(total=len(rows), rows=rows)

    def get(self, key: str) -> Optional[Dict]:
        with self._db() as db:
            r = db.execute("SELECT * FROM norms WHERE key = ?", (key,)).fetchone()
        return dict(r) if r else None
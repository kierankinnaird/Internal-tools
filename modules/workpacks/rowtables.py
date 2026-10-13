"""The tables of rows under a certificate: lines (SL1, MP1), joints (JI1) and tags (EE12)."""
from __future__ import annotations

from typing import Dict, List, Optional

from .engine import fill_workpack as F
from .fields import ROW_KIND_BY_FORM, ROW_KINDS

MAX_ROWS = 1000      # per table; far more than any form holds, and a guard against a runaway paste
BLANK_ROWS = 5       # empty rows offered at the foot of the table

TITLES = {"line": "Lines", "joint": "Joints", "tag": "Tags"}
NOUNS = {"line": ("line", "lines"), "joint": ("joint", "joints"), "tag": ("tag", "tags")}
NOTES = {"tag": "In the form, tags are listed under the description of tests. A line containing only [TAGS] in "
                "the description marks where they go; without it the tags follow the text."}

_ENGINE_HINTS = {label: hint for cols in (F.LINE_COLUMNS, F.JOINT_COLUMNS, F.TAG_COLUMNS) for _, label, hint in cols}


def kind_for(form: str) -> Optional[str]:
    """'line', 'joint' or 'tag', or None for a form with no table."""
    return ROW_KIND_BY_FORM.get(form)


def columns(kind: str) -> List[Dict]:
    return [{"name": name, "label": label, "hint": _ENGINE_HINTS.get(label, "")} for name, label in ROW_KINDS[kind][1]]


def count_text(kind: str, n: int) -> str:
    one, many = NOUNS[kind]
    return f"{n} {one if n == 1 else many}"


def parse_rows(form, names: List[str]) -> List[Dict]:
    """The rows posted from the grid: one list of values per column, all the same length.

    A post without the table marker, or with lists of different lengths, is refused whole, so a broken or
    partial post can never wipe or scramble a certificate's rows."""
    if form.get("table") != "1":
        raise ValueError("Nothing was saved because the table data was missing. Please try again.")
    lists = {n: form.getlist(n) for n in names}
    lengths = {len(v) for v in lists.values()}
    if len(lengths) != 1:
        raise ValueError("Nothing was saved because the table data was incomplete. Please try again.")
    count = lengths.pop()
    if count > MAX_ROWS:
        raise ValueError(f"A table can have at most {MAX_ROWS} rows")
    return [{n: lists[n][i] for n in names} for i in range(count)]
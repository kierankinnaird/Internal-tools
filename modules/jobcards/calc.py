"""Hours maths and checks. Pure functions, no web or database code."""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional


def round_up_hours(hours: float) -> float:
    """Up to the next whole hour: 2.5 becomes 3, and a whole number stays as it is. Rounding to 6 places first stops
    floating point noise (11.000000000000002) from pushing an exact figure up an extra hour."""
    return float(math.ceil(round(hours, 6)))


def tidy_hours(value) -> float:
    """Hours for a file or a report: whole hours as whole numbers. Anything with a fraction (a figure saved before hours
    were rounded up) is kept as it was, to two places, never silently rounded."""
    v = float(value or 0)
    return int(v) if v.is_integer() else round(v, 2)


def format_hours(value) -> str:
    """Hours for a page: '6' for six hours, and '4.50' only for an old figure with a fraction."""
    v = tidy_hours(value)
    return str(v) if isinstance(v, int) else f"{v:.2f}"


def line_hours(qty: Optional[float], norm: Optional[float], factor: Optional[float]) -> float:
    """QTY x NORM x FACTOR, rounded up to the next whole hour. Each task is rounded on its own, and the totals add up
    the rounded figures. A missing qty/norm counts as nothing yet; a missing factor as 1."""
    if qty is None or norm is None:
        return 0.0
    return round_up_hours(qty * norm * (1.0 if factor is None else factor))


def warnings(task: Dict) -> List[str]:
    out = []
    if task.get("kind") == "note":          # a heading carries no hours, so there is nothing on it to check
        return out
    has_content = task.get("description") or task.get("qty") is not None or task.get("norm_hours") is not None
    if not has_content:
        return out
    if task.get("qty") is None:
        out.append("No quantity")
    if task.get("norm_hours") is None:
        out.append("No norm")
    if (task.get("factor") or 1) != 1 and not (task.get("factor_reason") or "").strip():
        out.append("Factor changed without a reason")
    if task.get("source") == "manual" and task.get("norm_hours") is not None and not (task.get("basis") or "").strip():
        out.append("Manual norm without a basis")
    return out


def jobcard_totals(tasks: Iterable[Dict]) -> Dict[str, float]:
    lib = man = 0.0
    for t in tasks:
        if t.get("kind") == "note":
            continue
        h = line_hours(t.get("qty"), t.get("norm_hours"), t.get("factor"))
        if t.get("source") == "library":
            lib += h
        else:
            man += h
    return {"library": lib, "manual": man, "total": lib + man}


def rollup(jobcards: Iterable[Dict]) -> List[Dict]:
    """Hours by trade across jobcards. Each jobcard dict needs 'trade' and 'tasks'."""
    by: Dict[str, Dict[str, float]] = {}
    for jc in jobcards:
        trade = jc.get("trade") or "(no trade)"
        t = jobcard_totals(jc["tasks"])
        r = by.setdefault(trade, {"library": 0.0, "manual": 0.0})
        r["library"] += t["library"]
        r["manual"] += t["manual"]
    return [{"trade": k, "library": v["library"], "manual": v["manual"], "total": v["library"] + v["manual"]}
            for k, v in sorted(by.items())]
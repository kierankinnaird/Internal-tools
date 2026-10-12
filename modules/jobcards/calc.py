"""Hours maths and checks. Pure functions, no web or database code."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional


def line_hours(qty: Optional[float], norm: Optional[float], factor: Optional[float]) -> float:
    """QTY x NORM x FACTOR. A missing qty/norm counts as nothing yet; a missing factor as 1."""
    if qty is None or norm is None:
        return 0.0
    return qty * norm * (1.0 if factor is None else factor)


def warnings(task: Dict) -> List[str]:
    out = []
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
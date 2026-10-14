"""The CTR's arithmetic and checks. Pure functions: no web or database code.

How hours flow, so the page, the Excel file and the tests all agree:
  * a scope line gives hours in two columns (by default "Eng" and "Design"): quantity x norm x factor, rounded up to a
    whole hour, unless hours were typed on the line, which are used instead (also rounded up);
  * an "allowance" line is a percentage of every other line's hours (progress, meetings, IDC...), added to the first column;
  * a resource takes a typed percentage split of the hours of one source: a whole column, a named group of lines (a
    trade, say), or hours typed in. Resources on one source are shared out in whole hours that add back up to the
    source's hours (largest remainder), so 3 hours at 60/40 is 2 and 1, never 2 and 2;
  * rates are typed in; cost is hours x rate.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

TOLERANCE = 0.01            # how far from 100% a set of splits may be before it is flagged
POOL1, POOL2, FIXED = "pool1", "pool2", "fixed"
GROUP = "group:"


def round_up_hours(hours: float) -> int:
    """Up to the next whole hour. Rounded to 6 places first so floating point noise (11.000000000000002) cannot push an
    exact figure up an extra hour."""
    return int(math.ceil(round(hours, 6)))


def tidy(value) -> float:
    """A figure for a page or file: whole numbers as whole numbers, anything else to two places."""
    v = float(value or 0)
    return int(v) if v.is_integer() else round(v, 2)


def number(value, label: str, low: Optional[float] = 0, high: Optional[float] = None) -> Optional[float]:
    """A typed number: blank is None. A pound sign, thousands commas and a percent sign are ignored. Anything else that
    is not a finite number is refused with a message naming the field."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value).strip().replace("£", "").replace(",", "").rstrip("%").strip()
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            raise ValueError(f"{label} must be a number") from None
    if not math.isfinite(v):
        raise ValueError(f"{label} must be a number")
    if low is not None and v < low:
        raise ValueError(f"{label} cannot be below {low:g}")
    if high is not None and v > high:
        raise ValueError(f"{label} cannot be above {high:g}")
    return v


def share_out(total: float, splits: List[float]) -> List[int]:
    """Share `total` hours between splits (percentages) in whole hours. The shares add up to the rounded sum of the exact
    shares: to `total` itself when the splits come to 100%. Whole parts first, then the left-over hours go to the largest
    fractions (first listed wins a tie)."""
    raw = [round(total * s / 100.0, 6) for s in splits]
    parts = [math.floor(r) for r in raw]
    target = math.floor(round(sum(raw), 6) + 0.5)
    left = target - sum(parts)
    for i in sorted(range(len(raw)), key=lambda k: (-(raw[k] - parts[k]), k))[:max(left, 0)]:
        parts[i] += 1
    return parts


def source_label(source: str, labels) -> str:
    if source == POOL1:
        return f"{labels[0]} hours"
    if source == POOL2:
        return f"{labels[1]} hours"
    if source.startswith(GROUP):
        return f"“{source[len(GROUP):]}” hours"
    return "typed hours"


def _pool(override, qty, norm, factor) -> int:
    if override is not None:
        return round_up_hours(override)
    if qty is None or norm is None:
        return 0
    return round_up_hours(qty * norm * (1.0 if factor is None else factor))


def line_results(lines: List[Dict]) -> List[Dict]:
    """The hours of each scope line, in order: [{'eng': n, 'des': n}]."""
    out = []
    for ln in lines:
        if ln.get("kind") == "allowance":
            out.append({"eng": 0, "des": 0})
        else:
            out.append({"eng": _pool(ln.get("eng_override"), ln.get("qty"), ln.get("eng_norm"), ln.get("factor")),
                        "des": _pool(ln.get("des_override"), ln.get("qty"), ln.get("des_norm"), ln.get("factor"))})
    base = sum(r["eng"] + r["des"] for r in out)
    for ln, r in zip(lines, out):
        if ln.get("kind") != "allowance":
            continue
        pct = ln.get("qty")
        if ln.get("eng_override") is not None:
            r["eng"] = round_up_hours(ln["eng_override"])
        elif pct is not None:
            r["eng"] = round_up_hours(base * pct / 100.0)
        if ln.get("des_override") is not None:
            r["des"] = round_up_hours(ln["des_override"])
    return out


def groups_in(lines: Iterable[Dict]) -> List[str]:
    seen: List[str] = []
    for ln in lines:
        g = (ln.get("grp") or "").strip()
        if g and g not in seen:
            seen.append(g)
    return seen


def compute(ctr: Dict) -> Dict:
    """Everything the page and the file show, worked out from a CTR (lines, resources, additions, the two column labels).
    The result also carries 'warnings': things to look at, never reasons to refuse."""
    labels = (ctr.get("pool1_label") or "Eng", ctr.get("pool2_label") or "Design")
    lines, resources, additions = ctr.get("lines", []), ctr.get("resources", []), ctr.get("additions", [])
    results = line_results(lines)
    pools = {POOL1: sum(r["eng"] for r in results), POOL2: sum(r["des"] for r in results)}
    groups = {g: sum(r["eng"] + r["des"] for ln, r in zip(lines, results) if (ln.get("grp") or "").strip() == g)
              for g in groups_in(lines)}

    def hours_of(source: str) -> int:
        if source == POOL1 or source == POOL2:
            return pools[source]
        if source.startswith(GROUP):
            return groups.get(source[len(GROUP):], 0)
        return 0

    # resources: shared out per source, in whole hours
    out_res = [{"name": r.get("name", ""), "source": r.get("source") or POOL1, "split_pct": r.get("split_pct"),
                "rate": r.get("rate"), "source_hours": None, "hours": 0, "cost": 0.0} for r in resources]
    by_source: Dict[str, List[int]] = {}
    for i, r in enumerate(out_res):
        if r["source"] == FIXED:
            r["hours"] = round_up_hours(resources[i].get("fixed_hours") or 0)
        else:
            by_source.setdefault(r["source"], []).append(i)
    for source, members in by_source.items():
        total = hours_of(source)
        splits = [100.0 if out_res[i]["split_pct"] is None else out_res[i]["split_pct"] for i in members]
        for i, h in zip(members, share_out(total, splits)):
            out_res[i]["hours"], out_res[i]["source_hours"] = h, total
    for r in out_res:
        r["cost"] = round(r["hours"] * r["rate"], 2) if r["rate"] is not None else 0.0
    out_add = [{"name": a.get("name", ""), "unit_cost": a.get("unit_cost"), "units": a.get("units"),
                "cost": round((a.get("unit_cost") or 0) * (a.get("units") or 0), 2)} for a in additions]

    resources_cost = round(sum(r["cost"] for r in out_res), 2)
    additions_cost = round(sum(a["cost"] for a in out_add), 2)
    options = [{"value": POOL1, "label": f"All {labels[0]} hours", "hours": pools[POOL1]},
               {"value": POOL2, "label": f"All {labels[1]} hours", "hours": pools[POOL2]}]
    options += [{"value": GROUP + g, "label": f"“{g}” lines", "hours": h} for g, h in groups.items()]
    options.append({"value": FIXED, "label": "Hours typed in", "hours": None})
    return {
        "lines": results, "pools": pools, "groups": groups, "resources": out_res, "additions": out_add,
        "options": options, "labels": list(labels),
        "totals": {"hours": sum(r["hours"] for r in out_res), "line_hours": pools[POOL1] + pools[POOL2],
                   "resources_cost": resources_cost, "additions_cost": additions_cost,
                   "cost": round(resources_cost + additions_cost, 2)},
        "warnings": warnings(lines, results, out_res, by_source, groups, labels),
    }


def _names(items: List[str], limit: int = 4) -> str:
    items = [i for i in items if i] or ["(unnamed)"]
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def warnings(lines, results, resources, by_source, groups, labels) -> List[str]:
    out: List[str] = []
    used = set(by_source)
    for source, members in by_source.items():
        total = sum(100.0 if resources[i]["split_pct"] is None else resources[i]["split_pct"] for i in members)
        if abs(total - 100.0) > TOLERANCE:
            out.append(f"Splits taking the {source_label(source, labels)} add up to {total:g}%, not 100%.")
        if source.startswith(GROUP) and source[len(GROUP):] not in groups:
            out.append(f"{_names([resources[i]['name'] for i in members])} take hours from “{source[len(GROUP):]}”, "
                       "which no scope line uses.")
    # hours nobody takes, and hours taken twice
    missed = {POOL1: [], POOL2: []}
    twice = []
    for n, (ln, r) in enumerate(zip(lines, results), 1):
        g = (ln.get("grp") or "").strip()
        in_group = bool(g) and GROUP + g in used
        name = (ln.get("description") or g or f"line {n}").strip()
        for pool, hours in ((POOL1, r["eng"]), (POOL2, r["des"])):
            if hours and pool not in used and not in_group:
                missed[pool].append(name)
            if hours and pool in used and in_group and name not in twice:
                twice.append(name)
    for pool, names in missed.items():
        if names:
            out.append(f"No resource takes the {labels[0 if pool == POOL1 else 1]} hours of: {_names(names)}.")
    if twice:
        out.append(f"These hours are shared out twice, once as a whole column and once as a group: {_names(twice)}.")
    unrated = [r["name"] for r in resources if r["hours"] and r["rate"] is None]
    if unrated:
        out.append(f"No rate yet for: {_names(unrated)}.")
    return out

"""Which certificate fields matter for which form.

The engine decides what each form takes (its BODY_FIELDS table), so this reads the engine's own table instead of
keeping a second copy that could drift. Fields a form does not use are still kept, in a separate section,
so nothing a person typed is ever hidden or lost.
"""
from __future__ import annotations

from typing import Dict, List

from .engine import fill_workpack as F
from .fields import CERTIFICATE_COLUMNS, CERTIFICATE_FIELDS

HEADER_COLUMNS = ["hdr_title", "hdr_site", "hdr_mc1_no"]     # this certificate's header only
FILE_COLUMNS = ["filename", "folder"]                        # where and under what name the form is written
TEXTAREAS = {"description", "scope", "procedure", "ee12_description"}

_LABELS = dict(CERTIFICATE_FIELDS)
_ENGINE_HINTS = {label: hint for _, label, hint in F.CERT_COLUMNS}


def hint(column: str) -> str:
    """The engine's own one-line explanation of a column."""
    return _ENGINE_HINTS.get(_LABELS[column], "")


def relevant_columns(form: str) -> List[str]:
    """The certificate fields this form's body (or header, for PL1) uses, in the usual order."""
    used = {key for key, *_ in F.BODY_FIELDS.get(form, [])}
    used |= {key for key, *_ in F.BODY_REPLACE.get(form, [])}
    if form == "EE12":
        used.add("ee12_description")                         # the tests text; tags come from the table rows
    if form.startswith("PL1"):
        used |= {"punch_no", "discipline"}
    return [c for c in CERTIFICATE_COLUMNS if c in used and c not in HEADER_COLUMNS + FILE_COLUMNS]


# Slots the engine fills with a project-level value (shown in place, changed on the workpack page): key -> workpack column
WORKPACK_KEYS = {"project_no": "project_no", "workpack": "workpack_no", "sh1": "sh1_no", "jre": "jre",
                 "cchp_title": "cchp_title", "handover_title": "handover_title",
                 "handover_includes": "handover_includes", "handover_excludes": "handover_excludes"}
# Where the template's own wording is clearer than the engine's label for the slot.
LABEL_OVERRIDES = {"sl1a": "Scope of test: SL1A request no", "ee12_description": "Description of tests carried out"}
# Blank = the workpack's value, so these show it as a placeholder.
INHERITED = ("location", "system", "subsystem")


def layout(form: str) -> List[dict]:
    """The form's fillable cells where the blank template has them, as tables of rows of cells.

    Read from the engine's slot table (table, row, column of every cell it writes), so the page follows the template
    and cannot drift from what a fill really does. A cell is a `pair` (label, then value), a `wide` one (label above a
    value that spans the form) or a `blank` filler; `start` and `span` are in label/value pairs.
    """
    slots = [*F.BODY_FIELDS.get(form, []), *F.BODY_REPLACE.get(form, [])]
    grouped: Dict[int, Dict[int, list]] = {}
    for slot in slots:
        key, (table, row, col), (_, label_col, text) = slot[0], slot[1], slot[2]
        grouped.setdefault(table, {}).setdefault(row, []).append((col, key, label_col, text))
    tables = []
    for table in sorted(grouped):
        rows = grouped[table]
        columns = max([2] + [sum(1 for c, _, lc, _ in cells if not (c == 0 and lc == 0)) for cells in rows.values()])
        out = []
        for row in sorted(rows):
            cells = sorted(rows[row])
            pairs = [c for c in cells if not (c[0] == 0 and c[2] == 0)]
            line, used = [], 0
            for col, key, label_col, text in cells:
                label = LABEL_OVERRIDES.get(key, text)
                if col == 0 and label_col == 0:
                    line.append({"key": key, "label": label, "kind": "wide"})
                    continue
                index = pairs.index((col, key, label_col, text))
                if len(pairs) == 1:       # a lone cell fills the row, unless the template keeps it in the right-hand half
                    start, span = (columns - 1, 1) if col >= 2 else (0, columns)
                else:
                    start, span = index, 1
                if start > used:
                    line.append({"kind": "blank", "start": used, "span": start - used})
                line.append({"key": key, "label": label, "kind": "pair", "start": start, "span": span})
                used = start + span
            if used and used < columns:
                line.append({"kind": "blank", "start": used, "span": columns - used})
            out.append(line)
        tables.append({"columns": columns, "rows": out})
    return tables


def placed(form: str) -> set:
    """Every slot key the form's layout shows."""
    return {cell["key"] for table in layout(form) for row in table["rows"] for cell in row if "key" in cell}


def unplaced(form: str) -> List[str]:
    """Certificate fields this form uses that the template has no cell for in its body (PL1's header ones, EE12's tests text)."""
    shown = placed(form)
    return [c for c in relevant_columns(form) if c not in shown]


def sections(form: str) -> Dict[str, List[str]]:
    """Every certificate column, exactly once: details for this form, header, output file, and the rest."""
    details = relevant_columns(form)
    shown = set(details) | set(HEADER_COLUMNS) | set(FILE_COLUMNS)
    return {"details": details, "header": list(HEADER_COLUMNS), "files": list(FILE_COLUMNS),
            "other": [c for c in CERTIFICATE_COLUMNS if c not in shown]}
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


def sections(form: str) -> Dict[str, List[str]]:
    """Every certificate column, exactly once: details for this form, header, output file, and the rest."""
    details = relevant_columns(form)
    shown = set(details) | set(HEADER_COLUMNS) | set(FILE_COLUMNS)
    return {"details": details, "header": list(HEADER_COLUMNS), "files": list(FILE_COLUMNS),
            "other": [c for c in CERTIFICATE_COLUMNS if c not in shown]}
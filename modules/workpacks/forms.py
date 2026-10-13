"""Which form codes can be chosen when adding a certificate."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .engine import fill_workpack as F


def _natural(code: str):
    """EE2 before EE10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", code)]


def form_codes(folder: Path) -> List[str]:
    """The forms the tool has special handling for, plus a code for each blank template in the folder.

    A template's code is the start of its file name: 'AS1.docx' is AS1, 'PL1 A - FCP Projects.docx' is PL1 A.
    The engine accepts any code that starts a template's file name, so a code typed by hand still works.
    """
    codes = set(F.SECTION)
    folder = Path(folder)
    if folder.is_dir():
        for path in folder.rglob("*.docx"):
            if path.name.startswith("~$"):
                continue
            head = path.stem.split(" - ")[0].strip()
            if head and " " not in head:
                codes.add(head)
    return sorted(codes, key=_natural)
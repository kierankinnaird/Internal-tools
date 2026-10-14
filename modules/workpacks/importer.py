"""Brings an existing Workpack Tools input workbook (.xlsx) in as a new workpack.

The engine's own reader does the reading and the checking, so a workbook is accepted or refused exactly as the old
tool would have done. This module adds what a web upload needs on top: size limits, a look inside the zip before it
is opened, our own limits, and all-or-nothing saving. Import only: nothing here writes Excel.
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .engine import fill_workpack as F
from .fields import CERTIFICATE_FIELDS, ROW_KINDS, WORKPACK_FIELDS
from .fill import _unsafe
from .repo import Repo
from .rowtables import MAX_ROWS

MAX_BYTES = 5 * 1024 * 1024          # an input workbook is a few tens of kilobytes; this is a guard
MAX_UNPACKED = 50 * 1024 * 1024      # what the zip may expand to (a guard against zip bombs)
MAX_CERTIFICATES = 500
MAX_SHOWN = 20                       # problems listed on screen; the rest are counted

# engine data key -> (row kind, engine columns)
TABLES = {"lines": ("line", F.LINE_COLUMNS), "joints": ("joint", F.JOINT_COLUMNS), "tags": ("tag", F.TAG_COLUMNS)}


class ImportProblem(ValueError):
    """The workbook was refused. .problems has one plain sentence per problem."""

    def __init__(self, problems: List[str]):
        self.problems = problems[:MAX_SHOWN] + ([f"... and {len(problems) - MAX_SHOWN} more"] if len(problems) > MAX_SHOWN else [])
        super().__init__(problems[0] if problems else "The workbook could not be imported")


@dataclass
class Parsed:
    workpack: Dict[str, str]
    certificates: List[Dict] = field(default_factory=list)      # each: cert_id, form, columns..., rows {kind: [..]}

    @property
    def row_count(self) -> int:
        return sum(len(r) for c in self.certificates for r in c["rows"].values())


@dataclass
class ImportResult:
    wp_id: int
    certificates: int
    rows: int


def _map(engine_columns, ours) -> Dict[str, str]:
    """engine key -> our database column, joined on the label text both sides use."""
    by_label = {label: column for column, label in ours}
    return {key: by_label[label] for key, label, *_ in engine_columns if label in by_label}


PROJECT_MAP = _map(F.PROJECT_FIELDS, WORKPACK_FIELDS)
CERT_MAP = _map(F.CERT_COLUMNS, CERTIFICATE_FIELDS)
ROW_MAPS = {data_key: _map(cols, ROW_KINDS[kind][1]) for data_key, (kind, cols) in TABLES.items()}


def check_upload(data: bytes, filename: str) -> None:
    """Refuse anything that is plainly not a reasonable .xlsx, before it is opened."""
    if not filename.lower().endswith(".xlsx"):
        raise ImportProblem(["Choose an Excel workbook saved as .xlsx"])
    if not data:
        raise ImportProblem(["That file is empty"])
    if len(data) > MAX_BYTES:
        limit = f"{MAX_BYTES // (1024 * 1024)} MB" if MAX_BYTES >= 1024 * 1024 else f"{MAX_BYTES // 1024} KB"
        raise ImportProblem([f"That file is larger than {limit}, which is far more than a workpack workbook needs"])
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "xl/workbook.xml" not in names:
                raise zipfile.BadZipFile("not a workbook")
            if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
                raise ImportProblem(["That workbook expands to an unreasonable size, so it was not opened"])
    except zipfile.BadZipFile:
        raise ImportProblem(["That is not a readable .xlsx workbook"])


def _engine_problems(message: str) -> List[str]:
    """The engine's multi-line message as separate sentences."""
    lines = [ln.strip() for ln in message.split("\n")]
    out = [ln[1:].strip() if ln.startswith("-") else ln for ln in lines if ln]
    return [ln for ln in out if not ln.lower().startswith("problems in the input workbook")] or out


def parse_workbook(data: bytes, filename: str) -> Parsed:
    """Read and check a workbook. Raises ImportProblem listing everything wrong; saves nothing."""
    check_upload(data, filename)
    with tempfile.TemporaryDirectory(prefix="wp_import_") as tmp:
        path = Path(tmp) / "input.xlsx"
        path.write_bytes(data)
        try:
            sheet = F.read_sheet(str(path))
        except F.FillError as e:
            raise ImportProblem(_engine_problems(str(e)))
        except Exception:
            raise ImportProblem(["That file could not be read as an Excel workbook"])

    problems: List[str] = []
    workpack = {column: (sheet["project"].get(key) or "") for key, column in PROJECT_MAP.items()}
    if not workpack.get("title"):
        problems.append("The Project sheet has no Project title")
    if len(sheet["certs"]) > MAX_CERTIFICATES:
        problems.append(f"The Certificates sheet has {len(sheet['certs'])} rows; the limit is {MAX_CERTIFICATES}")

    certificates: List[Dict] = []
    by_id: Dict[str, Dict] = {}
    for rec in sheet["certs"]:
        cert = {"cert_id": rec["id"], "form": rec["form"].strip().upper(), "rows": {}}
        for key, column in CERT_MAP.items():
            cert[column] = rec.get(key) or ""
        for column in ("folder", "filename"):
            if _unsafe(cert[column]):
                problems.append(f"Certificates row {rec['_row']}: the {column} must be a plain name, not a path")
        certificates.append(cert)
        by_id[rec["id"]] = cert

    for data_key, (kind, _) in TABLES.items():
        for rec in sheet[data_key]:
            cert = by_id[rec["cert"]]                 # the engine's reader has already checked this exists
            cert["rows"].setdefault(kind, []).append({column: rec.get(key) or "" for key, column in ROW_MAPS[data_key].items()})
    for cert in certificates:
        for kind, rows in cert["rows"].items():
            if len(rows) > MAX_ROWS:
                problems.append(f"{cert['cert_id']}: {len(rows)} {kind} rows; the limit is {MAX_ROWS}")
    if problems:
        raise ImportProblem(problems)
    return Parsed(workpack, certificates)


def safe_name(filename: str) -> str:
    """A file name fit to put in the audit log."""
    return re.sub(r"[^\w.\- ]", "_", os.path.basename(filename or ""))[:80] or "workbook.xlsx"


def import_workbook(repo: Repo, data: bytes, filename: str, user: str) -> ImportResult:
    """Create a new workpack from a workbook. If anything fails part-way, what was created is removed again."""
    parsed = parse_workbook(data, filename)
    wp_id = repo.create_workpack(parsed.workpack, user)
    try:
        for cert in parsed.certificates:
            pk = repo.add_certificate(wp_id, cert, user)
            for kind, rows in cert["rows"].items():
                repo.replace_rows(pk, kind, rows, user)
    except Exception as e:
        repo.delete_workpack(wp_id)
        raise ImportProblem([str(e) if isinstance(e, ValueError) else "The workbook could not be saved"])
    repo.audit("workpack_imported", f"{parsed.workpack['title']}: {len(parsed.certificates)} certificates, "
                                     f"{parsed.row_count} table rows, from {safe_name(filename)}")
    return ImportResult(wp_id, len(parsed.certificates), parsed.row_count)
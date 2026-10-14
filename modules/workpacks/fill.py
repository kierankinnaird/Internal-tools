"""Fills a saved workpack's forms by running the Workpack Tools engine on it."""
from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .engine import fill_workpack as F
from .fields import ROW_KIND_BY_FORM
from .repo import Repo
from .sheet import write_input_workbook
from .store import TemplateStore

_ENGINE_LOCK = threading.Lock()     # the engine keeps its templates folder in a module setting, so one run at a time


@dataclass
class FormResult:
    cert_id: str
    form: str
    status: str
    output: str
    note: str


@dataclass
class FillReport:
    workpack: str
    out_dir: Path
    forms: List[FormResult] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return sum(1 for f in self.forms if f.status == "OK")

    @property
    def problems(self) -> int:
        return len(self.forms) - self.ok


def _unsafe(value: str) -> bool:
    """A folder or file name that is a path leaving the output folder."""
    if not value:
        return False
    v = value.replace("\\", "/")
    return os.path.isabs(value) or v.startswith("/") or ":" in v or ".." in v.split("/")


@contextmanager
def _engine_templates(folder: Path):
    """Point the engine's template-manifest lookup at our folder for the length of a run."""
    old = F.BUNDLED_TEMPLATES
    F.BUNDLED_TEMPLATES = str(folder)
    try:
        yield
    finally:
        F.BUNDLED_TEMPLATES = old


class FillService:
    def __init__(self, repo: Repo, store: TemplateStore):
        self.repo = repo
        self.store = store

    def _certificates(self, wp_id: int, cert_pks: Optional[List[int]]) -> List[Dict]:
        if not self.repo.get_workpack(wp_id):
            raise ValueError("No such workpack")
        certs = self.repo.list_certificates(wp_id)
        if cert_pks is not None:
            certs = [c for c in certs if c["id"] in set(cert_pks)]
        if not certs:
            raise ValueError("There are no certificates to fill")
        return certs

    def build_workbook(self, wp_id: int, path: Path, cert_pks: Optional[List[int]] = None) -> None:
        """Write the engine's input workbook for this workpack. Rows go in only for the kind the form takes."""
        certs = self._certificates(wp_id, cert_pks)
        rows = {}
        for c in certs:
            kind = ROW_KIND_BY_FORM.get(c["form"])
            if kind:
                rows[c["id"]] = {kind: self.repo.get_rows(c["id"], kind)}
        write_input_workbook(path, self.repo.get_workpack(wp_id), certs, rows)

    def fill(self, wp_id: int, out_dir: Path, cert_pks: Optional[List[int]] = None, spare_rows: Optional[int] = None,
             add_rows: bool = False, overwrite: bool = False) -> FillReport:
        certs = self._certificates(wp_id, cert_pks)
        for c in certs:
            if _unsafe(c["folder"]) or _unsafe(c["filename"]):
                raise ValueError(f"{c['cert_id']}: output folder and file name must be plain names, "
                                 "not paths that leave the output folder")
        status = self.store.status()
        if not status.present:
            raise ValueError(f"The blank templates are not installed (looked in {status.folder})")
        out_dir = Path(out_dir)
        title = self.repo.get_workpack(wp_id)["title"]
        with tempfile.TemporaryDirectory(prefix="wp_fill_") as tmp:
            sheet = Path(tmp) / "input.xlsx"
            self.build_workbook(wp_id, sheet, cert_pks)
            settings = F.load_settings(F.default_settings_path())
            try:
                with _ENGINE_LOCK, _engine_templates(status.folder):
                    results, audit = F.run(str(sheet), str(status.folder), str(out_dir), overwrite=overwrite,
                                           add_rows=add_rows, spare_rows=spare_rows,
                                           report=lambda *a, **k: None, settings=settings)
                    F.write_logs(str(out_dir), results, audit, None, tpl_dir=str(status.folder))
            except F.FillError as e:
                raise ValueError(str(e))
        report = FillReport(workpack=title, out_dir=out_dir)
        for cid, form, path, state, note in results:
            report.forms.append(FormResult(cid or "", form or "", state,
                                           os.path.relpath(path, out_dir).replace("\\", "/") if path else "", note or ""))
        if status.differs:
            report.notes.append("These templates differ from the templates pack: " + ", ".join(status.differs))
        if not status.manifest_found:
            report.notes.append("The templates folder has no MANIFEST.csv, so the template versions were not checked")
        self.repo.audit("workpack_filled", f"{title}: {report.ok} ok, {report.problems} not ok")
        return report
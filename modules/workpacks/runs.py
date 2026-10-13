"""Saved fill runs: each time forms are filled, the output goes in a folder of its own with a small record of the run.

Layout, inside the app's data folder:  workpacks/output/wp<workpack id>/<run id>/   (run id is a UTC timestamp)
The folder holds the filled forms, the engine's fill-log.csv and fill-audit.csv, and run.json, which is our own
record of the options used and the result of each form (the results page is drawn from it).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

META = "run.json"
RUN_ID = re.compile(r"^\d{8}-\d{6}(-\d{1,2})?$")


def default_folder(data_dir: Path) -> Path:
    return Path(data_dir) / "workpacks" / "output"


def describe(report, user: str, spare_rows: Optional[int], add_rows: bool) -> Dict:
    """The run record for a finished FillReport."""
    return {"title": report.workpack, "user": user, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "spare_rows": spare_rows, "add_rows": add_rows, "ok": report.ok, "problems": report.problems,
            "notes": list(report.notes),
            "forms": [{"cert_id": f.cert_id, "form": f.form, "status": f.status, "output": f.output, "note": f.note}
                      for f in report.forms]}


class RunStore:
    def __init__(self, base: Path):
        self.base = Path(base)

    def _wp_dir(self, wp_id: int) -> Path:
        return self.base / f"wp{int(wp_id)}"

    def new(self, wp_id: int) -> Tuple[str, Path]:
        """Make an empty folder for a new run."""
        parent = self._wp_dir(wp_id)
        parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        for n in range(100):
            run_id = stamp if n == 0 else f"{stamp}-{n}"
            try:
                (parent / run_id).mkdir()
            except FileExistsError:
                continue
            return run_id, parent / run_id
        raise ValueError("Could not start a new fill run, please try again")

    def path(self, wp_id: int, run_id: str) -> Optional[Path]:
        """The run's folder, or None when the id is not a real run (the id comes from the URL, so it is checked)."""
        if not RUN_ID.match(run_id or ""):
            return None
        p = self._wp_dir(wp_id) / run_id
        return p if p.is_dir() else None

    def save(self, wp_id: int, run_id: str, meta: Dict) -> None:
        (self._wp_dir(wp_id) / run_id / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")

    def load(self, wp_id: int, run_id: str) -> Optional[Dict]:
        p = self.path(wp_id, run_id)
        try:
            meta = json.loads((p / META).read_text(encoding="utf-8")) if p else None
        except (OSError, ValueError):
            return None
        if isinstance(meta, dict):
            meta["run_id"] = run_id
            return meta
        return None

    def list(self, wp_id: int) -> List[Dict]:
        """Saved runs for a workpack, newest first."""
        parent = self._wp_dir(wp_id)
        if not parent.is_dir():
            return []
        metas = [self.load(wp_id, p.name) for p in parent.iterdir() if p.is_dir()]
        return sorted((m for m in metas if m), key=lambda m: m["run_id"], reverse=True)

    def delete(self, wp_id: int, run_id: str) -> bool:
        p = self.path(wp_id, run_id)
        if p:
            shutil.rmtree(p, ignore_errors=True)
        return bool(p)

    def delete_all(self, wp_id: int) -> None:
        shutil.rmtree(self._wp_dir(wp_id), ignore_errors=True)

    def zip_bytes(self, wp_id: int, run_id: str) -> Optional[bytes]:
        """The run's files as a zip. Our own run record and any form the engine rejected are left out."""
        p = self.path(wp_id, run_id)
        if not p:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.name != META and not f.name.endswith(".REJECTED"):
                    z.write(f, f.relative_to(p).as_posix())
        return buf.getvalue()
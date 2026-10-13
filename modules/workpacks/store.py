"""Where the blank Apache templates are kept, and whether they are the ones we expect.

The templates are Apache's documents, so they are not part of this repository. They live in a folder of their own
(by default userdata/workpacks/templates, which git ignores) that is installed from the templates pack. The pack
carries a MANIFEST.csv with a SHA-256 for each file, and this module compares the folder against it.
"""
from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MANIFEST = "MANIFEST.csv"
ENV_VAR = "NMC_WORKPACK_TEMPLATES"
KINDS = (".docx", ".xlsx")


def default_folder(data_dir: Path) -> Path:
    """The templates folder: the environment variable if set, otherwise inside the app's data folder."""
    override = os.environ.get(ENV_VAR, "").strip()
    return Path(override) if override else Path(data_dir) / "workpacks" / "templates"


@dataclass
class TemplateStatus:
    folder: Path
    docx_count: int = 0
    manifest_found: bool = False
    differs: List[str] = field(default_factory=list)    # on disk, but not the file the manifest lists
    missing: List[str] = field(default_factory=list)    # listed in the manifest, not on disk
    unlisted: List[str] = field(default_factory=list)   # on disk, not in the manifest (for example a newer revision)

    @property
    def present(self) -> bool:
        return self.docx_count > 0

    @property
    def ok(self) -> bool:
        return self.present and self.manifest_found and not self.differs and not self.missing


class TemplateStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._hashes: Dict[Tuple[str, int, int], str] = {}

    def _sha256(self, path: Path) -> str:
        st = path.stat()
        key = (path.name, st.st_size, st.st_mtime_ns)
        if key not in self._hashes:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            self._hashes[key] = h.hexdigest()
        return self._hashes[key]

    def _manifest(self) -> Optional[Dict[str, set]]:
        """{file name: the SHA-256 values accepted for it}, or None when there is no manifest.
        A copy with labelled header boxes also accepts Apache's own original."""
        path = self.folder / MANIFEST
        if not path.is_file():
            return None
        accepted: Dict[str, set] = {}
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                name, digest = row.get("file"), (row.get("sha256") or "").lower()
                if not name or not digest:
                    continue
                accepted[name] = {digest}
                if row.get("labelled header boxes") == "yes" and row.get("apache original sha256"):
                    accepted[name].add(row["apache original sha256"].lower())
        return accepted

    def status(self) -> TemplateStatus:
        result = TemplateStatus(folder=self.folder)
        if not self.folder.is_dir():
            return result
        on_disk = sorted(p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in KINDS)
        result.docx_count = sum(1 for p in on_disk if p.suffix.lower() == ".docx")
        manifest = self._manifest()
        if manifest is None:
            return result
        result.manifest_found = True
        names = {p.name for p in on_disk}
        result.missing = sorted(n for n in manifest if n not in names)
        result.unlisted = sorted(n for n in names if n not in manifest)
        result.differs = sorted(p.name for p in on_disk if p.name in manifest and self._sha256(p) not in manifest[p.name])
        return result
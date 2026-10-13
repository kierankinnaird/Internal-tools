"""The Workpack Tools engine is vendored exactly as released. These tests catch a wrong or edited copy early
(an older fill_workpack.py once caused a confusing KeyError), whatever line endings git has given the files."""
import hashlib
from pathlib import Path

import pytest

from modules.workpacks.engine import fill_workpack as F

ENGINE = Path(__file__).resolve().parent.parent / "modules" / "workpacks" / "engine"

# SHA-256 of each file with line endings normalised to LF. To take a new release of the engine, copy its files
# over these, update the numbers below and VERSION here, then run the whole suite (see modules/workpacks/README.md).
VERSION = "2.3"
PINNED = {
    "fill_workpack.py": "5a5a0086a7c8b585bc8dcb10ba9e68226935e54dd5eb8f02346dc13038612cc0",
    "fill_settings.json": "a55dc0ae221a1d00adbba389ea14576cc244a1169d93282d13589afc8951909e",
    "CHANGELOG.md": "ca81777d64383e6e01f9598b02d079708e1af9e70b76aca8d9a4a64e50421751",
}


def fingerprint(name: str) -> str:
    data = (ENGINE / name).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("name", sorted(PINNED))
def test_engine_file_is_the_released_copy(name):
    assert fingerprint(name) == PINNED[name], (
        f"{name} is not the v{VERSION} release. Copy it again from the Workpack Tools folder "
        "(or, for a deliberate new release, update PINNED in this test).")


def test_engine_version_matches():
    assert F.VERSION == VERSION
    assert f"## v{VERSION}," in (ENGINE / "CHANGELOG.md").read_text(encoding="utf-8")
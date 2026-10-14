import re
import sqlite3
from pathlib import Path

import pytest

import modules.workpacks.web as web
from core.migrations import migrate
from hosts.standalone import create_app
from modules.jobcards.repo import Repo as JobcardsRepo
from modules.workpacks.fill import FillReport, FormResult
from modules.workpacks.repo import Repo as WorkpacksRepo

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"


@pytest.mark.parametrize("repo_class, migrations", [
    (WorkpacksRepo, MODULES / "workpacks" / "migrations"), (JobcardsRepo, MODULES / "jobcards" / "migrations")])
def test_a_repo_writes_audit_entries_through_a_public_method(tmp_path, repo_class, migrations):
    db = tmp_path / "x.sqlite"
    migrate(db, "x", migrations)
    events = []
    repo = repo_class(db, audit=lambda action, detail: events.append((action, detail)))
    repo.audit("workpack_filled", "Wellbay 18: 3 ok, 0 not ok")
    repo.audit("something_happened")                                              # the detail is optional
    assert events == [("workpack_filled", "Wellbay 18: 3 ok, 0 not ok"), ("something_happened", "")]


def test_a_repo_without_an_audit_sink_ignores_entries(tmp_path):
    db = tmp_path / "x.sqlite"
    migrate(db, "x", MODULES / "workpacks" / "migrations")
    WorkpacksRepo(db).audit("anything", "is fine")                                # the default sink does nothing


def test_nothing_outside_a_repo_reaches_for_its_private_audit_function():
    """`repo._audit(...)` from another file is what the public audit() method replaced. Only a class may use its own."""
    offenders = []
    for path in sorted(MODULES.rglob("*.py")):
        if "engine" in path.parts:                                                # the vendored engine is not ours to change
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"(\w+(?:\.\w+)*)\._audit\b", line):
                if match.group(1) != "self":
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {match.group(0)}")
    assert offenders == []


# ---- the entries still reach the audit log -------------------------------------------------------------------------
def audit_rows(tmp):
    with sqlite3.connect(tmp / "audit.sqlite") as db:
        return db.execute("SELECT user, module, action, detail FROM audit ORDER BY id").fetchall()


class StubFiller:
    def __init__(self, repo, store):
        self.repo = repo

    def fill(self, wp_id, out_dir, cert_pks=None, spare_rows=None, add_rows=False, overwrite=False):
        (out_dir / "AS1").mkdir()
        (out_dir / "AS1" / "AS1-1.docx").write_bytes(b"docx")
        (out_dir / "fill-log.csv").write_text("log", encoding="utf-8")
        self.repo.audit("workpack_filled", "Wellbay 18: 1 ok, 0 not ok")           # what the real service does
        return FillReport("Wellbay 18", out_dir, [FormResult("AS1-1", "AS1", "OK", "AS1/AS1-1.docx", "")], [])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "FillService", StubFiller)
    folder = tmp_path / "workpacks" / "templates"
    folder.mkdir(parents=True)
    (folder / "AS1 blank.docx").write_bytes(b"x")
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "Wellbay 18"})
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    return c, tmp_path


def test_fill_download_and_delete_still_write_their_audit_entries(client):
    c, tmp = client
    run_url = c.post("/workpacks/1/fill", data={"cert": ["1"]}).headers["Location"]
    assert c.get(run_url + "/download").status_code == 200                           # the whole run as a zip
    assert c.get(run_url + "/files/fill-log.csv").status_code == 200                 # a single file
    assert c.post(run_url + "/delete").status_code == 302
    actions = [(user, module, action) for user, module, action, _ in audit_rows(tmp)]
    for action in ("workpack_filled", "workpack_downloaded", "workpack_run_deleted"):
        assert ("tester", "workpacks", action) in actions, action
    assert [a for _, _, a in actions].count("workpack_downloaded") == 2              # one for the zip, one for the single file
    details = [detail for _, _, action, detail in audit_rows(tmp) if action == "workpack_downloaded"]
    assert any("fill-log.csv" in d for d in details) and any("run " in d for d in details)


def test_an_import_still_writes_its_audit_entry(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from modules.workpacks import importer
    from modules.workpacks.engine import fill_workpack as F
    sheet = tmp_path / "input.xlsx"
    F.make_sheet(str(sheet))
    wb = openpyxl.load_workbook(sheet)
    project = wb["Project"]
    for row in range(2, project.max_row + 1):
        if project.cell(row, 1).value == "Project title":
            project.cell(row, 2).value = "Imported pack"
    wb.save(sheet)
    app = create_app(userdata=tmp_path / "data", user_name="tester", modules=["workpacks"])
    c = app.test_client()
    with open(sheet, "rb") as fh:
        r = c.post("/workpacks/import", data={"workbook": (fh, "input.xlsx")}, content_type="multipart/form-data")
    assert r.status_code == 302
    rows = audit_rows(tmp_path / "data")
    assert any(action == "workpack_imported" and "Imported pack" in detail and "input.xlsx" in detail for _, _, action, detail in rows)
    assert importer.safe_name("input.xlsx") == "input.xlsx"

import hashlib
import zipfile
from pathlib import Path

import pytest

from core.migrations import migrate
from modules.workpacks.engine import fill_workpack as F
from modules.workpacks.fields import (CERTIFICATE_FIELDS, ROW_KINDS, WORKPACK_FIELDS)
from modules.workpacks.fill import FillService
from modules.workpacks.repo import Repo
from modules.workpacks.store import TemplateStore, default_folder

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "modules" / "workpacks" / "migrations"
PACK = default_folder(ROOT / "userdata")
needs_pack = pytest.mark.skipif(not TemplateStore(PACK).status().ok, reason="templates pack not installed")


@pytest.fixture()
def repo(tmp_path):
    db = tmp_path / "workpacks.sqlite"
    migrate(db, "workpacks", MIGRATIONS)
    events = []
    r = Repo(db, audit=lambda action, detail: events.append((action, detail)))
    r.events = events
    return r


@pytest.fixture()
def service(repo, tmp_path):
    return FillService(repo, TemplateStore(PACK))


def make_workpack(repo):
    wp = repo.create_workpack({
        "title": "Wellbay 18 clearance", "project_no": "FCP-123", "workpack_no": "WPK-018", "sh1_no": "SH1-18",
        "mc1_no": "MC1-18", "site": "Alpha", "location": "Wellbay", "system": "Fuel gas",
        "handover_includes": "Line one\nLine two", "ee12_description": "Tests:\n[TAGS]"}, "k")
    sh1 = repo.add_certificate(wp, {"cert_id": "SH1-18", "form": "SH1"}, "k")
    as1 = repo.add_certificate(wp, {"cert_id": "AS1-1", "form": "AS1", "equipment": "Pump P-1", "area": "Deck",
                                    "scope": "Check =1+1 alignment"}, "k")
    sl1 = repo.add_certificate(wp, {"cert_id": "SL1-1", "form": "SL1", "equipment": "Skid", "sl1a": "SL1A-AB-12345"}, "k")
    ji1 = repo.add_certificate(wp, {"cert_id": "JI1-1", "form": "JI1"}, "k")
    ee12 = repo.add_certificate(wp, {"cert_id": "EE12-1", "form": "EE12", "equipment": "Panel"}, "k")
    repo.replace_rows(sl1, "line", [{"pid": "P-100", "line_no": '2"-FG-001', "from_equipment": "A", "to_equipment": "B"}], "k")
    repo.replace_rows(ji1, "joint", [{"joint_no": "J-1", "drawing": "D1", "size": 6, "rating": "300#",
                                      "joint_type": "RTJ", "torque": 230.0}], "k")
    repo.replace_rows(ee12, "tag", [{"tag": "TAG-1", "drawing": "D9"}, {"tag": "TAG-2"}], "k")
    return wp, {"sh1": sh1, "as1": as1, "sl1": sl1, "ji1": ji1, "ee12": ee12}


# ---- the workbook handed to the engine ---------------------------------------------------------
def test_our_labels_are_the_ones_the_engine_reads():
    engine = {label for _, label, _ in F.PROJECT_FIELDS}
    assert {label for _, label in WORKPACK_FIELDS} == engine
    engine = {label for _, label, _ in F.CERT_COLUMNS} - {"ID", "Form"}
    assert {label for _, label in CERTIFICATE_FIELDS} == engine
    for kind, columns in (("line", F.LINE_COLUMNS), ("joint", F.JOINT_COLUMNS), ("tag", F.TAG_COLUMNS)):
        assert {label for _, label in ROW_KINDS[kind][1]} == {label for _, label, _ in columns} - {"Certificate ID"}


def test_the_engine_reads_back_what_we_wrote(repo, service, tmp_path):
    wp, ids = make_workpack(repo)
    service.build_workbook(wp, tmp_path / "in.xlsx")
    data = F.read_sheet(str(tmp_path / "in.xlsx"))
    p = data["project"]
    assert (p["title"], p["project_no"], p["workpack"], p["sh1"], p["mc1"]) == (
        "Wellbay 18 clearance", "FCP-123", "WPK-018", "SH1-18", "MC1-18")
    assert p["handover_includes"] == "Line one\nLine two" and p["site"] == "Alpha" and p["handover_excludes"] is None
    certs = {c["id"]: c for c in data["certs"]}
    assert list(certs) == ["SH1-18", "AS1-1", "SL1-1", "JI1-1", "EE12-1"]
    assert certs["AS1-1"]["equipment"] == "Pump P-1" and certs["AS1-1"]["area"] == "Deck"
    assert certs["AS1-1"]["scope"] == "Check =1+1 alignment" and certs["SL1-1"]["sl1a"] == "SL1A-AB-12345"
    assert certs["SH1-18"]["equipment"] is None
    assert data["lines"][0]["cert"] == "SL1-1" and data["lines"][0]["line"] == '2"-FG-001' and data["lines"][0]["to"] == "B"
    assert data["joints"][0]["torque"] == "230" and data["joints"][0]["size"] == "6"
    assert [t["tag"] for t in data["tags"]] == ["TAG-1", "TAG-2"] and data["tags"][1]["drawing"] is None


def test_text_starting_with_equals_stays_text(repo, service, tmp_path):
    wp = repo.create_workpack({"title": "=1+1"}, "k")
    repo.add_certificate(wp, {"cert_id": "A", "form": "AS1", "equipment": "=SUM(A1)"}, "k")
    service.build_workbook(wp, tmp_path / "in.xlsx")
    data = F.read_sheet(str(tmp_path / "in.xlsx"))
    assert data["project"]["title"] == "=1+1" and data["certs"][0]["equipment"] == "=SUM(A1)"


def test_rows_of_the_wrong_kind_are_left_out(repo, service, tmp_path):
    wp, ids = make_workpack(repo)
    repo.update_certificate(ids["sl1"], {"form": "AS1"}, "k")      # the lines it has are now orphans
    service.build_workbook(wp, tmp_path / "in.xlsx")
    assert F.read_sheet(str(tmp_path / "in.xlsx"))["lines"] == []


def test_only_the_selected_certificates_are_written(repo, service, tmp_path):
    wp, ids = make_workpack(repo)
    service.build_workbook(wp, tmp_path / "in.xlsx", [ids["ee12"], ids["as1"]])
    data = F.read_sheet(str(tmp_path / "in.xlsx"))
    assert [c["id"] for c in data["certs"]] == ["AS1-1", "EE12-1"] and len(data["tags"]) == 2 and data["lines"] == []


# ---- refusing before anything runs -------------------------------------------------------------
def test_unknown_workpack_and_nothing_to_fill(repo, service, tmp_path):
    with pytest.raises(ValueError, match="No such workpack"):
        service.fill(999, tmp_path / "out")
    wp = repo.create_workpack({"title": "Empty"}, "k")
    with pytest.raises(ValueError, match="no certificates"):
        service.fill(wp, tmp_path / "out")
    wp2, ids = make_workpack(repo)
    with pytest.raises(ValueError, match="no certificates"):
        service.fill(wp2, tmp_path / "out", cert_pks=[99999])


def test_a_certificate_cannot_send_files_outside_the_output_folder(repo, service, tmp_path):
    wp = repo.create_workpack({"title": "T"}, "k")
    repo.add_certificate(wp, {"cert_id": "A", "form": "AS1", "folder": "..\\..\\escape"}, "k")
    with pytest.raises(ValueError, match="plain names"):
        service.fill(wp, tmp_path / "out")
    repo.add_certificate(wp, {"cert_id": "B", "form": "AS1", "filename": "C:/Windows/x"}, "k")
    with pytest.raises(ValueError, match="plain names"):
        service.fill(wp, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_missing_templates_give_a_clear_message(repo, tmp_path):
    wp, _ = make_workpack(repo)
    service = FillService(repo, TemplateStore(tmp_path / "no-templates-here"))
    with pytest.raises(ValueError, match="templates are not installed"):
        service.fill(wp, tmp_path / "out")


# ---- a real fill, when the templates pack is installed -----------------------------------------
def _hashes(folder: Path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


@needs_pack
def test_a_real_fill_writes_every_form_and_leaves_the_templates_alone(repo, service, tmp_path):
    wp, ids = make_workpack(repo)
    before = _hashes(PACK)
    report = service.fill(wp, tmp_path / "out", spare_rows=4)
    assert [(f.form, f.status) for f in report.forms] == [
        ("SH1", "OK"), ("AS1", "OK"), ("SL1", "OK"), ("JI1", "OK"), ("EE12", "OK")], [f.note for f in report.forms]
    assert report.ok == 5 and report.problems == 0 and report.notes == []
    for f in report.forms:
        assert (tmp_path / "out" / f.output).is_file()
    assert (tmp_path / "out" / "fill-log.csv").is_file() and (tmp_path / "out" / "fill-audit.csv").is_file()
    sh1 = next(f for f in report.forms if f.form == "SH1")
    with zipfile.ZipFile(tmp_path / "out" / sh1.output) as z:
        assert "Wellbay 18 clearance" in z.read("word/document.xml").decode("utf-8")
    assert _hashes(PACK) == before
    assert repo.events[-1] == ("workpack_filled", "Wellbay 18 clearance: 5 ok, 0 not ok")


@needs_pack
def test_filling_again_skips_files_that_already_exist_unless_told_to_overwrite(repo, service, tmp_path):
    wp, ids = make_workpack(repo)
    service.fill(wp, tmp_path / "out", [ids["as1"]])
    again = service.fill(wp, tmp_path / "out", [ids["as1"]])
    assert again.forms[0].status == "SKIPPED"
    assert service.fill(wp, tmp_path / "out", [ids["as1"]], overwrite=True).forms[0].status == "OK"


@needs_pack
def test_a_form_with_no_template_is_reported_not_fatal(repo, service, tmp_path):
    wp = repo.create_workpack({"title": "T"}, "k")
    repo.add_certificate(wp, {"cert_id": "X", "form": "NOPE"}, "k")
    repo.add_certificate(wp, {"cert_id": "A", "form": "AS1"}, "k")
    report = service.fill(wp, tmp_path / "out")
    assert [(f.form, f.status) for f in report.forms] == [("NOPE", "FAILED"), ("AS1", "OK")]
    assert report.problems == 1
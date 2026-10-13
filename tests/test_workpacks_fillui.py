import io
import sqlite3
import zipfile

import pytest

import modules.workpacks.web as web
from hosts.standalone import create_app
from modules.workpacks.fill import FillReport, FormResult
from modules.workpacks.runs import RunStore, describe
from modules.workpacks.web import parse_spare


class StubFiller:
    """Stands in for the engine: writes two files and one failure, and remembers how it was called."""
    calls = []

    def __init__(self, repo, store):
        self.repo = repo

    def fill(self, wp_id, out_dir, cert_pks=None, spare_rows=None, add_rows=False, overwrite=False):
        StubFiller.calls.append({"wp": wp_id, "certs": cert_pks, "spare": spare_rows, "add": add_rows})
        (out_dir / "AS1").mkdir()
        (out_dir / "AS1" / "AS1-1.docx").write_bytes(b"docx")
        (out_dir / "AS1" / "AS1-2.docx.REJECTED").write_bytes(b"bad")
        (out_dir / "fill-log.csv").write_text("log", encoding="utf-8")
        (out_dir / "fill-audit.csv").write_text("audit", encoding="utf-8")
        return FillReport("Wellbay 18 clearance", out_dir, [
            FormResult("AS1-1", "AS1", "OK", "AS1/AS1-1.docx", ""),
            FormResult("AS1-2", "AS1", "CHECK FAILED", "", "<script>alert(1)</script>")], ["a note"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "FillService", StubFiller)
    StubFiller.calls = []
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "Wellbay 18 clearance"})
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-2", "form": "AS1"})
    return c, tmp_path, app


def audit(tmp):
    return [a for a, _ in sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action, detail FROM audit")]


def fill(c, **extra):
    data = {"cert": ["1", "2"], **extra}
    return c.post("/workpacks/1/fill", data=data)


# ---- options ---------------------------------------------------------------------------------
def test_parse_spare():
    assert parse_spare("") is None and parse_spare("  ") is None and parse_spare("0") == 0 and parse_spare("50") == 50
    for bad in ("51", "-1", "x", "1.5", "\u00b2"):
        with pytest.raises(ValueError):
            parse_spare(bad)


# ---- the fill page ---------------------------------------------------------------------------
def test_the_fill_page_lists_the_certificates_ticked(client):
    c, tmp, _ = client
    make_ready(tmp)
    html = c.get("/workpacks/1/fill").get_data(as_text=True)
    assert html.count('name="cert"') == 2 and html.count(" checked") >= 2
    assert "Nothing has been filled" in html


def test_the_page_says_so_when_the_templates_are_missing(client):
    c, _, _ = client
    html = c.get("/workpacks/1/fill").get_data(as_text=True)
    assert "not installed" in html and "Fill forms</button>" not in html and 'name="cert"' not in html


def test_an_empty_workpack_cannot_be_filled(client):
    c, _, _ = client
    c.post("/workpacks/", data={"title": "Empty"})
    assert "no certificates yet" in c.get("/workpacks/2/fill").get_data(as_text=True)


# ---- running a fill ---------------------------------------------------------------------------
def make_ready(tmp):
    folder = tmp / "workpacks" / "templates"
    folder.mkdir(parents=True)
    (folder / "AS1 blank.docx").write_bytes(b"x")


def test_filling_saves_a_run_and_shows_the_result(client):
    c, tmp, _ = client
    make_ready(tmp)
    r = fill(c, spare_rows="3", add_rows="1")
    assert r.status_code == 302 and "/workpacks/1/runs/" in r.headers["Location"]
    assert StubFiller.calls == [{"wp": 1, "certs": [1, 2], "spare": 3, "add": True}]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "1 of 2 forms written, 1 need attention" in html and "a note" in html and "Spare rows kept: 3" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "AS1/AS1-1.docx" in html
    assert "workpack_filled" not in audit(tmp)        # the stub does not audit; the real service does


def test_a_run_appears_in_the_earlier_runs_list(client):
    c, tmp, _ = client
    make_ready(tmp)
    fill(c)
    html = c.get("/workpacks/1/fill").get_data(as_text=True)
    assert "1 ok, 1 not ok" in html and "Download zip" in html and "Nothing has been filled" not in html


def test_nothing_ticked_or_bad_options_are_refused_without_a_run(client):
    c, tmp, _ = client
    make_ready(tmp)
    for data in ({}, {"cert": ["x"]}, {"cert": ["1"], "spare_rows": "99"}):
        r = c.post("/workpacks/1/fill", data=data)
        assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert StubFiller.calls == [] and not (tmp / "workpacks" / "output").exists()


def test_a_failed_fill_leaves_no_folder_behind(client, monkeypatch):
    c, tmp, _ = client
    make_ready(tmp)

    class Refusing(StubFiller):
        def fill(self, *a, **k):
            raise ValueError("The blank templates are not installed")
    monkeypatch.setattr(web, "FillService", Refusing)
    app = create_app(userdata=tmp, user_name="tester", modules=["workpacks"])
    r = app.test_client().post("/workpacks/1/fill", data={"cert": ["1"]})
    assert "error=The+blank+templates" in r.headers["Location"]
    assert list((tmp / "workpacks" / "output" / "wp1").iterdir()) == []


def test_the_real_service_refuses_when_the_templates_are_missing(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "W"})
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    r = c.post("/workpacks/1/fill", data={"cert": ["1"]})
    assert "error=" in r.headers["Location"]
    assert list((tmp_path / "workpacks" / "output" / "wp1").iterdir()) == []


# ---- downloads ---------------------------------------------------------------------------------
def test_the_zip_holds_the_forms_and_logs_but_not_rejected_files_or_the_record(client):
    c, tmp, _ = client
    make_ready(tmp)
    loc = fill(c).headers["Location"]
    r = c.get(loc + "/download")
    assert r.status_code == 200 and r.mimetype == "application/zip" and ".zip" in r.headers["Content-Disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert sorted(names) == ["AS1/AS1-1.docx", "fill-audit.csv", "fill-log.csv"]
    assert "workpack_downloaded" in audit(tmp)


def test_single_files_download_but_the_record_and_rejected_files_do_not(client):
    c, tmp, _ = client
    make_ready(tmp)
    loc = fill(c).headers["Location"]
    assert c.get(loc + "/files/AS1/AS1-1.docx").data == b"docx"
    assert c.get(loc + "/files/fill-log.csv").status_code == 200
    for name in ("run.json", "AS1/AS1-2.docx.REJECTED", "../run.json", "nothing.docx"):
        assert c.get(loc + "/files/" + name).status_code == 404, name


def test_run_ids_are_checked(client):
    c, tmp, _ = client
    make_ready(tmp)
    fill(c)
    for bad in ("..", "x", "20250101-000000", "%2e%2e"):
        assert c.get(f"/workpacks/1/runs/{bad}").status_code == 404, bad
        assert c.get(f"/workpacks/1/runs/{bad}/download").status_code == 404, bad


def test_a_run_belongs_to_its_workpack(client):
    c, tmp, _ = client
    make_ready(tmp)
    loc = fill(c).headers["Location"]
    c.post("/workpacks/", data={"title": "Other"})
    assert c.get(loc.replace("/workpacks/1/", "/workpacks/2/")).status_code == 404


def test_deleting_a_run_and_deleting_the_workpack_remove_the_files(client):
    c, tmp, _ = client
    make_ready(tmp)
    loc = fill(c).headers["Location"]
    assert c.post(loc + "/delete").status_code == 302
    assert c.get(loc).status_code == 404 and list((tmp / "workpacks" / "output" / "wp1").iterdir()) == []
    fill(c)
    c.post("/workpacks/1/delete")
    assert not (tmp / "workpacks" / "output" / "wp1").exists()
    assert "workpack_run_deleted" in audit(tmp)


# ---- permissions ---------------------------------------------------------------------------------
def test_filling_needs_the_fill_permission(client):
    c, tmp, app = client
    make_ready(tmp)
    loc = fill(c).headers["Location"]
    app.config["CTX"]._permissions = {"workpacks.view", "workpacks.edit"}
    assert "Fill forms" not in c.get("/workpacks/1").get_data(as_text=True)
    for method, url in [("get", "/workpacks/1/fill"), ("post", "/workpacks/1/fill"), ("get", loc),
                        ("get", loc + "/download"), ("get", loc + "/files/fill-log.csv"), ("post", loc + "/delete")]:
        assert getattr(c, method)(url).status_code == 403, url
    app.config["CTX"]._permissions = {"workpacks.view", "workpacks.fill"}
    assert "Fill forms" in c.get("/workpacks/1").get_data(as_text=True)
    assert c.get(loc).status_code == 200


def test_the_certificate_table_links_to_the_row_editor(client):
    c, _, _ = client
    c.post("/workpacks/1/certificates", data={"cert_id": "SL1-1", "form": "SL1"})
    assert 'href="/workpacks/certificates/3/rows"' in c.get("/workpacks/1").get_data(as_text=True)


# ---- the run store -------------------------------------------------------------------------------
def test_run_store_makes_unique_folders_and_lists_newest_first(tmp_path):
    s = RunStore(tmp_path)
    a, _ = s.new(1)
    b, _ = s.new(1)
    assert a != b
    rep = FillReport("T", tmp_path, [FormResult("A", "AS1", "OK", "a.docx", "")])
    s.save(1, a, describe(rep, "k", None, False))
    s.save(1, b, describe(rep, "k", 2, True))
    assert [m["run_id"] for m in s.list(1)] == sorted([a, b], reverse=True)
    assert s.list(2) == [] and s.zip_bytes(1, "nope") is None
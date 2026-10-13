import csv
import hashlib
import sqlite3
from pathlib import Path

import pytest

from hosts.standalone import create_app
from modules.workpacks.store import TemplateStatus
from modules.workpacks.web import template_banner


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    return app.test_client(), tmp_path, app


def install_pack(tmp_path, content=b"template", listed=True, manifest=True):
    folder = tmp_path / "workpacks" / "templates"
    folder.mkdir(parents=True)
    (folder / "AS1.docx").write_bytes(content)
    if manifest:
        with open(folder / "MANIFEST.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "sha256"])
            if listed:
                w.writerow(["AS1.docx", hashlib.sha256(b"template").hexdigest()])
    return folder


def test_the_page_opens_and_the_menu_has_workpacks(client):
    c, _, app = client
    html = c.get("/workpacks/").get_data(as_text=True)
    assert "<h1>Workpacks</h1>" in html and "No workpacks yet" in html and "Working as tester" in html
    assert {"label": "Workpacks", "endpoint": "workpacks.index"} in app.config["NAV"]
    assert c.get("/").headers["Location"].endswith("/workpacks/")      # first module in the menu


def test_the_module_creates_its_own_database(client):
    c, tmp, _ = client
    c.get("/workpacks/")
    tables = {r[0] for r in sqlite3.connect(tmp / "workpacks.sqlite").execute("SELECT name FROM sqlite_master")}
    assert {"workpack", "certificate", "line", "joint", "tag"} <= tables


def test_creating_a_workpack_lists_it_and_is_audited(client):
    c, tmp, _ = client
    r = c.post("/workpacks/", data={"title": "Wellbay 18 clearance", "project_no": "FCP-123", "workpack_no": "WPK-018",
                                    "site": "Alpha"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/1")
    html = c.get("/workpacks/").get_data(as_text=True)
    assert "Wellbay 18 clearance" in html and 'href="/workpacks/1"' in html
    assert "FCP-123" in html and "WPK-018" in html and "Alpha" in html
    assert "No workpacks yet" not in html
    rows = sqlite3.connect(tmp / "audit.sqlite").execute("SELECT user, module, action, detail FROM audit").fetchall()
    assert rows == [("tester", "workpacks", "workpack_created", "Wellbay 18 clearance")]


def test_a_workpack_needs_a_title(client):
    c, tmp, _ = client
    r = c.post("/workpacks/", data={"title": "   ", "project_no": "FCP-1"})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Project title is required" in html and "No workpacks yet" in html


def test_typed_text_is_escaped(client):
    c, _, _ = client
    c.post("/workpacks/", data={"title": "<script>alert(1)</script>"})
    html = c.get("/workpacks/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    html = c.get("/workpacks/?error=%3Cb%3Eoops%3C/b%3E").get_data(as_text=True)
    assert "<b>oops</b>" not in html


def test_without_edit_permission_nobody_can_create(client):
    c, tmp, app = client
    app.config["CTX"]._permissions = {"workpacks.view"}
    assert c.post("/workpacks/", data={"title": "Nope"}).status_code == 403
    html = c.get("/workpacks/").get_data(as_text=True)
    assert "New workpack" not in html and "All workpacks" in html
    app.config["CTX"]._permissions = set()
    assert c.get("/workpacks/").status_code == 403


def test_the_stylesheet_is_served(client):
    c, _, _ = client
    r = c.get("/workpacks/static/workpacks.css")
    assert r.status_code == 200 and b"border-radius" not in r.data     # sharp edges: nothing rounds


# ---- the template banner -----------------------------------------------------------------------
def test_banner_when_the_templates_are_not_installed(client):
    c, _, _ = client
    html = c.get("/workpacks/").get_data(as_text=True)
    assert 'class="banner warn"' in html and "not installed" in html


def test_banner_with_a_matching_pack(client):
    _, tmp, _ = client
    install_pack(tmp)
    app = create_app(userdata=tmp, user_name="tester", modules=["workpacks"])
    html = app.test_client().get("/workpacks/").get_data(as_text=True)
    assert 'class="banner ok"' in html and "1 templates installed, all matching the pack" in html


def test_banner_for_each_kind_of_problem():
    base = dict(folder=Path("T"), docx_count=3, manifest_found=True)
    assert template_banner(TemplateStatus(**base))["level"] == "ok"
    changed = template_banner(TemplateStatus(**base, differs=["AS1.docx"]))
    assert changed["level"] == "warn" and "AS1.docx" in changed["details"][0]
    gone = template_banner(TemplateStatus(**base, missing=["SH1.docx"]))
    assert gone["level"] == "warn" and "SH1.docx" in gone["details"][0]
    extra = template_banner(TemplateStatus(**base, unlisted=["AS1 rev B.docx"]))
    assert extra["level"] == "ok" and "AS1 rev B.docx" in extra["details"][0]     # a newer revision is not an error
    nomanifest = template_banner(TemplateStatus(folder=Path("T"), docx_count=3))
    assert nomanifest["level"] == "warn" and "MANIFEST.csv" in nomanifest["headline"]
    none = template_banner(TemplateStatus(folder=Path("T")))
    assert none["level"] == "warn" and "Looked in" in none["details"][0]
import sqlite3

import pytest

from hosts.standalone import create_app
from modules.workpacks.fields import WORKPACK_COLUMNS
from modules.workpacks.forms import form_codes
from modules.workpacks.web import GROUPS, rows_text


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "Wellbay 18 clearance", "project_no": "FCP-123"})   # workpack 1
    return c, tmp_path, app


def audit(tmp):
    return sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action, detail FROM audit").fetchall()


def certs(tmp):
    return sqlite3.connect(tmp / "workpacks.sqlite").execute(
        "SELECT cert_id, form, position FROM certificate ORDER BY position").fetchall()


# ---- the page ----------------------------------------------------------------------------------
def test_every_workpack_field_is_on_the_page_exactly_once():
    columns = [c for _, _, cols in GROUPS for c in cols]
    assert sorted(columns) == sorted(WORKPACK_COLUMNS)


def test_the_workpack_page_shows_the_details_and_every_field(client):
    c, _, _ = client
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "<h1>Wellbay 18 clearance</h1>" in html and 'value="FCP-123"' in html and "No certificates yet" in html
    for column in WORKPACK_COLUMNS:
        assert f'name="{column}"' in html


def test_an_unknown_workpack_is_a_404(client):
    c, _, _ = client
    assert c.get("/workpacks/99").status_code == 404
    assert c.post("/workpacks/99", data={"title": "x"}).status_code == 404
    assert c.post("/workpacks/99/delete").status_code == 404
    assert c.post("/workpacks/99/certificates", data={"cert_id": "A", "form": "AS1"}).status_code == 404


def test_saving_the_details(client):
    c, tmp, _ = client
    data = {"title": "Wellbay 18 (rev B)", "project_no": "FCP-123", "handover_includes": "Line one\r\nLine two",
            "ee12_description": "Tests", "jre": "A. Engineer"}
    r = c.post("/workpacks/1", data=data)
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/1")
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "Wellbay 18 (rev B)" in html and "A. Engineer" in html and "Line one\nLine two" in html
    assert ("workpack_updated", "Wellbay 18 clearance") in audit(tmp)


def test_saving_without_a_title_is_refused_and_changes_nothing(client):
    c, _, _ = client
    r = c.post("/workpacks/1", data={"title": " ", "site": "Alpha"})
    assert "error=" in r.headers["Location"]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Project title is required" in html and "Wellbay 18 clearance" in html and "Alpha" not in html


def test_creating_a_workpack_opens_its_page(client):
    c, _, _ = client
    r = c.post("/workpacks/", data={"title": "Second"})
    assert r.headers["Location"].endswith("/workpacks/2")


def test_deleting_a_workpack_removes_its_certificates(client):
    c, tmp, _ = client
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    r = c.post("/workpacks/1/delete")
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/")
    assert c.get("/workpacks/1").status_code == 404 and certs(tmp) == []
    assert ("workpack_deleted", "Wellbay 18 clearance") in audit(tmp)


# ---- certificates ------------------------------------------------------------------------------
def test_adding_certificates_in_order_and_form_codes_are_upper_cased(client):
    c, tmp, _ = client
    r = c.post("/workpacks/1/certificates", data={"cert_id": "SL1-1", "form": " sl1 "})
    assert r.headers["Location"].endswith("/workpacks/1#certificates")
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    assert certs(tmp) == [("SL1-1", "SL1", 1), ("AS1-1", "AS1", 2)]
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert html.index("SL1-1") < html.index("AS1-1") and "0 lines" in html
    assert ("certificate_added", "SL1 SL1-1") in audit(tmp)


def test_a_duplicate_or_blank_certificate_is_refused(client):
    c, tmp, _ = client
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    for data, message in [({"cert_id": "AS1-1", "form": "AS1"}, "already exists"),
                          ({"cert_id": "", "form": "AS1"}, "Certificate ID is required"),
                          ({"cert_id": "X", "form": ""}, "Form is required")]:
        r = c.post("/workpacks/1/certificates", data=data)
        assert message in c.get(r.headers["Location"]).get_data(as_text=True)
    assert certs(tmp) == [("AS1-1", "AS1", 1)]


def test_duplicating_and_deleting_a_certificate(client):
    c, tmp, _ = client
    c.post("/workpacks/1/certificates", data={"cert_id": "SL1-1", "form": "SL1"})
    pk = sqlite3.connect(tmp / "workpacks.sqlite").execute("SELECT id FROM certificate").fetchone()[0]
    r = c.post(f"/workpacks/certificates/{pk}/duplicate", data={"cert_id": "SL1-2"})
    assert r.headers["Location"].endswith("/workpacks/1#certificates")
    assert [x[0] for x in certs(tmp)] == ["SL1-1", "SL1-2"]
    bad = c.post(f"/workpacks/certificates/{pk}/duplicate", data={"cert_id": "SL1-2"})
    assert "already exists" in c.get(bad.headers["Location"]).get_data(as_text=True)
    c.post(f"/workpacks/certificates/{pk}/delete")
    assert [x[0] for x in certs(tmp)] == ["SL1-2"]
    assert c.post("/workpacks/certificates/999/delete").status_code == 404
    assert c.post("/workpacks/certificates/999/duplicate", data={"cert_id": "Q"}).status_code == 404


def test_typed_text_is_escaped_on_the_workpack_page(client):
    c, _, _ = client
    c.post("/workpacks/1", data={"title": "<b>bold</b>", "handover_includes": "</textarea><script>x()</script>"})
    c.post("/workpacks/1/certificates", data={"cert_id": "<i>x</i>", "form": "AS1"})
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "<b>bold</b>" not in html and "<script>x()</script>" not in html and "<i>x</i>" not in html


def test_rows_text():
    assert rows_text({"form": "SL1", "line_count": 1}) == "1 line"
    assert rows_text({"form": "JI1", "joint_count": 3}) == "3 joints"
    assert rows_text({"form": "EE12", "tag_count": 0}) == "0 tags"
    assert rows_text({"form": "AS1"}) == ""


# ---- permissions -------------------------------------------------------------------------------
def test_viewers_can_read_but_not_change_anything(client):
    c, tmp, app = client
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    app.config["CTX"]._permissions = {"workpacks.view"}
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "AS1-1" in html and "Save details" not in html and "Add certificate" not in html and "Delete" not in html
    assert "readonly" in html
    for url, data in [("/workpacks/1", {"title": "x"}), ("/workpacks/1/delete", {}),
                      ("/workpacks/1/certificates", {"cert_id": "B", "form": "AS1"}),
                      ("/workpacks/certificates/1/delete", {}), ("/workpacks/certificates/1/duplicate", {"cert_id": "C"})]:
        assert c.post(url, data=data).status_code == 403, url
    app.config["CTX"]._permissions = set()
    assert c.get("/workpacks/1").status_code == 403


# ---- the form list -----------------------------------------------------------------------------
def test_form_codes(tmp_path):
    assert {"AS1", "SH1", "C1", "DM", "PL1 A", "EE12"} <= set(form_codes(tmp_path / "nowhere"))
    for name in ["AS1.docx", "EE2.docx", "EE10.docx", "PL1 - Repair Orders.docx", "C1 CCHP.docx", "~$AS1.docx",
                 "PL1 A - FCP Projects (Construction).docx", "Pi & Mech ITR Matrix.xlsx"]:
        (tmp_path / name).write_bytes(b"x")
    codes = form_codes(tmp_path)
    assert "PL1" in codes and "PL1 A" in codes and "C1" in codes and "Pi" not in codes and "~$AS1" not in codes
    assert codes.index("EE2") < codes.index("EE10")                      # natural order
    assert len(codes) == len(set(codes))


def test_the_page_offers_the_installed_forms(client):
    c, tmp, _ = client
    folder = tmp / "workpacks" / "templates"
    folder.mkdir(parents=True)
    (folder / "TR7.docx").write_bytes(b"x")
    app = create_app(userdata=tmp, user_name="tester", modules=["workpacks"])
    html = app.test_client().get("/workpacks/1").get_data(as_text=True)
    assert '<option value="TR7">' in html and '<option value="AS1">' in html
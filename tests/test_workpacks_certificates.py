import sqlite3

import pytest

from hosts.standalone import create_app
from modules.workpacks import certfields
from modules.workpacks.engine import fill_workpack as F
from modules.workpacks.fields import CERTIFICATE_COLUMNS


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "Wellbay 18 clearance"})                  # workpack 1
    for cert_id, form in [("AS1-1", "AS1"), ("SL1-1", "SL1"), ("SH1-1", "SH1")]:  # certificates 1, 2, 3
        c.post("/workpacks/1/certificates", data={"cert_id": cert_id, "form": form})
    return c, tmp_path, app


def row(tmp, pk):
    db = sqlite3.connect(tmp / "workpacks.sqlite")
    db.row_factory = sqlite3.Row
    return dict(db.execute("SELECT * FROM certificate WHERE id=?", (pk,)).fetchone())


# ---- which fields belong to which form ---------------------------------------------------------
def test_fields_for_each_kind_of_form():
    assert certfields.relevant_columns("AS1") == ["equipment", "location", "area", "system", "subsystem", "drawing", "scope"]
    assert "sl1a" in certfields.relevant_columns("SL1") and "area" not in certfields.relevant_columns("SL1")
    assert "ee12_description" in certfields.relevant_columns("EE12")
    assert "procedure" in certfields.relevant_columns("SC1") and "description" in certfields.relevant_columns("SC1")
    for form in ("PL1 A", "PL1 B", "PL1"):
        assert certfields.relevant_columns(form) == ["punch_no", "discipline"]
    for form in ("SH1", "MC1", "C1", "DM", "TR7"):
        assert certfields.relevant_columns(form) == []


def test_every_form_the_engine_fills_gets_all_the_fields_the_engine_reads():
    for form, slots in F.BODY_FIELDS.items():
        wanted = {key for key, *_ in slots} & set(CERTIFICATE_COLUMNS)
        assert wanted <= set(certfields.relevant_columns(form)), form


@pytest.mark.parametrize("form", ["AS1", "SL1", "EE12", "SC1", "JI1", "SH1", "PL1 A", "TR7"])
def test_each_column_is_in_exactly_one_section(form):
    parts = certfields.sections(form)
    columns = [c for cols in parts.values() for c in cols]
    assert sorted(columns) == sorted(CERTIFICATE_COLUMNS)


def test_hints_come_from_the_engine():
    assert certfields.hint("area") == "AS1 only" and "SL1A-XX-XXXXX" in certfields.hint("sl1a")
    assert all(isinstance(certfields.hint(c), str) for c in CERTIFICATE_COLUMNS)


# ---- the page ----------------------------------------------------------------------------------
def test_the_page_shows_the_fields_for_the_form_and_keeps_the_rest_apart(client):
    c, _, _ = client
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)         # AS1
    assert "<h1>AS1 AS1-1</h1>" in html and "Details for AS1" in html
    assert html.index('name="area"') < html.index("Other fields") < html.index('name="sl1a"')
    html = c.get("/workpacks/certificates/2").get_data(as_text=True)         # SL1
    assert html.index('name="sl1a"') < html.index("Other fields") < html.index('name="area"')
    html = c.get("/workpacks/certificates/3").get_data(as_text=True)         # SH1
    assert "takes no details of its own" in html and 'name="hdr_title"' in html and 'name="filename"' in html
    for column in CERTIFICATE_COLUMNS:
        assert html.count(f'name="{column}"') == 1


def test_the_engines_hints_are_shown(client):
    c, _, _ = client
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert "Blank = default location" in html and "Without .docx." in html


def test_an_unknown_certificate_is_a_404(client):
    c, _, _ = client
    assert c.get("/workpacks/certificates/99").status_code == 404
    assert c.post("/workpacks/certificates/99", data={"cert_id": "x"}).status_code == 404


def test_saving_a_certificate(client):
    c, tmp, _ = client
    r = c.post("/workpacks/certificates/1", data={"cert_id": "AS1-PL33000", "form": "as1", "equipment": "Pump P-1",
                                                 "area": "Deck", "scope": "Line one\r\nLine two", "folder": "Pumps"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/certificates/1?saved=1")
    saved = row(tmp, 1)
    assert (saved["cert_id"], saved["form"], saved["equipment"], saved["area"], saved["folder"]) == (
        "AS1-PL33000", "AS1", "Pump P-1", "Deck", "Pumps") and saved["scope"] == "Line one\nLine two"
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Saved." in html and "Pump P-1" in html and "Line one\nLine two" in html
    assert "<h1>AS1 AS1-PL33000</h1>" in html
    audit = sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action, detail FROM audit").fetchall()
    assert ("certificate_updated", "AS1 AS1-1") in audit


def test_a_field_left_out_of_a_post_is_not_blanked(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/2", data={"area": "Deck", "equipment": "Skid"})
    c.post("/workpacks/certificates/2", data={"equipment": "Skid 2"})
    assert row(tmp, 2)["area"] == "Deck" and row(tmp, 2)["equipment"] == "Skid 2"


def test_changing_the_form_changes_the_sections_and_keeps_the_values(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/1", data={"form": "AS1", "area": "Deck", "scope": "Check"})
    c.post("/workpacks/certificates/1", data={"form": "sl1", "area": "Deck", "scope": "Check"})
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert "Details for SL1" in html and html.index('name="sl1a"') < html.index("Other fields") < html.index('name="area"')
    assert row(tmp, 1)["area"] == "Deck" and row(tmp, 1)["scope"] == "Check"


def test_refused_saves_change_nothing(client):
    c, tmp, _ = client
    for data, message in [({"cert_id": " "}, "Certificate ID is required"), ({"form": ""}, "Form is required"),
                          ({"cert_id": "SL1-1"}, "already exists")]:
        r = c.post("/workpacks/certificates/1", data={**data, "equipment": "Changed"})
        assert "error=" in r.headers["Location"]
        assert message in c.get(r.headers["Location"]).get_data(as_text=True)
    assert row(tmp, 1)["cert_id"] == "AS1-1" and row(tmp, 1)["equipment"] == ""


def test_typed_text_is_escaped(client):
    c, _, _ = client
    c.post("/workpacks/certificates/1", data={"equipment": '"><script>x()</script>', "scope": "</textarea><b>b</b>"})
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert "<script>x()</script>" not in html and "<b>b</b>" not in html


def test_previous_and_next_certificates(client):
    c, _, _ = client
    first = c.get("/workpacks/certificates/1").get_data(as_text=True)
    middle = c.get("/workpacks/certificates/2").get_data(as_text=True)
    last = c.get("/workpacks/certificates/3").get_data(as_text=True)
    assert "SL1-1 &rarr;" in first and "&larr;" not in first
    assert "&larr; AS1-1" in middle and "SH1-1 &rarr;" in middle
    assert "&larr; SL1-1" in last and "&rarr;" not in last


def test_the_workpack_page_links_to_each_certificate(client):
    c, _, _ = client
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert 'href="/workpacks/certificates/1"' in html and html.count("/workpacks/certificates/2") >= 2   # ID link and Edit


def test_viewers_can_read_but_not_save(client):
    c, _, app = client
    app.config["CTX"]._permissions = {"workpacks.view"}
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert "AS1-1" in html and "Save certificate" not in html and "readonly" in html
    assert c.post("/workpacks/certificates/1", data={"equipment": "x"}).status_code == 403
    app.config["CTX"]._permissions = set()
    assert c.get("/workpacks/certificates/1").status_code == 403
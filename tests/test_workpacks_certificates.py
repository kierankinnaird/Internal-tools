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


# ---- the template-shaped layout ----------------------------------------------------------------
def keys(form):
    return [[c.get("key", "_") for c in row] for t in certfields.layout(form) for row in t["rows"]]


def test_the_layout_puts_each_field_where_the_template_has_it():
    assert keys("AS1") == [["equipment", "location"], ["area", "system"], ["drawing", "subsystem"], ["scope"]]
    cells = certfields.layout("AS1")[0]["rows"]
    assert cells[3][0]["kind"] == "wide" and (cells[0][1]["start"], cells[0][1]["span"]) == (1, 1)
    assert keys("JI1") == [["location", "system", "subsystem"]] and certfields.layout("JI1")[0]["columns"] == 3


def test_a_lone_cell_fills_the_row_or_sits_in_the_right_half_as_the_template_does():
    sl1 = certfields.layout("SL1")[0]["rows"]
    assert keys("SL1") == [["equipment", "location"], ["_", "system"], ["sl1a"]]       # SYSTEM sits right, JI1 REF is left
    assert (sl1[1][0]["kind"], sl1[1][0]["start"], sl1[1][0]["span"]) == ("blank", 0, 1)
    assert (sl1[2][0]["start"], sl1[2][0]["span"]) == (0, 2)
    assert keys("EE12")[2] == ["_", "subsystem"]


def test_the_layout_shows_exactly_the_slots_the_engine_fills():
    for form in list(F.BODY_FIELDS) + ["PL1 A", "TR7", "DM"]:
        wanted = {slot[0] for slot in [*F.BODY_FIELDS.get(form, []), *F.BODY_REPLACE.get(form, [])]}
        assert certfields.placed(form) == wanted, form
    assert certfields.layout("TR7") == [] and certfields.layout("DM") == []


def test_fields_the_template_body_has_no_cell_for_are_listed_after_the_layout():
    assert certfields.unplaced("AS1") == [] and certfields.unplaced("EE12") == ["ee12_description"]
    assert certfields.unplaced("PL1 A") == ["punch_no", "discipline"]


# ---- the page ----------------------------------------------------------------------------------
def test_the_page_shows_the_fields_for_the_form_and_keeps_the_rest_apart(client):
    c, _, _ = client
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)         # AS1
    assert "<h1>AS1 AS1-1</h1>" in html and "Form AS1" in html
    assert html.index('name="area"') < html.index("Other fields") < html.index('name="sl1a"')
    html = c.get("/workpacks/certificates/2").get_data(as_text=True)         # SL1
    assert html.index('name="sl1a"') < html.index("Other fields") < html.index('name="area"')
    c.post("/workpacks/1/certificates", data={"cert_id": "TR7-1", "form": "TR7"})        # a form with no fields of its own
    html = c.get("/workpacks/certificates/4").get_data(as_text=True)
    assert "takes no details of its own" in html and 'name="hdr_title"' in html and 'name="filename"' in html
    for pk in (1, 2, 3, 4):                                                  # every field is on the page exactly once
        html = c.get(f"/workpacks/certificates/{pk}").get_data(as_text=True)
        for column in CERTIFICATE_COLUMNS:
            assert html.count(f'name="{column}"') == 1, (pk, column)


def test_the_page_follows_the_templates_order(client):
    c, _, _ = client
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)         # AS1: EQUIPMENT LOCATION / AREA SYSTEM / ...
    order = [html.index(f'for="f_{n}"') for n in ("equipment", "location", "area", "system", "drawing", "subsystem", "scope")]
    assert order == sorted(order)
    assert html.index('for="f_hdr_title"') < order[0] < html.index("Certificate and output file")


def test_blank_boxes_show_the_workpack_value_they_fall_back_to(client):
    c, _, _ = client
    c.post("/workpacks/1", data={"title": "Wellbay 18 clearance", "location": "Deck 2", "system": "Diesel", "site": "Beryl B",
                                 "project_no": "FCP-9", "workpack_no": "WP-77", "sh1_no": "SH1-5", "mc1_no": "MC1-3"})
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert 'placeholder="Deck 2"' in html and 'placeholder="Diesel"' in html                    # location, system
    assert 'placeholder="Wellbay 18 clearance"' in html and 'placeholder="Beryl B"' in html       # header title, site
    assert 'placeholder="MC1-3"' in html
    for shown in ("FCP-9", "WP-77", "SH1-5"):                                                   # not editable here
        assert f">{shown}</div>" in html and f'value="{shown}"' not in html


def test_project_level_cells_are_shown_but_not_editable(client):
    c, _, _ = client
    c.post("/workpacks/1", data={"title": "T", "handover_title": "Whole skid", "handover_includes": "Pumps"})
    html = c.get("/workpacks/certificates/3").get_data(as_text=True)         # SH1
    assert ">Whole skid</div>" in html and ">Pumps</div>" in html and "Filled in by the tool" in html
    assert 'name="handover_title"' not in html


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
    assert "Form SL1" in html and html.index('name="sl1a"') < html.index("Other fields") < html.index('name="area"')
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
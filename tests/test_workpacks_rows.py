import sqlite3

import pytest
from werkzeug.datastructures import MultiDict

from hosts.standalone import create_app
from modules.workpacks import rowtables
from modules.workpacks.engine import fill_workpack as F
from modules.workpacks.fill import FillService
from modules.workpacks.repo import Repo
from modules.workpacks.store import TemplateStore


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    c = app.test_client()
    c.post("/workpacks/", data={"title": "Wellbay 18 clearance"})                       # workpack 1
    for cert_id, form in [("SL1-1", "SL1"), ("JI1-1", "JI1"), ("EE12-1", "EE12"), ("AS1-1", "AS1"), ("MP1-1", "MP1")]:
        c.post("/workpacks/1/certificates", data={"cert_id": cert_id, "form": form})   # certificates 1 to 5
    return c, tmp_path, app


def lines(*rows):
    """The posted form for a line table: one list per column."""
    cols = ["pid", "line_no", "from_equipment", "to_equipment"]
    return MultiDict([("table", "1")] + [(c, r[i]) for r in rows for i, c in enumerate(cols)])


def saved_rows(tmp, table):
    return sqlite3.connect(tmp / "workpacks.sqlite").execute(
        f"SELECT * FROM {table} ORDER BY certificate_id, position").fetchall()


# ---- reading the posted grid -------------------------------------------------------------------
def test_parse_rows():
    form = MultiDict([("table", "1"), ("tag", "T-1"), ("tag", ""), ("drawing", "D1"), ("drawing", "")])
    assert rowtables.parse_rows(form, ["tag", "drawing"]) == [{"tag": "T-1", "drawing": "D1"}, {"tag": "", "drawing": ""}]
    assert rowtables.parse_rows(MultiDict([("table", "1")]), ["tag", "drawing"]) == []      # every row removed on purpose


def test_a_broken_post_is_refused_whole():
    with pytest.raises(ValueError, match="missing"):
        rowtables.parse_rows(MultiDict([("tag", "T-1"), ("drawing", "D1")]), ["tag", "drawing"])
    with pytest.raises(ValueError, match="incomplete"):
        rowtables.parse_rows(MultiDict([("table", "1"), ("tag", "T-1"), ("tag", "T-2"), ("drawing", "D1")]), ["tag", "drawing"])
    too_many = MultiDict([("table", "1")] + [("tag", "x")] * (rowtables.MAX_ROWS + 1))
    with pytest.raises(ValueError, match="at most"):
        rowtables.parse_rows(too_many, ["tag"])


def test_columns_and_text_come_from_the_engine():
    assert [c["label"] for c in rowtables.columns("line")] == ["P&ID No / ISO No", "Line No", "From equipment", "To equipment"]
    assert rowtables.columns("line")[0]["hint"] == "SL1: P&ID No. MP1: ISO No"
    assert rowtables.columns("joint")[4]["hint"] == "e.g. Seal Ring, RTJ"
    assert rowtables.count_text("line", 1) == "1 line" and rowtables.count_text("joint", 0) == "0 joints"
    assert [rowtables.kind_for(f) for f in ("SL1", "MP1", "JI1", "EE12", "AS1", "SH1")] == [
        "line", "line", "joint", "tag", None, None]


# ---- the page ----------------------------------------------------------------------------------
def test_the_page_offers_the_right_columns_and_blank_rows(client):
    c, _, _ = client
    html = c.get("/workpacks/certificates/1/rows").get_data(as_text=True)                   # SL1: lines
    assert "<h1>Lines for SL1 SL1-1</h1>" in html and "P&amp;ID No / ISO No" in html and 'data-col="to_equipment"' in html
    assert html.count('name="pid"') == rowtables.BLANK_ROWS + 1                             # blank rows + the template row
    html = c.get("/workpacks/certificates/2/rows").get_data(as_text=True)                   # JI1: joints
    assert "Required torque value" in html and 'name="joint_no"' in html and 'name="pid"' not in html
    html = c.get("/workpacks/certificates/3/rows").get_data(as_text=True)                   # EE12: tags
    assert "[TAGS]" in html and 'name="tag"' in html


def test_a_form_with_no_table_has_no_rows_page(client):
    c, _, _ = client
    r = c.get("/workpacks/certificates/4/rows")                                              # AS1
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert "has no table rows" in c.get(r.headers["Location"]).get_data(as_text=True)
    assert c.post("/workpacks/certificates/4/rows", data={"table": "1"}).status_code == 302
    assert c.get("/workpacks/certificates/99/rows").status_code == 404
    assert c.post("/workpacks/certificates/99/rows", data={"table": "1"}).status_code == 404


def test_saving_rows_keeps_order_and_drops_blank_rows(client):
    c, tmp, _ = client
    r = c.post("/workpacks/certificates/1/rows", data=lines(
        ("P-100", '2"-FG-001', "Pump A", "Tank B"), ("", "", "", ""), ("P-101", "3-FG-002", "", "Vent"), ("", "", "", "")))
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/certificates/1/rows?saved=2")
    assert [(x[3], x[4], x[5], x[6]) for x in saved_rows(tmp, "line")] == [
        ("P-100", '2"-FG-001', "Pump A", "Tank B"), ("P-101", "3-FG-002", "", "Vent")]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Saved 2 lines." in html and 'value="P-101"' in html and 'value="2&#34;-FG-001"' in html
    audit = sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action, detail FROM audit").fetchall()
    assert ("rows_saved", "SL1 SL1-1: 2 line rows") in audit


def test_saving_again_replaces_the_rows_and_all_removed_clears_them(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(("A", "1", "", ""), ("B", "2", "", "")))
    c.post("/workpacks/certificates/1/rows", data=lines(("B", "2", "", "")))
    assert [x[3] for x in saved_rows(tmp, "line")] == ["B"]
    r = c.post("/workpacks/certificates/1/rows", data={"table": "1"})
    assert saved_rows(tmp, "line") == [] and "Saved 0 lines." in c.get(r.headers["Location"]).get_data(as_text=True)


def test_joints_and_tags_save_too(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/2/rows", data=MultiDict([
        ("table", "1"), ("joint_no", "J-1"), ("drawing", "D1"), ("size", "6"), ("rating", "300#"), ("joint_type", "RTJ"),
        ("torque", "230")]))
    c.post("/workpacks/certificates/3/rows", data=MultiDict([("table", "1"), ("tag", "TAG-1"), ("tag", "TAG-2"),
                                                           ("drawing", "D9"), ("drawing", "")]))
    assert [x[3:] for x in saved_rows(tmp, "joint")] == [("J-1", "D1", "6", "300#", "RTJ", "230")]
    assert [(x[3], x[4]) for x in saved_rows(tmp, "tag")] == [("TAG-1", "D9"), ("TAG-2", "")]
    assert "Saved 2 tags." in c.get("/workpacks/certificates/3/rows?saved=2").get_data(as_text=True)


def test_refused_saves_change_nothing(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(("KEEP", "1", "", "")))
    for data, message in [({"pid": "WIPE"}, "missing"),
                          (MultiDict([("table", "1"), ("pid", "a"), ("pid", "b"), ("line_no", "1")]), "incomplete")]:
        r = c.post("/workpacks/certificates/1/rows", data=data)
        assert message in c.get(r.headers["Location"]).get_data(as_text=True)
    assert [x[3] for x in saved_rows(tmp, "line")] == ["KEEP"]


def test_typed_text_is_escaped(client):
    c, _, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(('"><script>x()</script>', "1", "", "")))
    assert "<script>x()</script>" not in c.get("/workpacks/certificates/1/rows").get_data(as_text=True)


def test_the_certificate_page_links_to_the_table(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(("A", "1", "", ""), ("B", "2", "", "")))
    html = c.get("/workpacks/certificates/1").get_data(as_text=True)
    assert "<h2>Lines</h2>" in html and "2 lines" in html and 'href="/workpacks/certificates/1/rows"' in html
    assert "Edit lines" in html
    assert "0 joints" in c.get("/workpacks/certificates/2").get_data(as_text=True)
    assert "Edit tags" in c.get("/workpacks/certificates/3").get_data(as_text=True)
    assert "/rows" not in c.get("/workpacks/certificates/4").get_data(as_text=True)         # AS1 has no table


def test_changing_the_form_changes_the_table_that_is_shown(client):
    c, _, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(("A", "1", "", "")))
    c.post("/workpacks/certificates/1", data={"form": "JI1"})
    html = c.get("/workpacks/certificates/1/rows").get_data(as_text=True)
    assert "Joint number" in html and 'name="pid"' not in html and "<h1>Joints for JI1 SL1-1</h1>" in html


def test_viewers_can_read_but_not_save(client):
    c, tmp, app = client
    c.post("/workpacks/certificates/1/rows", data=lines(("A", "1", "", "")))
    app.config["CTX"]._permissions = {"workpacks.view"}
    html = c.get("/workpacks/certificates/1/rows").get_data(as_text=True)
    assert 'value="A"' in html and "data-readonly" in html and "Save lines" not in html and "Add 5 rows" not in html
    assert html.count('name="pid"') == 1                                                    # no blank rows offered
    assert c.post("/workpacks/certificates/1/rows", data=lines(("X", "", "", ""))).status_code == 403
    app.config["CTX"]._permissions = set()
    assert c.get("/workpacks/certificates/1/rows").status_code == 403


def test_the_script_is_served(client):
    c, _, _ = client
    assert c.get("/workpacks/static/rows.js").status_code == 200


# ---- from the grid to the engine ---------------------------------------------------------------
def test_saved_rows_reach_the_engines_input_workbook(client):
    c, tmp, _ = client
    c.post("/workpacks/certificates/1/rows", data=lines(("P-100", '2"-FG-001', "Pump A", "Tank B"), ("P-101", "3-FG-002", "", "Vent")))
    c.post("/workpacks/certificates/2/rows", data=MultiDict([
        ("table", "1"), ("joint_no", "J-1"), ("drawing", "D1"), ("size", "6"), ("rating", "300#"), ("joint_type", "RTJ"),
        ("torque", "230")]))
    c.post("/workpacks/certificates/3/rows", data=MultiDict([("table", "1"), ("tag", "TAG-1"), ("drawing", "D9")]))
    service = FillService(Repo(tmp / "workpacks.sqlite"), TemplateStore(tmp / "none"))
    service.build_workbook(1, tmp / "in.xlsx")
    data = F.read_sheet(str(tmp / "in.xlsx"))
    assert [(r["cert"], r["pid"], r["line"], r["to"]) for r in data["lines"]] == [
        ("SL1-1", "P-100", '2"-FG-001', "Tank B"), ("SL1-1", "P-101", "3-FG-002", "Vent")]
    assert [(r["cert"], r["joint"], r["torque"]) for r in data["joints"]] == [("JI1-1", "J-1", "230")]
    assert [(r["cert"], r["tag"], r["drawing"]) for r in data["tags"]] == [("EE12-1", "TAG-1", "D9")]
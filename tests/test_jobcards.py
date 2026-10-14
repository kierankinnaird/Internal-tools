import pytest

from core.modules import MissingRequirement, Module, mount
from hosts.standalone import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, "tester")
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "WP1", "title": "T"})
    c.post("/jobcards/workpacks/1/jobcards", data={"trade": "Welder"})
    return c, app, tmp_path


def save(c, **kw):
    body = {"title": "J", "trade": "Welder", "flags": ["COSHH", "bogus"], "drawings": [{"number": "D1", "title": "x"}],
            "tasks": []}
    body.update(kw)
    return c.post("/jobcards/cards/1/save", json=body)


def test_numbering_and_duplicate_workpack(client):
    c, app, _ = client
    c.post("/jobcards/workpacks/1/jobcards", data={})
    from modules.jobcards.repo import Repo
    nums = [j["number"] for j in Repo(app.config["CTX"].data_dir / "jobcards.sqlite").list_jobcards(1)]
    assert nums == ["WP1-001", "WP1-002"]
    r = c.post("/jobcards/workpacks", data={"number": "WP1"})
    assert "already+exists" in r.headers["Location"] or "already%20exists" in r.headers["Location"]


def test_save_roundtrip_and_flags_filtered(client):
    c, *_ = client
    r = save(c, tasks=[{"description": "Weld", "qty": "4", "norm_hours": "1.5", "source": "library",
                        "norm_key": "K1", "norm_uom": "weld", "norm_desc": "d", "factor": "1"}])
    j = r.get_json()
    assert j["flags"] == ["COSHH"]
    assert j["tasks"][1]["hours"] == 6 and j["tasks"][1]["source"] == "library"
    assert j["totals"]["library"] == 6


def test_library_without_key_becomes_manual(client):
    c, *_ = client
    j = save(c, tasks=[{"description": "a", "qty": 1, "norm_hours": 1, "source": "library", "norm_key": ""}]).get_json()
    assert j["tasks"][1]["source"] == "manual"


def test_factor_stamp_and_audit(client):
    c, app, tmp = client
    j = save(c, tasks=[{"description": "a", "qty": 1, "norm_hours": 2, "source": "manual", "factor": "1.5",
                        "factor_reason": "Congested"}]).get_json()
    t = j["tasks"][1]
    assert t["factor"] == 1.5 and t["factor_set_by"] == "tester"
    stamp = t["factor_set_at"]
    # saving again without touching the factor keeps the original stamp
    j2 = save(c, tasks=[{"id": t["id"], "description": "b", "qty": 1, "norm_hours": 2, "source": "manual",
                         "factor": "1.5", "factor_reason": "Congested"}]).get_json()
    assert j2["tasks"][1]["factor_set_at"] == stamp and j2["tasks"][1]["id"] == t["id"]
    import sqlite3
    acts = [r[0] for r in sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action FROM audit")]
    assert "factor_changed" in acts


def test_rollup_csv_snapshot_print(client):
    c, *_ = client
    save(c, tasks=[{"description": "a", "qty": 2, "norm_hours": 2, "source": "manual", "basis": "quote"}])
    csv = c.get("/jobcards/workpacks/1/rollup.csv").get_data(as_text=True)
    assert "WP1,Welder,0,6,6" in csv
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "rev A"})
    assert "rev A" in c.get("/jobcards/workpacks/1").get_data(as_text=True)
    assert c.get("/jobcards/cards/1/print").status_code == 200


def test_duplicate_and_delete_jobcard(client):
    c, *_ = client
    save(c, tasks=[{"description": "a", "qty": 2, "norm_hours": 2, "source": "manual"}])
    r = c.post("/jobcards/cards/1/duplicate")
    assert r.headers["Location"].endswith("/cards/2")
    assert "a" in c.get("/jobcards/cards/2").get_data(as_text=True)
    c.post("/jobcards/cards/2/delete")
    assert c.get("/jobcards/cards/2").status_code == 404


def test_norm_picker_with_and_without_norms(tmp_path):
    with_n = create_app(tmp_path / "a", "t").test_client()
    d = with_n.get("/jobcards/api/norm-search?q=weld").get_json()
    assert d["available"] and d["rows"]
    only = create_app(tmp_path / "b", "t", modules=["jobcards"]).test_client()
    assert only.get("/jobcards/api/norm-search?q=weld").get_json()["available"] is False
    assert only.get("/norms/").status_code == 404
    only.post("/jobcards/workpacks", data={"number": "W"})
    only.post("/jobcards/workpacks/1/jobcards", data={})
    assert only.get("/jobcards/cards/1").status_code == 200


def test_factor_permission(tmp_path):
    app = create_app(tmp_path, "t")
    ctx = app.config["CTX"]
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "W"})
    c.post("/jobcards/workpacks/1/jobcards", data={})
    ctx._permissions = {"jobcards.view", "jobcards.edit"}     # no jobcards.factor
    j = c.post("/jobcards/cards/1/save", json={"tasks": [{"description": "a", "qty": 1, "norm_hours": 1, "factor": 3}]}).get_json()
    assert j["tasks"][1]["factor"] == 1


def test_missing_requirement_blocks_mount(tmp_path):
    from flask import Blueprint, Flask
    from core.context import Context
    m = Module("x", "X", "1", lambda c: Blueprint("x", __name__), requires=["norms.lookup"])
    with pytest.raises(MissingRequirement):
        mount(Flask(__name__), m, Context(data_dir=tmp_path))


def test_suggest_tokens_and_service():
    from modules.norms.service import NormsService, suggest_tokens
    assert suggest_tokens("Install the cable glands on junction box") == ["install", "cable", "gland", "junction", "box"]
    assert suggest_tokens("") == [] and suggest_tokens("the and of") == []
    rows = NormsService().suggest("Cut and bevel 6\" sch 40 pipe for welding").rows
    assert rows and all(r["status"] == "OK" for r in rows) and len(rows) <= 5
    assert NormsService().suggest("zzzqqq xxyyzz").rows == []


def test_suggest_endpoint(tmp_path):
    c = create_app(tmp_path / "a", "t").test_client()
    d = c.get("/jobcards/api/norm-suggest", query_string={"q": "install junction box"}).get_json()
    assert d["available"] and d["rows"]
    only = create_app(tmp_path / "b", "t", modules=["jobcards"]).test_client()
    assert only.get("/jobcards/api/norm-suggest?q=install junction box").get_json() == {"available": False, "rows": []}
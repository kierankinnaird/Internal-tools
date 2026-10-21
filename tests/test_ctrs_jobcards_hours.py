"""A workbook linked to a jobcards workpack: Piping sheets take the pipefitters' hours by themselves."""
import sqlite3

import pytest

from core.migrations import migrate
from hosts.standalone import create_app
from pathlib import Path
from modules.ctrs.repo import Repo

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "ctrs" / "migrations"


def work(c, card, qty):
    trade = ("P/Fitter", "Welder")[card - 1]
    c.post(f"/jobcards/cards/{card}/save", json={"title": "J", "trade": trade, "tasks": [
        {"description": "work", "qty": qty, "norm_hours": 1, "basis": "q"}]})


@pytest.fixture
def jobs(tmp_path):
    """The whole app with a jobcards workpack WP1 (a P/Fitter card and a Welder card) and a snapshot of it."""
    app = create_app(tmp_path, "tester")
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "WP1", "title": "Wellbay"})
    for trade in ("P/Fitter", "Welder"):
        c.post("/jobcards/workpacks/1/jobcards", data={"trade": trade})
    work(c, 1, 10), work(c, 2, 5)
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "Rev A"})
    return app, c, tmp_path


def trade_hours(app, snapshot_id=1):
    service = app.config["CTX"].services.get("jobcards.hours")
    return {l["trade"]: l["total"] for l in service.snapshot(snapshot_id)["lines"]}


def lines_of(tmp, ctr_id):
    with sqlite3.connect(tmp / "ctrs.sqlite") as db:
        return db.execute("SELECT description, grp, eng_override, from_snapshot FROM ctr_line WHERE ctr_id=? ORDER BY pos",
                          (ctr_id,)).fetchall()


def resources_of(tmp, ctr_id):
    with sqlite3.connect(tmp / "ctrs.sqlite") as db:
        return db.execute("SELECT name, source, split_pct, rate FROM ctr_resource WHERE ctr_id=? ORDER BY pos", (ctr_id,)).fetchall()


# ---- storage: bringing in only some trades ------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path):
    migrate(tmp_path / "ctrs.sqlite", "ctrs", MIGRATIONS)
    return Repo(tmp_path / "ctrs.sqlite")


SNAP = {"id": 5, "label": "Rev A", "created_at": "2026-10-14T10:00:00", "workpack_number": "WP1",
        "lines": [{"trade": "P/Fitter", "total": 40}, {"trade": "Welder", "total": 12}, {"trade": "Rigger", "total": 0}]}


def test_only_the_named_trades_come_in_and_only_their_old_lines_are_replaced(repo, tmp_path):
    cid = repo.create_ctr({"title": "Piping"}, "k")
    assert repo.import_snapshot(cid, SNAP, "k") == 2                                          # by hand: every trade with hours
    newer = {**SNAP, "id": 6, "lines": [{"trade": "P/Fitter", "total": 55}, {"trade": "Welder", "total": 99}]}
    assert repo.import_snapshot(cid, newer, "k", only=["P/Fitter"]) == 1
    assert {(d, h) for d, _, h, _ in lines_of(tmp_path, cid)} == {("Welder", 12), ("P/Fitter", 55)}   # welder kept as it was
    assert repo.get_ctr(cid)["source_snapshot_id"] == 6


def test_with_resources_each_new_trade_gets_a_resource_once_and_existing_ones_are_left_alone(repo, tmp_path):
    cid = repo.create_ctr({"title": "Piping"}, "k")
    repo.save_ctr(cid, {"resources": [{"name": "Lead Pipefitter", "source": "group:P/Fitter", "split_pct": "60", "rate": "55"}]}, "k")
    repo.import_snapshot(cid, SNAP, "k", with_resources=True)                                  # P/Fitter is taken already; Welder is not
    assert resources_of(tmp_path, cid) == [("Lead Pipefitter", "group:P/Fitter", 60, 55), ("Welder", "group:Welder", 100, None)]
    repo.import_snapshot(cid, SNAP, "k", with_resources=True)                                  # again: nothing doubled
    assert len(resources_of(tmp_path, cid)) == 2
    other = repo.create_ctr({"title": "Other"}, "k")
    repo.import_snapshot(other, SNAP, "k")                                                     # by hand: no resources made
    assert resources_of(tmp_path, other) == []


def test_asking_for_a_trade_the_snapshot_has_no_hours_for_changes_nothing(repo, tmp_path):
    cid = repo.create_ctr({"title": "Piping"}, "k")
    repo.import_snapshot(cid, SNAP, "k", only=["P/Fitter"])
    before = lines_of(tmp_path, cid)
    with pytest.raises(ValueError, match="no Rigger hours"):
        repo.import_snapshot(cid, SNAP, "k", only=["Rigger"])                                  # a trade with 0 hours counts as none
    with pytest.raises(ValueError, match="no P/Fitter hours"):
        repo.import_snapshot(cid, {**SNAP, "lines": []}, "k", only=["P/Fitter"])
    assert lines_of(tmp_path, cid) == before


# ---- the pages -----------------------------------------------------------------------------------------------
def test_a_piping_sheet_takes_the_pipefitter_hours_when_the_workbook_is_made(jobs):
    app, c, tmp = jobs
    r = c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Piping", "Mechanical", "Construction"]})
    assert r.headers["Location"].endswith("/ctrs/estimates/1?hours=1")
    hours = trade_hours(app)
    assert hours["P/Fitter"] > 0 and hours["Welder"] > 0
    assert lines_of(tmp, 1) == [("P/Fitter", "P/Fitter", hours["P/Fitter"], 1)]                  # only the pipefitters, not the welders
    assert lines_of(tmp, 2) == [] and lines_of(tmp, 3) == []                                       # other disciplines are left alone
    assert resources_of(tmp, 1) == [("P/Fitter", "group:P/Fitter", 100, None)]                     # so the hours count; the rate is still to type
    page = c.get(r.headers["Location"]).data.decode()
    assert "Hours brought in from the jobcards on 1 sheet" in page
    assert f">{hours['P/Fitter']}</td>" in page                                                    # the workbook page shows them, not 0
    assert "WP1 - Rev A" in c.get("/ctrs/1").data.decode()                                         # the CTR says which snapshot it used


def test_a_piping_sheet_added_later_is_filled_and_opens_with_a_note(jobs):
    app, c, tmp = jobs
    c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1"})
    r = c.post("/ctrs/estimates/1/ctrs", data={"title": " piping "})                               # case and spaces do not matter
    assert r.headers["Location"].endswith("/ctrs/1?imported=1")
    assert lines_of(tmp, 1)[0][:3] == ("P/Fitter", "P/Fitter", trade_hours(app)["P/Fitter"])
    assert b"1 trade line brought in from the jobcards" in c.get(r.headers["Location"]).data
    r = c.post("/ctrs/estimates/1/ctrs", data={"title": "Construction - Piping"})                  # not the discipline's name: untouched
    assert r.headers["Location"].endswith("/ctrs/2") and lines_of(tmp, 2) == []


def test_without_a_jobcards_link_nothing_is_filled(jobs):
    _, c, tmp = jobs
    c.post("/ctrs/", data={"title": "BB", "disciplines": ["Piping"]})
    assert lines_of(tmp, 1) == []
    r = c.post("/ctrs/estimates/1/update-hours")
    assert b"Choose a jobcards workpack first" in c.get(r.headers["Location"]).data


def test_choosing_a_workpack_later_fills_the_piping_sheets_at_once(jobs):
    app, c, tmp = jobs
    c.post("/ctrs/", data={"title": "BB", "disciplines": ["Piping"]})
    r = c.post("/ctrs/estimates/1", data={"jobcards_workpack": "WP1"})                            # only this field is sent
    assert "saved=1" in r.headers["Location"] and "hours=1" in r.headers["Location"]
    assert lines_of(tmp, 1)[0][2] == trade_hours(app)["P/Fitter"]
    assert "hours=" not in c.post("/ctrs/estimates/1", data={"title": "BB2"}).headers["Location"]   # saving again brings in nothing
    assert lines_of(tmp, 1)[0][2] == trade_hours(app)["P/Fitter"] and len(lines_of(tmp, 1)) == 1
    page = c.get("/ctrs/estimates/1").data.decode()
    assert 'value="WP1" selected' in page and "Update hours from jobcards" in page


def test_a_workpack_with_no_snapshot_cannot_be_chosen(jobs):
    _, c, _ = jobs
    r = c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "NOPE", "disciplines": ["Piping"]})
    assert b"no snapshot of a jobcards workpack numbered NOPE" in c.get(r.headers["Location"]).data
    assert c.get("/ctrs/estimates/1").status_code == 404                                           # nothing was made
    c.post("/ctrs/", data={"title": "BB"})
    r = c.post("/ctrs/estimates/1", data={"jobcards_workpack": "NOPE"})
    assert b"numbered NOPE" in c.get(r.headers["Location"]).data


def test_updating_brings_in_the_newest_snapshot_and_keeps_everything_else(jobs):
    app, c, tmp = jobs
    c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Piping"]})
    c.post("/ctrs/1/import-hours", data={"snapshot_id": "1"})                                      # by hand: every trade, so Welder too
    typed = [{"description": "Isometrics", "qty": "2", "eng_norm": "3"}]
    imported = [{"description": d, "grp": g, "eng_override": h, "from_snapshot": 1} for d, g, h, _ in lines_of(tmp, 1)]
    assert c.post("/ctrs/1/save", json={"lines": typed + imported}).status_code == 200
    work(c, 1, 30)
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "Rev B"})                            # snapshot 2: more pipefitter hours
    r = c.post("/ctrs/estimates/1/update-hours")
    assert "hours=1" in r.headers["Location"]
    new = trade_hours(app, 2)
    assert new["P/Fitter"] > trade_hours(app, 1)["P/Fitter"]
    rows = {d: (h, f) for d, _, h, f in lines_of(tmp, 1)}
    assert rows["P/Fitter"] == (new["P/Fitter"], 1)                                                # refreshed
    assert rows["Welder"] == (trade_hours(app, 1)["Welder"], 1)                                    # another trade: kept as it was
    assert rows["Isometrics"][1] == 0 and len(rows) == 3                                           # a typed line: kept, nothing doubled
    assert "WP1 - Rev B" in c.get("/ctrs/1").data.decode()
    assert [r[1] for r in resources_of(tmp, 1)] == ["group:P/Fitter"]                              # one resource, however often it is updated
    c.post("/ctrs/estimates/1/update-hours")
    assert [r[1] for r in resources_of(tmp, 1)] == ["group:P/Fitter"]


def test_a_snapshot_with_no_pipefitter_hours_says_so_and_keeps_what_was_there(jobs):
    _, c, tmp = jobs
    c.post("/jobcards/workpacks", data={"number": "WP2", "title": "Deck"})
    c.post("/jobcards/workpacks/2/jobcards", data={"trade": "Welder"})
    c.post("/jobcards/cards/3/save", json={"title": "J", "trade": "Welder",
                                          "tasks": [{"description": "w", "qty": 3, "norm_hours": 1, "basis": "q"}]})
    c.post("/jobcards/workpacks/2/snapshots", data={"label": "Welding only"})
    c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Piping"]})
    before = lines_of(tmp, 1)
    r = c.post("/ctrs/estimates/1", data={"jobcards_workpack": "WP2"})
    assert "That snapshot has no P/Fitter hours in it" in c.get(r.headers["Location"]).data.decode()
    assert lines_of(tmp, 1) == before


def test_a_workbook_with_no_automatic_sheet_says_what_it_would_have_filled(jobs):
    _, c, _ = jobs
    c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Mechanical"]})
    r = c.post("/ctrs/estimates/1/update-hours")
    assert b"Piping takes P/Fitter" in c.get(r.headers["Location"]).data


def test_a_viewer_cannot_update_hours(jobs):
    app, c, _ = jobs
    c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Piping"]})
    app.config["CTX"]._permissions = {"ctrs.view"}
    assert c.post("/ctrs/estimates/1/update-hours").status_code == 403
    page = c.get("/ctrs/estimates/1").data.decode()
    assert "Update hours from jobcards" not in page and "Use this workpack" not in page and "WP1" in page


def test_the_pages_work_without_the_jobcards_module(tmp_path):
    app = create_app(tmp_path, "tester", modules=["ctrs"])
    c = app.test_client()
    r = c.post("/ctrs/", data={"title": "BB", "jobcards_workpack": "WP1", "disciplines": ["Piping"]})   # ignored: nothing to pick from
    page = c.get(r.headers["Location"]).data.decode()
    assert "Hours from the jobcards" not in page and c.get("/ctrs/").status_code == 200
    assert c.post("/ctrs/estimates/1/ctrs", data={"title": "Piping"}).status_code == 302
    assert c.post("/ctrs/estimates/1", data={"jobcards_workpack": "WP1"}).headers["Location"].endswith("saved=1")


def test_the_choice_of_workpack_is_audited_with_the_workbook(jobs):
    app, c, tmp = jobs
    c.post("/ctrs/", data={"title": "BB", "disciplines": ["Piping"]})
    c.post("/ctrs/estimates/1", data={"jobcards_workpack": "WP1"})
    with sqlite3.connect(tmp / "audit.sqlite") as db:
        actions = [r[0] for r in db.execute("SELECT action FROM audit WHERE module='ctrs' ORDER BY id")]
    assert actions[-2:] == ["estimate_saved", "ctr_hours_imported"]

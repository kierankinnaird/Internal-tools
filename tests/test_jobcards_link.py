import shutil
import sqlite3
from pathlib import Path

import pytest

from core.migrations import migrate
from hosts.standalone import create_app
from modules.jobcards.constants import TRADES
from modules.jobcards.link import MAX_CREATE, JobcardsLink
from modules.jobcards.repo import Repo

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "jobcards" / "migrations"


@pytest.fixture()
def link(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", MIGRATIONS)
    events = []
    service = JobcardsLink(db, audit=lambda action, detail: events.append((action, detail)))
    service.events = events
    service.db = db
    return service


def counts(link):
    with sqlite3.connect(link.db) as c:
        return (c.execute("SELECT COUNT(*) FROM workpack").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM jobcard").fetchone()[0])


def ref_of(link, wp_id):
    with sqlite3.connect(link.db) as c:
        return c.execute("SELECT workpacks_ref FROM workpack WHERE id=?", (wp_id,)).fetchone()[0]


def plain(number="JW1", **more):
    return dict({"number": number, "title": "Title"}, **more)


# ---- the migration ---------------------------------------------------------------------------
def test_migration_adds_an_empty_link_and_keeps_existing_rows(tmp_path):
    early = tmp_path / "early"
    early.mkdir()
    for name in ("0001_initial.sql", "0002_print_fields.sql"):
        shutil.copy(MIGRATIONS / name, early / name)
    db = tmp_path / "jobcards.sqlite"
    assert migrate(db, "jobcards", early) == 2
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO workpack (number, title, created_at) VALUES ('OLD', 'Old one', 'now')")
        c.execute("INSERT INTO jobcard (workpack_id, seq, number, updated_at) VALUES (1, 1, 'OLD-001', 'now')")
    assert migrate(db, "jobcards", MIGRATIONS) == 1                      # only the new file is applied
    assert migrate(db, "jobcards", MIGRATIONS) == 0
    with sqlite3.connect(db) as c:
        assert "workpacks_ref" in {r[1] for r in c.execute("PRAGMA table_info(workpack)")}
        assert c.execute("SELECT number, title, workpacks_ref FROM workpack").fetchall() == [("OLD", "Old one", None)]
        assert c.execute("SELECT COUNT(*) FROM jobcard").fetchone()[0] == 1
        assert "ix_workpack_ref" in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}


# ---- reading ---------------------------------------------------------------------------------
def test_trades_are_the_modules_trades(link):
    assert link.trades() == TRADES
    link.trades().append("x")
    assert link.trades() == TRADES                                       # a copy, not the module's own list


def test_available_lists_unlinked_workpacks_newest_first_with_counts(link):
    repo = Repo(link.db)
    a = repo.create_workpack({"number": "A", "title": "First"}, "k")
    b = repo.create_workpack({"number": "B", "title": "Second"}, "k")
    repo.create_jobcard(b, "k")
    repo.create_jobcard(b, "k")
    assert link.available() == [{"id": b, "number": "B", "title": "Second", "jobcards": 2},
                                {"id": a, "number": "A", "title": "First", "jobcards": 0}]
    link.link(b, 7, "k")
    assert [w["number"] for w in link.available()] == ["A"]


def test_linked_gives_the_workpacks_and_a_summary_of_their_jobcards(link):
    wp = link.create_for(5, "k", plain("J1", asset="Pump", location="Deck", discipline="Mech", fcp_no="FCP9"),
                         count=2, trade="Welder")
    repo = Repo(link.db)
    first = repo.list_jobcards(wp)[0]
    repo.save_jobcard(first["id"], {"title": "Weld it", "trade": "Welder", "revision": "B", "tasks": [
        {"description": "a", "qty": 2, "norm_hours": 3, "source": "manual", "basis": "quote"},
        {"description": "no qty", "norm_hours": 1, "source": "manual", "basis": "quote"}]}, "k")
    (result,) = link.linked(5)
    assert result["id"] == wp and result["number"] == "J1" and result["title"] == "Title"
    assert (result["asset"], result["location"], result["discipline"], result["fcp_no"]) == ("Pump", "Deck", "Mech", "FCP9")
    one, two = result["jobcards"]
    assert one["id"] == first["id"] and one["number"] == "J1-001" and one["title"] == "Weld it"
    assert one["trade"] == "Welder" and one["revision"] == "B"
    assert one["tasks"] == 2 and one["warnings"] == 1 and one["totals"]["total"] == 6
    assert two["number"] == "J1-002" and two["tasks"] == 0 and two["warnings"] == 0
    assert link.linked(99) == []


def test_linked_is_ordered_by_id_and_only_for_that_ref(link):
    a = link.create_for(1, "k", plain("A"))
    link.create_for(2, "k", plain("B"))
    c = link.create_for(1, "k", plain("C"))
    assert [w["id"] for w in link.linked(1)] == [a, c]


# ---- create_for ------------------------------------------------------------------------------
def test_create_for_makes_a_linked_workpack_with_numbered_jobcards(link):
    wp = link.create_for(3, "kieran", plain("JW1", asset="A1"), count=3, trade="Rigger")
    assert ref_of(link, wp) == 3
    jcs = Repo(link.db).list_jobcards(wp)
    assert [j["number"] for j in jcs] == ["JW1-001", "JW1-002", "JW1-003"]
    assert {j["trade"] for j in jcs} == {"Rigger"} and jcs[0]["asset"] == "A1"
    assert ("workpack_linked", "JW1 -> workpack 3") in link.events


def test_create_for_with_no_jobcards_and_with_the_most_allowed(link):
    assert link.linked(1) == []
    wp = link.create_for(1, "k", plain("EMPTY"), count=0)
    assert counts(link) == (1, 0) and ref_of(link, wp) == 1
    link.create_for(1, "k", plain("MANY"), count=MAX_CREATE)
    assert counts(link) == (2, MAX_CREATE)


def test_an_unknown_trade_becomes_no_trade(link):
    wp = link.create_for(1, "k", plain(), count=1, trade="Astronaut")
    assert Repo(link.db).list_jobcards(wp)[0]["trade"] == ""


def test_other_fields_are_optional_and_none_is_blank(link):
    wp = link.create_for(1, "k", {"number": "BARE", "title": None, "location": None})
    row = Repo(link.db).get_workpack(wp)
    assert row["number"] == "BARE" and row["title"] == "" and row["location"] == "" and row["jobcard_prefix"] == "BARE-"


@pytest.mark.parametrize("count", [-1, MAX_CREATE + 1, "x", "3", 2.5, None, True])
def test_bad_counts_are_refused_and_leave_nothing_behind(link, count):
    with pytest.raises(ValueError):
        link.create_for(1, "k", plain(), count=count)
    assert counts(link) == (0, 0)


def test_a_missing_or_duplicate_number_leaves_nothing_behind(link):
    with pytest.raises(ValueError):
        link.create_for(1, "k", {"number": "  ", "title": "x"}, count=2)
    with pytest.raises(ValueError):
        link.create_for(1, "k", {"title": "x"}, count=2)
    assert counts(link) == (0, 0)
    link.create_for(1, "k", plain("DUP"), count=1)
    with pytest.raises(ValueError, match="already exists"):
        link.create_for(2, "k", plain("DUP"), count=4)
    assert counts(link) == (1, 1) and link.linked(2) == []


def test_a_failure_part_way_removes_the_workpack_and_its_jobcards(link, monkeypatch):
    real = Repo.create_jobcard
    calls = []

    def flaky(self, wp_id, user, trade=""):
        calls.append(wp_id)
        if len(calls) == 3:
            raise RuntimeError("disk full")
        return real(self, wp_id, user, trade)

    monkeypatch.setattr(Repo, "create_jobcard", flaky)
    with pytest.raises(RuntimeError, match="disk full"):
        link.create_for(1, "k", plain("HALF"), count=5)
    assert counts(link) == (0, 0)
    assert link.linked(1) == [] and link.available() == []
    assert not any(action == "workpack_linked" for action, _ in link.events)


# ---- references ------------------------------------------------------------------------------
@pytest.mark.parametrize("ref", [0, -2, "", None, "x", "3", 1.5, True])
def test_a_bad_reference_is_refused_everywhere(link, ref):
    wp = Repo(link.db).create_workpack({"number": "A"}, "k")
    for call in (lambda: link.create_for(ref, "k", plain()), lambda: link.linked(ref),
                 lambda: link.link(wp, ref, "k"), lambda: link.unlink_all(ref, "k")):
        with pytest.raises(ValueError, match="A workpack is required"):
            call()
    assert counts(link) == (1, 0) and ref_of(link, wp) is None


# ---- link and unlink -------------------------------------------------------------------------
def test_link_unlink_and_relink(link):
    wp = Repo(link.db).create_workpack({"number": "A"}, "k")
    link.link(wp, 4, "k")
    assert ref_of(link, wp) == 4 and [w["id"] for w in link.linked(4)] == [wp]
    link.link(wp, 4, "k")                                                # same again: nothing happens
    assert [a for a, _ in link.events].count("workpack_linked") == 1
    link.unlink(wp, "k")
    assert ref_of(link, wp) is None and [a for a, _ in link.events][-1] == "workpack_unlinked"
    link.unlink(wp, "k")                                                 # not linked: nothing happens
    assert [a for a, _ in link.events].count("workpack_unlinked") == 1
    link.link(wp, 9, "k")                                                # free to go somewhere else
    assert ref_of(link, wp) == 9


def test_a_workpack_linked_elsewhere_is_refused(link):
    wp = Repo(link.db).create_workpack({"number": "A"}, "k")
    link.link(wp, 4, "k")
    with pytest.raises(ValueError) as e:
        link.link(wp, 5, "k")
    assert str(e.value) == "A is already linked to another workpack. Unlink it there first"
    assert ref_of(link, wp) == 4


def test_unknown_ids_are_refused(link):
    for bad in (999, 0, -1, None, "x", True):
        with pytest.raises(ValueError, match="No such jobcards workpack"):
            link.link(bad, 1, "k")
        with pytest.raises(ValueError, match="No such jobcards workpack"):
            link.unlink(bad, "k")


def test_many_workpacks_can_share_one_reference(link):
    repo = Repo(link.db)
    ids = [repo.create_workpack({"number": n}, "k") for n in ("A", "B", "C")]
    for i in ids:
        link.link(i, 1, "k")
    assert [w["id"] for w in link.linked(1)] == ids


def test_unlink_all_keeps_the_jobcards(link):
    a = link.create_for(1, "k", plain("A"), count=2)
    b = link.create_for(1, "k", plain("B"), count=1)
    other = link.create_for(2, "k", plain("C"), count=1)
    link.events.clear()
    assert link.unlink_all(1, "k") == 2
    assert counts(link) == (3, 4) and ref_of(link, a) is None and ref_of(link, b) is None and ref_of(link, other) == 2
    assert [a for a, _ in link.events] == ["workpack_unlinked"]
    assert link.unlink_all(1, "k") == 0 and len(link.events) == 1        # nothing left: no second audit entry


def test_deleting_a_jobcards_workpack_removes_its_link(link):
    wp = link.create_for(1, "k", plain("A"), count=1)
    Repo(link.db).delete_workpack(wp)
    assert link.linked(1) == [] and link.available() == [] and counts(link) == (0, 0)


# ---- inside the app --------------------------------------------------------------------------
def test_the_app_registers_the_service_and_audits_through_the_context(tmp_path):
    app = create_app(tmp_path, "tester", modules=["jobcards"])
    service = app.config["CTX"].services.get("jobcards.link")
    assert isinstance(service, JobcardsLink)
    wp = service.create_for(1, "tester", plain("APP1"), count=1)
    assert service.linked(1)[0]["id"] == wp
    rows = sqlite3.connect(tmp_path / "audit.sqlite").execute(
        "SELECT user, module, action, detail FROM audit WHERE action='workpack_linked'").fetchall()
    assert rows == [("tester", "jobcards", "workpack_linked", "APP1 -> workpack 1")]


def test_there_is_no_service_when_only_workpacks_is_mounted(tmp_path):
    app = create_app(tmp_path, "tester", modules=["workpacks"])
    assert app.config["CTX"].services.get("jobcards.link") is None
    assert not app.config["CTX"].services.has("jobcards.link")


def test_the_jobcards_pages_still_work_on_their_own(tmp_path):
    c = create_app(tmp_path, "tester", modules=["jobcards"]).test_client()
    assert c.post("/jobcards/workpacks", data={"number": "WP1", "title": "T"}).status_code == 302
    assert c.post("/jobcards/workpacks/1/jobcards", data={"trade": "Welder"}).status_code == 302
    assert "WP1" in c.get("/jobcards/").get_data(as_text=True)
    assert "WP1-001" in c.get("/jobcards/workpacks/1").get_data(as_text=True)
    assert c.get("/jobcards/cards/1").status_code == 200
    assert c.get("/jobcards/cards/1/print").status_code == 200

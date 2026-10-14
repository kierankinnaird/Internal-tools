from pathlib import Path

import pytest

from core.migrations import migrate
from modules.jobcards.repo import Repo

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "jobcards" / "migrations"


@pytest.fixture()
def repo(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", MIGRATIONS)
    events = []
    r = Repo(db, audit=lambda action, detail: events.append((action, detail)))
    r.events = events
    r.wp = r.create_workpack({"number": "WP1", "title": "T"}, "kieran")
    return r


def task(**kw):
    base = {"description": "d", "qty": 1, "norm_hours": 2, "source": "manual", "basis": "quote", "factor": 1}
    base.update(kw)
    return base


def test_workpack_needs_a_number_and_a_unique_one(repo):
    with pytest.raises(ValueError):
        repo.create_workpack({"number": "  "}, "k")
    with pytest.raises(ValueError):
        repo.create_workpack({"number": "WP1"}, "k")


def test_jobcard_numbers_follow_the_workpack_prefix(repo):
    repo.create_jobcard(repo.wp, "k")
    repo.create_jobcard(repo.wp, "k")
    assert [j["number"] for j in repo.list_jobcards(repo.wp)] == ["WP1-001", "WP1-002"]


def test_save_round_trip_filters_unknown_flags(repo):
    jc = repo.create_jobcard(repo.wp, "k", "Welder")
    saved = repo.save_jobcard(jc, {"title": "J", "trade": "Welder", "flags": ["COSHH", "bogus"],
                                   "drawings": [{"number": "D1", "title": "x"}, {"number": "", "title": ""}],
                                   "tasks": [task(qty="4", norm_hours="1.5", source="library", norm_key="K1")]}, "k")
    assert saved["flags"] == ["COSHH"] and saved["drawings"] == [{"number": "D1", "title": "x"}]
    assert saved["tasks"][1]["source"] == "library" and saved["totals"]["library"] == 6      # between the two standard tasks


def test_library_line_without_a_key_is_stored_as_manual(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [task(source="library", norm_key="")]}, "k")
    assert saved["tasks"][1]["source"] == "manual"


def test_factor_is_stamped_and_audited_only_when_it_changes(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    t = repo.save_jobcard(jc, {"tasks": [task(factor="1.5", factor_reason="Congested")]}, "alex")["tasks"][1]
    assert t["factor"] == 1.5 and t["factor_set_by"] == "alex"
    again = repo.save_jobcard(jc, {"tasks": [dict(task(factor="1.5", factor_reason="Congested"), id=t["id"], description="b")]}, "someone-else")["tasks"][1]
    assert again["id"] == t["id"] and again["factor_set_by"] == "alex" and again["factor_set_at"] == t["factor_set_at"]
    assert [e for e in repo.events if e[0] == "factor_changed"] == [("factor_changed", "WP1-001 line 2: factor set to 1.5")]


def test_removed_tasks_are_deleted(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first = repo.save_jobcard(jc, {"tasks": [task(), task(description="e")]}, "k")["tasks"]       # 2 standard + 2 of ours
    left = repo.save_jobcard(jc, {"tasks": [dict(task(), id=first[1]["id"])]}, "k")["tasks"]
    assert [t["id"] for t in left] == [first[0]["id"], first[1]["id"], first[3]["id"]]       # ours: one removed; standard ones kept


def test_duplicate_copies_content_into_a_new_card(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    repo.save_jobcard(jc, {"title": "Orig", "flags": ["COSHH"], "tasks": [task()]}, "k")
    copy = repo.get_jobcard(repo.duplicate_jobcard(jc, "k"))
    assert copy["number"] == "WP1-002" and copy["title"] == "Orig" and copy["flags"] == ["COSHH"] and len(copy["tasks"]) == 3


def test_rollup_and_snapshots_are_frozen(repo):
    jc = repo.create_jobcard(repo.wp, "k", "Welder")
    repo.save_jobcard(jc, {"trade": "Welder", "tasks": [task(qty=2, norm_hours=2)]}, "k")
    assert repo.rollup(repo.wp) == [{"trade": "Welder", "library": 0.0, "manual": 6.0, "total": 6.0}]     # 4 + 2 standard
    repo.create_snapshot(repo.wp, "rev A", "k")
    repo.save_jobcard(jc, {"trade": "Welder", "tasks": [task(qty=10, norm_hours=2)]}, "k")
    snap = repo.list_snapshots(repo.wp)[0]
    assert snap["label"] == "rev A" and snap["lines"][0]["manual"] == 6.0


def test_deleting_a_workpack_is_audited(repo):
    repo.delete_workpack(repo.wp)
    assert repo.get_workpack(repo.wp) is None and ("workpack_deleted", "WP1") in repo.events
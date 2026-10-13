import sqlite3
from pathlib import Path

import pytest

from core.migrations import migrate
from modules.workpacks.fields import WORKPACK_COLUMNS
from modules.workpacks.repo import Repo, clean

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "workpacks" / "migrations"


@pytest.fixture()
def repo(tmp_path):
    db = tmp_path / "workpacks.sqlite"
    migrate(db, "workpacks", MIGRATIONS)
    events = []
    r = Repo(db, audit=lambda action, detail: events.append((action, detail)))
    r.events = events
    return r


def test_every_workpack_field_is_a_real_column(tmp_path):
    db = tmp_path / "w.sqlite"
    migrate(db, "workpacks", MIGRATIONS)
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(workpack)")}
    assert set(WORKPACK_COLUMNS) <= cols


def test_clean_tidies_what_people_paste():
    assert clean(None) == "" and clean("  x  ") == "x" and clean(230.0) == "230" and clean(1.5) == "1.5"
    assert clean("a\r\nb\rc") == "a\nb\nc"


def test_create_and_read_back(repo):
    wp = repo.create_workpack({"title": "  Wellbay 18  ", "project_no": "FCP-1", "handover_includes": "a\r\nb"}, "kieran")
    got = repo.get_workpack(wp)
    assert got["title"] == "Wellbay 18" and got["project_no"] == "FCP-1" and got["handover_includes"] == "a\nb"
    assert got["site"] == "" and got["created_by"] == "kieran" and got["updated_by"] == "kieran"
    assert repo.events == [("workpack_created", "Wellbay 18")]


def test_title_is_required(repo):
    with pytest.raises(ValueError):
        repo.create_workpack({"title": "   "}, "k")
    wp = repo.create_workpack({"title": "T"}, "k")
    with pytest.raises(ValueError):
        repo.update_workpack(wp, {"title": ""}, "k")


def test_update_changes_only_the_fields_given(repo):
    wp = repo.create_workpack({"title": "T", "site": "Alpha", "system": "S1"}, "a")
    out = repo.update_workpack(wp, {"site": "Bravo", "unknown": "ignored"}, "b")
    assert (out["title"], out["site"], out["system"]) == ("T", "Bravo", "S1")
    assert out["updated_by"] == "b" and out["created_by"] == "a"


def test_update_missing_workpack(repo):
    with pytest.raises(ValueError):
        repo.update_workpack(999, {"site": "x"}, "k")


def test_list_is_newest_first_with_certificate_counts(repo):
    a, b = repo.create_workpack({"title": "A"}, "k"), repo.create_workpack({"title": "B"}, "k")
    with repo._db() as db:
        db.execute("INSERT INTO certificate (workpack_id, cert_id, form) VALUES (?,?,?)", (a, "AS1-1", "AS1"))
    rows = repo.list_workpacks()
    assert [r["title"] for r in rows] == ["B", "A"] and [r["certificates"] for r in rows] == [0, 1]


def test_delete_removes_it_and_is_audited(repo):
    wp = repo.create_workpack({"title": "Gone"}, "k")
    repo.delete_workpack(wp)
    assert repo.get_workpack(wp) is None and repo.list_workpacks() == []
    assert repo.events[-1] == ("workpack_deleted", "Gone")
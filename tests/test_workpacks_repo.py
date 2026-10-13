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


# ---- certificates ------------------------------------------------------------------------------
@pytest.fixture()
def wp(repo):
    return repo.create_workpack({"title": "T"}, "k")


def test_add_and_read_back_a_certificate(repo, wp):
    c = repo.add_certificate(wp, {"cert_id": " AS1-PL1 ", "form": "AS1", "equipment": "Pump", "scope": "a\r\nb"}, "kieran")
    got = repo.get_certificate(c)
    assert (got["cert_id"], got["form"], got["equipment"], got["scope"]) == ("AS1-PL1", "AS1", "Pump", "a\nb")
    assert got["workpack_id"] == wp and got["area"] == ""
    assert repo.events[-1] == ("certificate_added", "AS1 AS1-PL1")


def test_certificate_needs_an_id_a_form_and_a_workpack(repo, wp):
    with pytest.raises(ValueError):
        repo.add_certificate(wp, {"cert_id": " ", "form": "AS1"}, "k")
    with pytest.raises(ValueError):
        repo.add_certificate(wp, {"cert_id": "X", "form": ""}, "k")
    with pytest.raises(ValueError):
        repo.add_certificate(999, {"cert_id": "X", "form": "AS1"}, "k")


def test_certificate_id_must_be_unique_within_the_workpack(repo, wp):
    repo.add_certificate(wp, {"cert_id": "SL1-1", "form": "SL1"}, "k")
    with pytest.raises(ValueError, match="already exists"):
        repo.add_certificate(wp, {"cert_id": "SL1-1", "form": "SL1"}, "k")
    other = repo.create_workpack({"title": "Other"}, "k")
    repo.add_certificate(other, {"cert_id": "SL1-1", "form": "SL1"}, "k")


def test_certificates_keep_the_order_they_were_added_in(repo, wp):
    for n in ("B", "A", "C"):
        repo.add_certificate(wp, {"cert_id": n, "form": "AS1"}, "k")
    assert [c["cert_id"] for c in repo.list_certificates(wp)] == ["B", "A", "C"]


def test_update_certificate_changes_only_what_is_given(repo, wp):
    c = repo.add_certificate(wp, {"cert_id": "E1", "form": "EE12", "equipment": "Panel", "system": "S"}, "k")
    out = repo.update_certificate(c, {"system": "S2", "nonsense": "x"}, "k")
    assert (out["equipment"], out["system"], out["cert_id"], out["form"]) == ("Panel", "S2", "E1", "EE12")


def test_update_can_rename_but_not_collide_or_blank(repo, wp):
    a = repo.add_certificate(wp, {"cert_id": "A", "form": "AS1"}, "k")
    repo.add_certificate(wp, {"cert_id": "B", "form": "AS1"}, "k")
    assert repo.update_certificate(a, {"cert_id": "A2", "form": "MP1"}, "k")["form"] == "MP1"
    assert repo.update_certificate(a, {"cert_id": "A2"}, "k")["cert_id"] == "A2"
    with pytest.raises(ValueError, match="already exists"):
        repo.update_certificate(a, {"cert_id": "B"}, "k")
    with pytest.raises(ValueError):
        repo.update_certificate(a, {"cert_id": ""}, "k")
    with pytest.raises(ValueError):
        repo.update_certificate(a, {"form": " "}, "k")
    with pytest.raises(ValueError):
        repo.update_certificate(999, {"area": "x"}, "k")


def test_changing_a_certificate_marks_the_workpack_updated(repo, wp):
    before = repo.get_workpack(wp)
    c = repo.add_certificate(wp, {"cert_id": "A", "form": "AS1"}, "someone")
    assert repo.get_workpack(wp)["updated_by"] == "someone"
    repo.update_certificate(c, {"area": "x"}, "another")
    assert repo.get_workpack(wp)["updated_by"] == "another" and before["created_by"] == "k"


def test_delete_certificate_takes_its_rows_with_it(repo, wp):
    c = repo.add_certificate(wp, {"cert_id": "J", "form": "JI1"}, "k")
    with repo._db() as db:
        db.execute("INSERT INTO joint (certificate_id, joint_no) VALUES (?, 'J1')", (c,))
    repo.delete_certificate(c, "k")
    assert repo.get_certificate(c) is None
    with repo._db() as db:
        assert db.execute("SELECT COUNT(*) FROM joint").fetchone()[0] == 0
    repo.delete_certificate(c, "k")  # deleting twice is harmless
    assert repo.events[-1] == ("certificate_deleted", "JI1 J")


def test_list_counts_the_rows_under_each_certificate(repo, wp):
    c = repo.add_certificate(wp, {"cert_id": "S", "form": "SL1"}, "k")
    with repo._db() as db:
        db.executemany("INSERT INTO line (certificate_id, pid) VALUES (?, ?)", [(c, "P1"), (c, "P2")])
    got = repo.list_certificates(wp)[0]
    assert (got["line_count"], got["joint_count"], got["tag_count"]) == (2, 0, 0)
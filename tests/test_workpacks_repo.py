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


# ---- table rows --------------------------------------------------------------------------------
def make(repo, wp, cert_id, form, **extra):
    return repo.add_certificate(wp, {"cert_id": cert_id, "form": form, **extra}, "k")


def test_rows_round_trip_in_order(repo, wp):
    c = make(repo, wp, "J1", "JI1")
    saved = repo.replace_rows(c, "joint", [
        {"joint_no": "J-2", "size": 6, "rating": "300#", "joint_type": "RTJ", "torque": 230.0},
        {"joint_no": "J-1", "drawing": "D1"},
    ], "k")
    assert saved == 2
    rows = repo.get_rows(c, "joint")
    assert [r["joint_no"] for r in rows] == ["J-2", "J-1"]
    assert rows[0] == {"joint_no": "J-2", "drawing": "", "size": "6", "rating": "300#", "joint_type": "RTJ", "torque": "230"}


def test_blank_rows_are_dropped_and_saving_replaces_what_was_there(repo, wp):
    c = make(repo, wp, "E1", "EE12")
    repo.replace_rows(c, "tag", [{"tag": "T1"}, {"tag": "T2"}, {"tag": " ", "drawing": ""}, {}], "k")
    assert [r["tag"] for r in repo.get_rows(c, "tag")] == ["T1", "T2"]
    repo.replace_rows(c, "tag", [{"tag": "T9", "drawing": "D9"}], "k")
    assert repo.get_rows(c, "tag") == [{"tag": "T9", "drawing": "D9"}]
    assert repo.replace_rows(c, "tag", [], "k") == 0 and repo.get_rows(c, "tag") == []


def test_unknown_keys_in_a_row_are_ignored(repo, wp):
    c = make(repo, wp, "S1", "SL1")
    repo.replace_rows(c, "line", [{"pid": "P-1", "line_no": "L1", "bogus": "x"}], "k")
    assert repo.get_rows(c, "line") == [{"pid": "P-1", "line_no": "L1", "from_equipment": "", "to_equipment": ""}]


def test_rows_must_suit_the_form(repo, wp):
    sl1, as1 = make(repo, wp, "S1", "SL1"), make(repo, wp, "A1", "AS1")
    with pytest.raises(ValueError, match="takes line rows"):
        repo.replace_rows(sl1, "joint", [{"joint_no": "J1"}], "k")
    with pytest.raises(ValueError, match="no table rows"):
        repo.replace_rows(as1, "line", [{"pid": "P"}], "k")
    with pytest.raises(ValueError, match="Unknown row kind"):
        repo.replace_rows(sl1, "nonsense", [], "k")
    with pytest.raises(ValueError, match="Unknown row kind"):
        repo.get_rows(sl1, "nonsense")
    with pytest.raises(ValueError, match="No such certificate"):
        repo.replace_rows(999, "line", [], "k")


def test_mp1_uses_line_rows_like_sl1(repo, wp):
    c = make(repo, wp, "M1", "MP1")
    assert repo.replace_rows(c, "line", [{"pid": "ISO-1", "line_no": "L1"}], "k") == 1


def test_saving_rows_marks_the_workpack_updated_and_is_audited(repo, wp):
    c = make(repo, wp, "E1", "EE12")
    repo.replace_rows(c, "tag", [{"tag": "T1"}], "someone")
    assert repo.get_workpack(wp)["updated_by"] == "someone"
    assert repo.events[-1] == ("rows_saved", "EE12 E1: 1 tag rows")


def test_list_counts_follow_saved_rows(repo, wp):
    c = make(repo, wp, "J1", "JI1")
    repo.replace_rows(c, "joint", [{"joint_no": "1"}, {"joint_no": "2"}, {"joint_no": "3"}], "k")
    assert repo.list_certificates(wp)[0]["joint_count"] == 3


def test_duplicate_copies_fields_and_rows_but_not_the_file_name(repo, wp):
    src = make(repo, wp, "SL1-A", "SL1", equipment="Skid", system="S", filename="My leak test")
    repo.replace_rows(src, "line", [{"pid": "P-1", "line_no": "L1"}, {"pid": "P-2", "line_no": "L2"}], "k")
    new = repo.duplicate_certificate(src, "SL1-B", "kieran")
    got = repo.get_certificate(new)
    assert (got["cert_id"], got["form"], got["equipment"], got["system"]) == ("SL1-B", "SL1", "Skid", "S")
    assert got["filename"] == "" and repo.get_certificate(src)["filename"] == "My leak test"
    assert repo.get_rows(new, "line") == repo.get_rows(src, "line") and len(repo.get_rows(new, "line")) == 2
    assert [c["cert_id"] for c in repo.list_certificates(wp)] == ["SL1-A", "SL1-B"]
    assert repo.events[-1] == ("certificate_duplicated", "SL1 SL1-A -> SL1-B")


def test_duplicate_is_independent_of_the_original(repo, wp):
    src = make(repo, wp, "E1", "EE12")
    repo.replace_rows(src, "tag", [{"tag": "T1"}], "k")
    new = repo.duplicate_certificate(src, "E2", "k")
    repo.replace_rows(new, "tag", [{"tag": "CHANGED"}], "k")
    assert repo.get_rows(src, "tag") == [{"tag": "T1", "drawing": ""}]


def test_duplicate_needs_a_new_unique_id(repo, wp):
    src = make(repo, wp, "A", "AS1")
    make(repo, wp, "B", "AS1")
    with pytest.raises(ValueError, match="already exists"):
        repo.duplicate_certificate(src, "B", "k")
    with pytest.raises(ValueError, match="required"):
        repo.duplicate_certificate(src, "  ", "k")
    with pytest.raises(ValueError, match="No such certificate"):
        repo.duplicate_certificate(999, "Z", "k")
    assert len(repo.list_certificates(wp)) == 2
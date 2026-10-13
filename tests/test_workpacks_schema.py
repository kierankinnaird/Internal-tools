import sqlite3
from pathlib import Path

import pytest

from core.migrations import migrate

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "workpacks" / "migrations"
NOW = "2026-10-13T08:00:00+00:00"


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "workpacks.sqlite"
    migrate(path, "workpacks", MIGRATIONS)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    yield con
    con.close()


def _workpack(db, title="Test"):
    return db.execute("INSERT INTO workpack (title, created_at, created_by, updated_at, updated_by) "
                      "VALUES (?,?,?,?,?)", (title, NOW, "t", NOW, "t")).lastrowid


def _cert(db, wp, cert_id="AS1-1", form="AS1"):
    return db.execute("INSERT INTO certificate (workpack_id, cert_id, form) VALUES (?,?,?)",
                      (wp, cert_id, form)).lastrowid


def test_migration_applies_once(tmp_path):
    path = tmp_path / "w.sqlite"
    assert migrate(path, "workpacks", MIGRATIONS) == 1
    assert migrate(path, "workpacks", MIGRATIONS) == 0


def test_tables_exist(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"workpack", "certificate", "line", "joint", "tag"} <= names


def test_text_fields_default_to_empty_not_null(db):
    wp = _workpack(db)
    cert = _cert(db, wp)
    assert db.execute("SELECT equipment, scope FROM certificate WHERE id = ?", (cert,)).fetchone() == ("", "")
    assert db.execute("SELECT site FROM workpack WHERE id = ?", (wp,)).fetchone() == ("",)


def test_certificate_id_unique_within_a_workpack_only(db):
    a, b = _workpack(db, "A"), _workpack(db, "B")
    _cert(db, a, "SL1-1", "SL1")
    _cert(db, b, "SL1-1", "SL1")
    with pytest.raises(sqlite3.IntegrityError):
        _cert(db, a, "SL1-1", "SL1")


def test_deleting_a_workpack_removes_everything_under_it(db):
    wp = _workpack(db)
    sl1, ji1, ee12 = _cert(db, wp, "SL1-1", "SL1"), _cert(db, wp, "JI1-1", "JI1"), _cert(db, wp, "EE12-1", "EE12")
    db.execute("INSERT INTO line (certificate_id, pid, line_no) VALUES (?,?,?)", (sl1, "P-100", "L1"))
    db.execute("INSERT INTO joint (certificate_id, joint_no) VALUES (?,?)", (ji1, "J1"))
    db.execute("INSERT INTO tag (certificate_id, tag) VALUES (?,?)", (ee12, "TAG-1"))
    db.execute("DELETE FROM workpack WHERE id = ?", (wp,))
    for table in ("certificate", "line", "joint", "tag"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_rows_need_a_real_certificate(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO tag (certificate_id, tag) VALUES (999, 'X')")

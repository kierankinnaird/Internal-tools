import sqlite3
from pathlib import Path

from core.migrations import migrate

JOBCARDS = Path(__file__).resolve().parent.parent / "modules" / "jobcards" / "migrations"


def tables(db_path):
    with sqlite3.connect(db_path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_jobcards_schema_is_created(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    assert migrate(db, "jobcards", JOBCARDS) == 3
    assert {"workpack", "jobcard", "jobcard_flag", "drawing", "task", "snapshot", "snapshot_line"} <= tables(db)


def test_migrations_apply_once_only(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", JOBCARDS)
    assert migrate(db, "jobcards", JOBCARDS) == 0


def test_later_migration_adds_print_columns(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", JOBCARDS)
    with sqlite3.connect(db) as c:
        assert "fcp_no" in {r[1] for r in c.execute("PRAGMA table_info(workpack)")}
        assert {"ans_sh1_no", "created_by_signature"} <= {r[1] for r in c.execute("PRAGMA table_info(jobcard)")}


def test_deleting_a_workpack_removes_its_cards_and_tasks(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", JOBCARDS)
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("INSERT INTO workpack (number, created_at) VALUES ('W1', 'now')")
        c.execute("INSERT INTO jobcard (workpack_id, seq, number, updated_at) VALUES (1, 1, 'W1-001', 'now')")
        c.execute("INSERT INTO task (jobcard_id, pos) VALUES (1, 0)")
        c.execute("DELETE FROM workpack WHERE id = 1")
        assert c.execute("SELECT COUNT(*) FROM jobcard").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM task").fetchone()[0] == 0
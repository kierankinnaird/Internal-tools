"""The CTR module's own database, how it plugs into the host, and the rule that modules never import each other."""
import re
import sqlite3
from pathlib import Path

import pytest

from core.migrations import migrate
from hosts.standalone import ORDER, create_app, read_enabled

ROOT = Path(__file__).resolve().parent.parent
CTRS = ROOT / "modules" / "ctrs" / "migrations"


def tables(db_path):
    with sqlite3.connect(db_path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_the_schema_is_created_once(tmp_path):
    db = tmp_path / "ctrs.sqlite"
    assert migrate(db, "ctrs", CTRS) == 1
    assert {"ctr", "ctr_line", "ctr_resource", "ctr_addition"} <= tables(db)
    assert migrate(db, "ctrs", CTRS) == 0


def test_deleting_a_ctr_removes_its_rows(tmp_path):
    db = tmp_path / "ctrs.sqlite"
    migrate(db, "ctrs", CTRS)
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("INSERT INTO ctr (title, created_at, updated_at) VALUES ('T', 'now', 'now')")
        c.execute("INSERT INTO ctr_line (ctr_id, pos) VALUES (1, 1)")
        c.execute("INSERT INTO ctr_resource (ctr_id, pos) VALUES (1, 1)")
        c.execute("INSERT INTO ctr_addition (ctr_id, pos) VALUES (1, 1)")
        c.execute("DELETE FROM ctr WHERE id = 1")
        assert [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("ctr_line", "ctr_resource", "ctr_addition")] == [0, 0, 0]


def test_a_new_row_gets_sensible_defaults(tmp_path):
    db = tmp_path / "ctrs.sqlite"
    migrate(db, "ctrs", CTRS)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO ctr (created_at, updated_at) VALUES ('now', 'now')")
        c.execute("INSERT INTO ctr_line (ctr_id, pos) VALUES (1, 1)")
        c.execute("INSERT INTO ctr_resource (ctr_id, pos) VALUES (1, 1)")
        ctr = c.execute("SELECT payment_terms, pool1_label, pool2_label, source_snapshot_id FROM ctr").fetchone()
        assert ctr == ("Reimbursable", "Eng", "Design", None)
        assert c.execute("SELECT kind, qty, factor, from_snapshot FROM ctr_line").fetchone() == ("line", None, None, 0)
        assert c.execute("SELECT source, split_pct, rate FROM ctr_resource").fetchone() == ("pool1", 100, None)


def test_the_ctr_module_is_listed_last_so_the_modules_it_uses_load_first():
    assert ORDER[-1] == "ctrs" and ORDER.index("jobcards") < ORDER.index("ctrs")
    assert read_enabled() == ["norms", "jobcards", "workpacks", "ctrs"]


def test_the_module_declares_what_it_offers_and_uses():
    from modules.ctrs import MODULE
    assert MODULE.name == "ctrs" and MODULE.nav == [("CTRs", "ctrs.index")]
    assert MODULE.permissions == ["ctrs.view", "ctrs.edit"]
    assert MODULE.optional == ["jobcards.hours"] and MODULE.requires == []


def test_it_loads_with_any_mix_of_the_other_modules(tmp_path):
    for modules in (["ctrs"], ["jobcards", "ctrs"], ["norms", "ctrs"], ["norms", "jobcards", "workpacks", "ctrs"]):
        app = create_app(tmp_path / "-".join(modules), "tester", modules=modules)
        assert app.test_client().get("/ctrs/").status_code == 200, modules


def test_the_jobcards_service_is_looked_up_when_a_page_is_asked_for_so_load_order_does_not_matter(tmp_path):
    app = create_app(tmp_path, "tester", modules=["ctrs", "jobcards"])           # the "wrong" way round
    c = app.test_client()
    c.post("/ctrs/", data={"title": "T"})
    assert b"Hours from the jobcards" in c.get("/ctrs/1").data


# ---- modules never import each other (cross-module calls go through ctx.services) ------------------------------------
def module_sources():
    for folder in sorted((ROOT / "modules").iterdir()):
        if not folder.is_dir() or folder.name.startswith("__"):
            continue
        for path in folder.rglob("*.py"):
            if "engine" in path.relative_to(folder).parts:                       # the vendored Workpack Tools
                continue
            yield folder.name, path


def test_there_are_modules_to_check():
    names = {name for name, _ in module_sources()}
    assert {"norms", "jobcards", "workpacks", "ctrs"} <= names


@pytest.mark.parametrize("owner, path", list(module_sources()), ids=lambda v: v.name if isinstance(v, Path) else v)
def test_a_module_never_imports_another_module(owner, path):
    others = {n for n, _ in module_sources()} - {owner}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"\s*(?:from|import)\s+(?:\.\.|modules\.|modules\s+import\s+)(\w+)", line)
        if m:
            assert m.group(1) not in others, f"{path.relative_to(ROOT)}:{n} imports module {m.group(1)}: {line.strip()}"

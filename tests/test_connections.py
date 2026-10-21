"""Every SQLite connection the app opens is closed again, including when something goes wrong.

Python's own `with sqlite3.connect(...)` only commits; it does not close. A connection left to the garbage collector
raises a ResourceWarning and, if an error is in flight, can live on inside its traceback. Each test here watches every
connection opened through sqlite3.connect and checks that close() was called on all of them.
"""
import sqlite3

import pytest

from core.context import SqliteAudit
from hosts.standalone import create_app
from modules.jobcards.link import JobcardsLink
from modules.norms.service import NormsService


@pytest.fixture()
def watched(monkeypatch):
    """The connections opened while a test runs, each remembering whether it was closed."""
    connections = []
    real = sqlite3.connect

    class Watched(sqlite3.Connection):
        closed_by_us = False

        def close(self):
            self.closed_by_us = True
            return super().close()

    def connect(*args, **kwargs):
        kwargs["factory"] = Watched
        conn = real(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    return connections


def assert_all_closed(connections, at_least=1):
    assert len(connections) >= at_least
    assert [c for c in connections if not c.closed_by_us] == []


# ---- the two places that used to leave them to the garbage collector ----------------------------------------------
def test_the_audit_log_closes_its_connections_and_still_saves(tmp_path, watched):
    audit = SqliteAudit(tmp_path / "audit.sqlite")
    audit.log("kieran", "jobcards", "jobcard_saved", "NMC-BB18-001")
    audit.log("kieran", "workpacks", "workpack_filled", "BB-18")
    assert_all_closed(watched, at_least=3)                                        # one to create the table, one per entry
    with sqlite3.connect(tmp_path / "audit.sqlite") as db:                         # and the entries really were committed
        assert db.execute("SELECT user, module, action FROM audit ORDER BY id").fetchall() == [
            ("kieran", "jobcards", "jobcard_saved"), ("kieran", "workpacks", "workpack_filled")]


def test_a_failed_audit_entry_is_rolled_back_and_the_connection_still_closed(tmp_path, watched):
    audit = SqliteAudit(tmp_path / "audit.sqlite")
    audit.log("kieran", "m", "a", "kept")
    with pytest.raises(sqlite3.IntegrityError):
        audit.log(None, "m", "a", "user is required, so this cannot be saved")
    assert_all_closed(watched, at_least=3)
    with sqlite3.connect(tmp_path / "audit.sqlite") as db:
        assert db.execute("SELECT detail FROM audit").fetchall() == [("kept",)]


def test_the_norms_service_closes_every_connection(watched):
    svc = NormsService()
    svc.disciplines()
    svc.items()
    svc.items("1 Piping")
    svc.search("pipe")
    svc.suggest("install junction box")
    assert svc.get("nonsense") is None
    assert_all_closed(watched, at_least=6)


def test_the_norms_service_closes_its_connection_when_a_query_fails(tmp_path, watched):
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()                                                 # a database with no norms table
    del watched[:]
    with pytest.raises(sqlite3.OperationalError):
        NormsService(empty).disciplines()
    assert_all_closed(watched)                                                     # closed even though the query raised


# ---- the rest were already closed: keep it that way ------------------------------------------------------------------
def test_a_whole_working_session_leaves_nothing_open(tmp_path, watched):
    app = create_app(userdata=tmp_path, user_name="tester")
    c = app.test_client()
    # workpacks, with jobcards created and linked from it
    assert c.post("/workpacks/", data={"title": "Wellbay 18", "project_no": "FCP-1", "workpack_no": "WPK-18",
                                       "jc_mode": "create", "jc_number": "JW-18", "jc_count": "2", "jc_prefix": "NMC-BB18-"}).status_code == 302
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    c.post("/workpacks/certificates/1", data={"equipment": "Pump"})
    for url in ("/workpacks/", "/workpacks/1", "/workpacks/certificates/1", "/workpacks/1/fill", "/workpacks/", "/workpacks/99"):
        c.get(url)
    c.post("/workpacks/1/fill", data={"cert": ["1"], "include_jobcards": "1"})     # refused: no templates, but it tries
    # jobcards: editor, save, print, hours by trade, snapshot, duplicate, delete
    c.post("/jobcards/cards/1/save", json={"title": "T", "tasks": [
        {"kind": "note", "note": "<b>Heading</b>"}, {"description": "Weld", "qty": 2, "norm_hours": 2.5, "basis": "q"}]})
    c.get("/jobcards/"); c.get("/jobcards/workpacks/1"); c.get("/jobcards/cards/1"); c.get("/jobcards/cards/1/print")
    c.get("/jobcards/workpacks/1/rollup.csv")
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "rev A"})
    c.post("/jobcards/cards/1/duplicate")
    c.post("/jobcards/cards/2/delete")
    # norms, and the norm picker and suggestions inside the editor
    c.get("/norms/"); c.get("/norms/api/items"); c.get("/norms/api/search?q=pipe&limit=abc")
    c.post("/norms/api/copied", json={"key": "1-1-01-00-01"})
    c.get("/jobcards/api/norm-search?q=weld"); c.get("/jobcards/api/norm-suggest?q=install+junction+box")
    c.get("/jobcards/api/norm-disciplines")
    # a request that fails partway
    assert c.post("/jobcards/cards/999/save", json={}).status_code == 404
    assert c.get("/jobcards/cards/999").status_code == 404
    # unlink and delete, then the export service used by the fill pack
    c.post("/workpacks/1/jobcards/1/unlink")
    service = app.config["CTX"].services.get("jobcards.link")
    service.link(1, 1, "tester")
    assert len(service.export_linked(1, tmp_path / "pack")) >= 1
    c.post("/workpacks/1/delete")
    assert_all_closed(watched, at_least=40)                                        # a busy session, so a real check


def test_a_whole_ctr_session_leaves_nothing_open(tmp_path, watched):
    app = create_app(userdata=tmp_path, user_name="tester")
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "WP1", "title": "Wellbay"})
    c.post("/jobcards/workpacks/1/jobcards", data={"trade": "Welder"})
    c.post("/jobcards/cards/1/save", json={"title": "J", "trade": "Welder", "tasks": [
        {"description": "Weld", "qty": 4, "norm_hours": 2.5, "basis": "q"}]})
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "rev A"})
    assert c.post("/ctrs/", data={"title": "Beryl Bravo"}).status_code == 302
    assert c.post("/ctrs/estimates/1/ctrs", data={"title": "Piping", "ctr_no": "C1"}).status_code == 302
    c.get("/ctrs/"); c.get("/ctrs/estimates/1"); c.get("/ctrs/1"); c.get("/ctrs/static/ctrs.js")
    assert c.post("/ctrs/1/import-hours", data={"snapshot_id": "1"}).status_code == 302
    c.post("/ctrs/1/save", json={"title": "Piping", "resources": [{"name": "A", "source": "group:Welder", "split_pct": "60", "rate": "5"}]})
    c.post("/ctrs/1/preview", json={"lines": [{"qty": "x"}]})                       # refused: a mistake in what was typed
    c.post("/ctrs/1/preview", json={})
    c.post("/ctrs/1/import-hours", data={"snapshot_id": "99"})                      # refused: no such snapshot
    assert c.get("/ctrs/1/export.xlsx").status_code == 200
    c.post("/ctrs/1/duplicate")
    c.post("/ctrs/2/delete")
    assert c.get("/ctrs/estimates/1/export.xlsx").status_code == 200                # the whole workbook
    c.post("/ctrs/estimates/1", data={"title": "Beryl Bravo 2", "client": "Apache"})
    c.post("/ctrs/estimates/1/delete")
    assert c.get("/ctrs/99").status_code == 404 and c.post("/ctrs/99/save", json={}).status_code == 404
    service = app.config["CTX"].services.get("jobcards.hours")
    service.snapshots(); service.snapshot(1)
    with pytest.raises(ValueError):
        service.snapshot(99)
    assert_all_closed(watched, at_least=30)

"""The jobcards.hours service: frozen snapshot hours, offered to other modules (the CTRs) without any import."""
import pytest

from hosts.standalone import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, "tester", modules=["jobcards"])


@pytest.fixture
def service(app):
    return app.config["CTX"].services.get("jobcards.hours")


def build(app):
    """Two workpacks. Every jobcard starts with the two standard 1-hour tasks, so:
    WP1 has a welder card (library 3 h + manual 4 h + standard 2 h = 9) and a rigger card (5 + 2 = 7);
    WP2 has a painter card (2 + 2 = 4)."""
    c = app.test_client()
    for number, title in (("WP1", "Wellbay"), ("WP2", "Skid")):
        c.post("/jobcards/workpacks", data={"number": number, "title": title})
    for wp, trade in ((1, "Welder"), (1, "Rigger"), (2, "Painter")):
        c.post(f"/jobcards/workpacks/{wp}/jobcards", data={"trade": trade})

    def tasks(jc_id, trade, *items):                       # items: (qty, norm, source)
        body = {"title": "J", "trade": trade, "tasks": [
            {"description": f"t{i}", "qty": q, "norm_hours": n, "source": src, "norm_key": "K" if src == "library" else "",
             "basis": "quote" if src == "manual" else ""} for i, (q, n, src) in enumerate(items, 1)]}
        assert c.post(f"/jobcards/cards/{jc_id}/save", json=body).status_code == 200

    tasks(1, "Welder", (3, 1, "library"), (2, 2, "manual"))
    tasks(2, "Rigger", (5, 1, "manual"))
    tasks(3, "Painter", (2, 1, "manual"))
    return c


def snapshot_of(c, wp, label):
    c.post(f"/jobcards/workpacks/{wp}/snapshots", data={"label": label})


def test_the_service_is_registered_and_listed_as_provided(app, service):
    assert service is not None
    from modules.jobcards import MODULE
    assert "jobcards.hours" in MODULE.provides


def test_no_snapshots_means_an_empty_list(service):
    assert service.snapshots() == []


def test_snapshots_are_listed_newest_first_with_workpack_and_whole_hour_total(app, service):
    c = build(app)
    snapshot_of(c, 1, "rev A"); snapshot_of(c, 2, "")
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "rev B"})
    listed = service.snapshots()
    assert [(s["id"], s["workpack_number"], s["workpack_title"], s["label"]) for s in listed] == [
        (3, "WP1", "Wellbay", "rev B"), (2, "WP2", "Skid", ""), (1, "WP1", "Wellbay", "rev A")]
    assert [s["total"] for s in listed] == [16, 4, 16]                              # 9 + 7 and 4: whole numbers
    assert all(isinstance(s["total"], int) and s["created_by"] == "tester" and s["created_at"] for s in listed)


def test_a_snapshot_gives_its_hours_by_trade(app, service):
    c = build(app)
    snapshot_of(c, 1, "rev A")
    snap = service.snapshot(1)
    assert (snap["id"], snap["label"], snap["workpack_number"], snap["total"]) == (1, "rev A", "WP1", 16)
    assert [(l["trade"], l["library"], l["manual"], l["total"]) for l in snap["lines"]] == [
        ("Rigger", 0, 7, 7), ("Welder", 3, 6, 9)]


def test_a_snapshot_is_frozen_while_the_jobcards_move_on(app, service):
    c = build(app)
    snapshot_of(c, 1, "rev A")
    c.post("/jobcards/cards/2/save", json={"title": "J", "trade": "Rigger", "tasks": [
        {"description": "more", "qty": 100, "norm_hours": 1, "basis": "q"}]})
    assert service.snapshot(1)["total"] == 16                                         # still what it was on the day
    snapshot_of(c, 1, "rev B")
    assert service.snapshot(2)["total"] == 16 - 7 + 102          # the rigger card is now 100 + 2


@pytest.mark.parametrize("bad", [0, 99, -1, "1", None, True, 1.0, "x"])
def test_a_missing_or_malformed_snapshot_id_is_refused(app, service, bad):
    build(app)
    with pytest.raises(ValueError, match="No such snapshot"):
        service.snapshot(bad)


def test_old_snapshots_with_fractional_hours_are_not_silently_rounded(app, service):
    c = build(app)
    snapshot_of(c, 1, "old")
    with service._db() as db:
        db.execute("UPDATE snapshot_line SET manual_hours = 4.5 WHERE trade = 'Welder'")
        db.commit()
    snap = service.snapshot(1)
    assert {l["trade"]: l["total"] for l in snap["lines"]}["Welder"] == 7.5 and snap["total"] == 14.5


def test_the_service_only_reads(app, service):
    c = build(app)
    snapshot_of(c, 1, "rev A")
    with service._db() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM snapshot_line ORDER BY snapshot_id, trade")]
    service.snapshots(); service.snapshot(1)
    with service._db() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM snapshot_line ORDER BY snapshot_id, trade")] == before
    assert not hasattr(service, "create_snapshot")

import shutil
import sqlite3
from pathlib import Path

import pytest

from core.migrations import migrate
from hosts.standalone import create_app
from modules.jobcards import calc, richtext
from modules.jobcards.constants import STANDARD_BASIS, STANDARD_TASKS
from modules.jobcards.link import JobcardsLink
from modules.jobcards.repo import Repo

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "jobcards" / "migrations"
FIRST = "Raise PTW, Carry out TBT, Erect Signs & Barriers"
LAST = "Complete this jobcard"


@pytest.fixture()
def repo(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", MIGRATIONS)
    r = Repo(db)
    r.wp = r.create_workpack({"number": "WP1", "title": "T"}, "k")
    return r


def mine(description="work", **more):
    return dict({"description": description, "qty": 2, "norm_hours": 3, "source": "manual", "basis": "quote"}, **more)


def descriptions(jc):
    return [t["description"] for t in jc["tasks"]]


# ---- the standard tasks -------------------------------------------------------------------------
def test_a_new_jobcard_starts_with_the_two_standard_tasks(repo):
    jc = repo.get_jobcard(repo.create_jobcard(repo.wp, "k"))
    assert descriptions(jc) == [FIRST, LAST]
    for t, role in zip(jc["tasks"], ("first", "last")):
        assert (t["role"], t["qty"], t["norm_hours"], t["factor"], t["source"]) == (role, 1, 1, 1, "manual")
        assert t["basis"] == STANDARD_BASIS and t["note"] == ""
    assert jc["totals"]["total"] == 2
    assert [t["pos"] for t in jc["tasks"]] == [0, 1]


def test_a_fresh_jobcard_has_nothing_to_check(repo):
    jobcards = repo.list_jobcards(repo.wp)
    repo.create_jobcard(repo.wp, "k")
    (fresh,) = [j for j in repo.list_jobcards(repo.wp) if j not in jobcards]
    assert fresh["warning_count"] == 0 and len(fresh["tasks"]) == 2


def test_the_standard_tasks_are_what_the_constants_say():
    assert [(s["role"], s["description"]) for s in STANDARD_TASKS] == [("first", FIRST), ("last", LAST)]


def test_jobcards_made_through_the_link_service_get_them_too(tmp_path):
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", MIGRATIONS)
    link = JobcardsLink(db)
    link.create_for(1, "k", {"number": "J", "jobcard_prefix": "NMC-BB18-"}, count=2)
    jobcards = link.linked(1)[0]["jobcards"]
    assert [j["number"] for j in jobcards] == ["NMC-BB18-001", "NMC-BB18-002"] and all(j["tasks"] == 2 for j in jobcards)


def test_they_can_be_edited(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first, last = repo.get_jobcard(jc)["tasks"]
    saved = repo.save_jobcard(jc, {"tasks": [
        dict(mine(FIRST + " (isolations by others)", qty=2, norm_hours=1.5), id=first["id"]),
        dict(mine(LAST, qty=1, norm_hours=0.5), id=last["id"])]}, "k")
    assert descriptions(saved) == [FIRST + " (isolations by others)", LAST]
    assert (saved["tasks"][0]["qty"], saved["tasks"][0]["norm_hours"], saved["tasks"][1]["norm_hours"]) == (2, 1.5, 0.5)
    assert [t["role"] for t in saved["tasks"]] == ["first", "last"]


def test_new_tasks_go_between_them_in_the_order_given(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first, last = repo.get_jobcard(jc)["tasks"]
    saved = repo.save_jobcard(jc, {"tasks": [
        dict(mine(FIRST), id=first["id"]), mine("a"), mine("b"), mine("c"), dict(mine(LAST), id=last["id"])]}, "k")
    assert descriptions(saved) == [FIRST, "a", "b", "c", LAST]


def test_they_stay_first_and_last_whatever_order_arrives(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first, last = repo.get_jobcard(jc)["tasks"]
    saved = repo.save_jobcard(jc, {"tasks": [
        dict(mine(LAST), id=last["id"]), mine("a"), dict(mine(FIRST), id=first["id"]), mine("b")]}, "k")
    assert descriptions(saved) == [FIRST, "a", "b", LAST]
    assert [t["pos"] for t in saved["tasks"]] == [0, 1, 2, 3]
    again = repo.save_jobcard(jc, {"tasks": [dict(mine("b"), id=saved["tasks"][2]["id"]), dict(mine("a"), id=saved["tasks"][1]["id"])]}, "k")
    assert descriptions(again) == [FIRST, "b", "a", LAST]


def test_they_cannot_be_dropped_by_leaving_them_out(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    before = repo.get_jobcard(jc)["tasks"]
    saved = repo.save_jobcard(jc, {"tasks": []}, "k")
    assert descriptions(saved) == [FIRST, LAST] and [t["id"] for t in saved["tasks"]] == [t["id"] for t in before]
    saved = repo.save_jobcard(jc, {"tasks": [mine("only")]}, "k")
    assert descriptions(saved) == [FIRST, "only", LAST]
    assert repo.save_jobcard(jc, {}, "k")["tasks"][0]["description"] == FIRST                # no task list at all


def test_the_browser_cannot_make_an_ordinary_task_standard(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [mine("sneaky first", role="first"), mine("sneaky last", role="last")]}, "k")
    assert descriptions(saved) == [FIRST, "sneaky first", "sneaky last", LAST]
    assert [t["role"] for t in saved["tasks"]] == ["first", "", "", "last"]


def test_a_card_from_before_this_feature_is_left_alone(tmp_path):
    early = tmp_path / "early"
    early.mkdir()
    for name in ("0001_initial.sql", "0002_print_fields.sql", "0003_link_to_workpacks.sql"):
        shutil.copy(MIGRATIONS / name, early / name)
    db = tmp_path / "jobcards.sqlite"
    migrate(db, "jobcards", early)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO workpack (number, created_at) VALUES ('OLD', 'now')")
        c.execute("INSERT INTO jobcard (workpack_id, seq, number, updated_at) VALUES (1, 1, 'OLD-001', 'now')")
        c.execute("INSERT INTO task (jobcard_id, pos, description, qty, norm_hours) VALUES (1, 0, 'Old task', 1, 1)")
    assert migrate(db, "jobcards", MIGRATIONS) == 2                      # 0004 (roles, notes) and 0005 (kind)
    repo = Repo(db)
    jc = repo.get_jobcard(1)
    assert descriptions(jc) == ["Old task"] and (jc["tasks"][0]["role"], jc["tasks"][0]["note"], jc["tasks"][0]["kind"]) == ("", "", "task")
    saved = repo.save_jobcard(1, {"tasks": [dict(mine("Old task"), id=jc["tasks"][0]["id"]), mine("another")]}, "k")
    assert descriptions(saved) == ["Old task", "another"]                  # nothing is added to, or moved in, an old card


def test_a_duplicate_has_one_of_each_standard_task_and_keeps_the_rest(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first, last = repo.get_jobcard(jc)["tasks"]
    repo.save_jobcard(jc, {"tasks": [dict(mine(FIRST + " v2"), id=first["id"]), mine("a"),
                                     mine("", kind="note", note="<b>x</b>"), dict(mine(LAST), id=last["id"])]}, "k")
    copy = repo.get_jobcard(repo.duplicate_jobcard(jc, "k"))
    assert descriptions(copy) == [FIRST + " v2", "a", "x", LAST]
    assert [t["role"] for t in copy["tasks"]] == ["first", "", "", "last"]
    assert [t["kind"] for t in copy["tasks"]] == ["task", "task", "note", "task"] and copy["tasks"][2]["note"] == "<b>x</b>"
    original = repo.get_jobcard(jc)
    assert {t["id"] for t in copy["tasks"]}.isdisjoint({t["id"] for t in original["tasks"]})


def test_a_duplicate_of_an_old_card_gains_the_standard_tasks(repo):
    old = repo.create_jobcard(repo.wp, "k")
    with sqlite3.connect(repo.db_path) as c:                              # make it look like a card from before
        c.execute("DELETE FROM task WHERE jobcard_id=?", (old,))
        c.execute("INSERT INTO task (jobcard_id, pos, description) VALUES (?, 0, 'Old task')", (old,))
    assert descriptions(repo.get_jobcard(repo.duplicate_jobcard(old, "k"))) == [FIRST, "Old task", LAST]


# ---- notes: a heading row with formatted text and no hours; the tasks under it carry the hours ---------------------
def heading(text="<b>Destruct hydraulic supply tubing &amp; Containment from interface plate to:</b>", **more):
    return dict({"kind": "note", "note": text, "description": ""}, **more)


def test_a_note_is_saved_as_a_heading_without_hours_and_comes_back(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    note = "Destruct hydraulic supply tubing:<ul><li>Annulus Kill MSAS Valve</li><li><b>Downhole Safety Valve</b></li></ul>"
    saved = repo.save_jobcard(jc, {"tasks": [heading(note), mine("Annulus Kill MSAS Valve", qty=1, norm_hours=2)]}, "k")
    row = saved["tasks"][1]
    assert (row["kind"], row["note"], row["qty"], row["norm_hours"], row["factor"], row["source"]) == ("note", note, None, None, 1, "manual")
    assert row["description"] == "Destruct hydraulic supply tubing:\nAnnulus Kill MSAS Valve\nDownhole Safety Valve"
    assert repo.get_jobcard(jc)["tasks"][1]["note"] == note
    assert saved["tasks"][2]["kind"] == "task" and saved["tasks"][2]["note"] == ""


def test_the_subtasks_under_a_note_carry_the_hours_and_the_note_none(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [
        heading(), mine("Annulus Kill MSAS Valve", qty=1, norm_hours=2), mine("Downhole Safety Valve", qty=1, norm_hours=3)]}, "k")
    assert [t["kind"] for t in saved["tasks"]] == ["task", "note", "task", "task", "task"]
    assert saved["totals"]["total"] == 1 + 2 + 3 + 1                         # the two standard tasks and the two subtasks
    assert calc.warnings(saved["tasks"][1]) == []                           # a heading has nothing to check


def test_hours_sent_with_a_note_are_ignored(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [heading(qty=5, norm_hours=5, factor=3, factor_reason="x", basis="y",
                                                    source="library", norm_key="K1")]}, "k")
    row = saved["tasks"][1]
    assert (row["qty"], row["norm_hours"], row["factor"], row["factor_reason"], row["basis"], row["norm_key"]) == (None, None, 1, "", "", "")
    assert saved["totals"]["total"] == 2


def test_a_task_that_carries_hours_keeps_no_note(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [mine("Weld", note="<b>stray</b>")]}, "k")
    assert saved["tasks"][1]["kind"] == "task" and saved["tasks"][1]["note"] == ""


def test_a_row_can_be_turned_into_a_note_and_back(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    task_id = repo.save_jobcard(jc, {"tasks": [mine("Destruct tubing")]}, "k")["tasks"][1]["id"]
    as_note = repo.save_jobcard(jc, {"tasks": [dict(heading("<b>Destruct tubing</b>"), id=task_id)]}, "k")["tasks"][1]
    assert as_note["id"] == task_id and as_note["kind"] == "note" and as_note["qty"] is None
    back = repo.save_jobcard(jc, {"tasks": [dict(mine("Destruct tubing"), id=task_id)]}, "k")["tasks"][1]
    assert back["id"] == task_id and back["kind"] == "task" and back["note"] == "" and back["qty"] == 2


def test_a_standard_task_cannot_become_a_note(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    first, last = repo.get_jobcard(jc)["tasks"]
    saved = repo.save_jobcard(jc, {"tasks": [dict(heading("sneaky"), id=first["id"]), dict(mine(LAST), id=last["id"])]}, "k")
    assert [(t["kind"], t["role"]) for t in saved["tasks"]] == [("task", "first"), ("task", "last")]


def test_a_note_in_the_middle_stays_in_order_between_the_standard_tasks(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    saved = repo.save_jobcard(jc, {"tasks": [mine("a"), heading("<b>Group</b>"), mine("b")]}, "k")
    assert descriptions(saved) == [FIRST, "a", "Group", "b", LAST]


def test_a_note_is_cleaned_when_saved(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    dirty = '<b onclick="x()">bold</b><script>alert(1)</script><a href="javascript:x()">link</a><img src=x onerror=y()>'
    saved = repo.save_jobcard(jc, {"tasks": [heading(dirty)]}, "k")
    stored = sqlite3.connect(repo.db_path).execute("SELECT note FROM task WHERE kind='note'").fetchone()[0]
    assert stored == saved["tasks"][1]["note"] == "<b>bold</b>link" and saved["tasks"][1]["description"] == "boldlink"


def test_a_note_that_was_stored_dirty_is_cleaned_on_the_way_out(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    with sqlite3.connect(repo.db_path) as c:
        c.execute("UPDATE task SET note=? WHERE jobcard_id=? AND role='first'", ('<script>alert(1)</script><i>ok</i>', jc))
    assert repo.get_jobcard(jc)["tasks"][0]["note"] == "<i>ok</i>"


def test_an_empty_note_is_stored_as_nothing(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    for blank in ("", "   ", "<div><br></div>", "<p>&nbsp;</p>", None, 5, ["x"]):
        row = repo.save_jobcard(jc, {"tasks": [heading(blank)]}, "k")["tasks"][1]
        assert (row["kind"], row["note"], row["description"]) == ("note", "", "")


def test_an_over_long_note_is_refused_and_nothing_is_saved(repo):
    jc = repo.create_jobcard(repo.wp, "k")
    repo.save_jobcard(jc, {"title": "Before", "tasks": [mine("keep")]}, "k")
    with pytest.raises(ValueError, match="at most"):
        repo.save_jobcard(jc, {"title": "After", "tasks": [heading("y" * (richtext.MAX_LENGTH + 1))]}, "k")
    saved = repo.get_jobcard(jc)
    assert saved["title"] == "Before" and descriptions(saved) == [FIRST, "keep", LAST]


def test_plain_text_of_a_note():
    assert richtext.plain("<b>Head</b><ul><li>one</li><li>two  words</li></ul><div>tail</div>") == "Head\none\ntwo words\ntail"
    assert richtext.plain("") == "" and richtext.plain(None) == "" and richtext.plain("<br><div> </div>") == ""
    assert len(richtext.plain("x" * 5000)) == 1000


@pytest.mark.parametrize("raw, expected", [
    ("plain", "plain"),
    ("<b>bold</b> and <strong>strong</strong>", "<b>bold</b> and <strong>strong</strong>"),
    ("<i>i</i><em>e</em><u>u</u>", "<i>i</i><em>e</em><u>u</u>"),
    ("<ul><li>one</li><li>two</li></ul>", "<ul><li>one</li><li>two</li></ul>"),
    ("<ol><li>one</li></ol>", "<ol><li>one</li></ol>"),
    ("line<br>two<br/>three", "line<br>two<br>three"),
    ("<div>a</div><div>b</div>", "<div>a</div><div>b</div>"),
    ("<b>unclosed", "<b>unclosed</b>"),
    ("stray</b> end</i>", "stray end"),
    ("<b><i>mis</b>nested</i>", "<b><i>mis</i></b>nested"),
    ("a &lt; b &amp; c", "a &lt; b &amp; c"),
    ("<b>x</b>&nbsp;y", "<b>x</b>\xa0y"),
    ('<span style="color:red">kept text</span>', "kept text"),
    ('<font color="red">kept</font>', "kept"),
    ('<b class="x" style="y" onclick="z">b</b>', "<b>b</b>"),
    ("<script>alert(1)</script>after", "after"),
    ("<style>p{}</style>after", "after"),
    ("<iframe src=x>inside</iframe>after", "after"),
    ('<a href="http://x">link</a>', "link"),
    ("<img src=x onerror=alert(1)>", ""),
    ("<<script>script>x", "&lt;"),                     # what follows an opened script is script
    ("<b", ""),
    ("", ""), (None, ""), (3, ""), ("<br>", ""), ("<div> </div>", ""),
])
def test_richtext_clean(raw, expected):
    assert richtext.clean(raw) == expected


def test_a_list_with_nothing_typed_yet_is_still_kept():
    assert richtext.clean("<ul><li></li></ul>") == "<ul><li></li></ul>"


def test_cleaning_twice_changes_nothing():
    once = richtext.clean('<div><b>x</b> &amp; <i>y</i></div><ul><li onclick="1">z</li></ul><script>1</script>')
    assert richtext.clean(once) == once


# ---- the web pages ------------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path, "tester", modules=["jobcards"])
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "WP1", "title": "Pack"})
    c.post("/jobcards/workpacks/1/jobcards", data={})
    return c, app


def save(c, tasks, **more):
    return c.post("/jobcards/cards/1/save", json=dict({"tasks": tasks}, **more))


def test_the_editor_is_given_the_roles_and_notes(client):
    c, _ = client
    html = c.get("/jobcards/cards/1").get_data(as_text=True)
    assert '"role": "first"' in html and '"role": "last"' in html and '"note": ""' in html and '"kind": "task"' in html
    js = c.get("/jobcards/static/jobcards.js").get_data(as_text=True)
    assert "contenteditable" in js and "insertUnorderedList" in js and 'role === "last"' in js
    assert '"Make task"' in js and 'kind: r.state.kind' in js
    assert b"border-radius" not in c.get("/jobcards/static/jobcards.css").data


def test_saving_over_http_keeps_the_order_and_returns_notes(client):
    c, _ = client
    jc = save(c, [dict(kind="note", note="<b>hi</b>", description=""), mine("a")]).get_json()
    assert descriptions(jc) == [FIRST, "hi", "a", LAST]
    assert jc["tasks"][1]["kind"] == "note" and jc["tasks"][1]["note"] == "<b>hi</b>" and jc["tasks"][1]["warnings"] == []
    assert jc["tasks"][1]["hours"] == 0 and jc["tasks"][2]["hours"] == 6 and jc["totals"]["total"] == 8


def test_an_over_long_note_over_http_is_a_clear_400(client):
    c, _ = client
    r = save(c, [dict(kind="note", note="y" * (richtext.MAX_LENGTH + 1))])
    assert r.status_code == 400 and "at most" in r.get_json()["error"]
    assert descriptions(save(c, []).get_json()) == [FIRST, LAST]                  # and the card is as it was


def test_viewers_cannot_save_notes(client):
    c, app = client
    app.config["CTX"]._permissions = {"jobcards.view"}
    assert save(c, [dict(kind="note", note="<b>no</b>")]).status_code == 403
    assert c.get("/jobcards/cards/1").status_code == 200


def test_the_print_view_shows_formatted_notes_and_never_a_script(client):
    c, app = client
    save(c, [dict(kind="note", note="Destruct tubing to:<ul><li>Annulus Kill MSAS Valve</li><li><b>Downhole Safety Valve</b></li></ul>"),
             mine("Annulus Kill MSAS Valve")])
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    assert "<li>Annulus Kill MSAS Valve</li>" in html and "<li><b>Downhole Safety Valve</b></li>" in html
    assert html.count("Annulus Kill MSAS Valve") == 2                          # the heading's list item, and the subtask
    # an unclean note that got into the database some other way still cannot reach the page
    with sqlite3.connect(app.config["CTX"].data_dir / "jobcards.sqlite") as db:
        db.execute("UPDATE task SET note='<script>alert(1)</script><b>safe</b>' WHERE kind='note'")
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    assert "<script>alert(1)" not in html and "<b>safe</b>" in html


def test_the_closing_task_sits_on_the_bottom_row_of_the_print(client):
    c, _ = client
    save(c, [mine("a"), mine("b")])
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    rows = [r for r in html.split("<tr>") if 'class="c">' in r and 'class="blue">' in r]
    numbers = [r.split('class="c">')[1].split("<")[0] for r in rows]
    assert numbers == [str(i) for i in range(1, 11)]                       # at least 10 item rows, numbered in order
    assert FIRST.replace("&", "&amp;") in rows[0] and "a" in rows[1] and "b" in rows[2]
    assert LAST in rows[9] and all(LAST not in r for r in rows[3:9])       # blank rows come before it


def test_a_long_list_prints_every_task_with_the_closing_one_last(client):
    c, _ = client
    save(c, [mine(f"task {i}") for i in range(1, 14)])
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    rows = [r for r in html.split("<tr>") if 'class="c">' in r and 'class="blue">' in r]
    assert len(rows) == 15 and "task 13" in rows[13] and LAST in rows[14]


def test_a_card_without_standard_tasks_prints_as_before(tmp_path):
    app = create_app(tmp_path, "tester", modules=["jobcards"])
    c = app.test_client()
    c.post("/jobcards/workpacks", data={"number": "WP1"})
    c.post("/jobcards/workpacks/1/jobcards", data={})
    with sqlite3.connect(tmp_path / "jobcards.sqlite") as db:
        db.execute("DELETE FROM task")
        db.execute("INSERT INTO task (jobcard_id, pos, description) VALUES (1, 0, 'Only task')")
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    rows = [r for r in html.split("<tr>") if 'class="c">' in r and 'class="blue">' in r]
    assert len(rows) == 10 and "Only task" in rows[0] and LAST not in html


# ---- hours are rounded up per task everywhere they are shown --------------------------------------------------
def test_saved_hours_are_rounded_up_per_task_and_totalled(client):
    c, _ = client
    jc = save(c, [mine("a", qty=1, norm_hours=2.5), mine("b", qty=2, norm_hours=1.25), mine("c", qty=1, norm_hours=2)]).get_json()
    assert [t["hours"] for t in jc["tasks"]] == [1, 3, 3, 2, 1]                          # standard, 2.5, 2.5, 2 (whole), standard
    assert jc["totals"]["total"] == 10                                                    # not 8.5 + 2 raw


def test_the_print_view_shows_the_rounded_hours_and_total(client):
    c, _ = client
    save(c, [mine("a", qty=1, norm_hours=2.5), mine("b", qty=1, norm_hours=0.2)])
    html = c.get("/jobcards/cards/1/print").get_data(as_text=True)
    assert 'class="blue c">3</td>' in html and 'class="blue c">1</td>' in html            # 2.5 -> 3, 0.2 -> 1
    assert 'style="border-style:solid">6</td>' in html                                     # 1 + 3 + 1 + 1 (standard tasks 1 each)


def test_the_hours_by_trade_csv_uses_rounded_hours(client):
    c, _ = client
    save(c, [mine("a", qty=1, norm_hours=2.5)], trade="Welder")
    assert "WP1,Welder,0,5,5" in c.get("/jobcards/workpacks/1/rollup.csv").get_data(as_text=True)     # 1 + 3 + 1


def test_the_editor_rounds_up_the_same_way(client):
    c, _ = client
    js = c.get("/jobcards/static/jobcards.js").get_data(as_text=True)
    assert "Math.ceil(Math.round(" in js and "function hoursOf" in js and "n.toFixed(0)" in js
    assert "rounded up to the next whole hour" in c.get("/jobcards/cards/1").get_data(as_text=True)


# ---- the jobcards page, the snapshot and the CTR figures are whole hours ---------------------------------------
def page_text(c, url="/jobcards/workpacks/1"):
    return c.get(url).get_data(as_text=True)


def test_the_jobcards_page_shows_whole_hours_in_every_table(client):
    c, _ = client
    save(c, [mine("a", qty=1, norm_hours=2.5), mine("b", qty=1, norm_hours=0.2)], trade="Welder")      # 3 + 1 (+ 2 standard)
    html = page_text(c)
    assert '<td class="num"><b>6</b></td>' in html                                    # the jobcard's total, in the jobcards table
    assert 'class="num">0</td><td class="num">6</td><td class="num"><b>6</b></td>' in html      # library, manual, total by trade
    assert '<tr class="total"><td>Total</td><td class="num">0</td><td class="num">6</td><td class="num">6</td></tr>' in html
    assert ".00" not in html and "6.0" not in html


def test_a_snapshot_freezes_whole_hours_and_shows_them_as_such(client):
    c, app = client
    tmp = app.config["CTX"].data_dir
    save(c, [mine("a", qty=1, norm_hours=2.5), mine("b", qty=2, norm_hours=1.25)], trade="Welder")     # 3 + 3 (+ 2)
    c.post("/jobcards/workpacks/1/snapshots", data={"label": "Issued for CTR rev A"})
    with sqlite3.connect(tmp / "jobcards.sqlite") as db:
        lines = db.execute("SELECT trade, library_hours, manual_hours FROM snapshot_line").fetchall()
    assert lines == [("Welder", 0.0, 8.0)]                                              # whole, and the sum of rounded tasks
    html = page_text(c)
    assert "Issued for CTR rev A" in html
    assert '<tr><td>Welder</td><td class="num">0</td><td class="num">8</td><td class="num">8</td></tr>' in html
    save(c, [mine("a", qty=1, norm_hours=10)], trade="Welder")                         # later changes leave the snapshot alone
    with sqlite3.connect(tmp / "jobcards.sqlite") as db:
        assert db.execute("SELECT manual_hours FROM snapshot_line").fetchall() == [(8.0,)]


def test_an_old_snapshot_with_a_fraction_is_shown_as_it_was_not_rounded(client):
    c, app = client
    tmp = app.config["CTX"].data_dir
    with sqlite3.connect(tmp / "jobcards.sqlite") as db:                                # taken before hours were rounded up
        db.execute("INSERT INTO snapshot (workpack_id, label, created_by, created_at) VALUES (1, 'Old', 'k', '2026-10-01T09:00:00')")
        db.execute("INSERT INTO snapshot_line (snapshot_id, trade, library_hours, manual_hours) VALUES (1, 'Welder', 1.5, 4.5)")
    html = page_text(c)
    assert '<tr><td>Welder</td><td class="num">1.50</td><td class="num">4.50</td><td class="num">6</td></tr>' in html


def test_the_hours_by_trade_csv_is_whole_hours(client):
    c, _ = client
    save(c, [mine("a", qty=1, norm_hours=0.2)], trade="Welder")
    rows = c.get("/jobcards/workpacks/1/rollup.csv").get_data(as_text=True).splitlines()
    assert rows[0] == "Workpack,Trade,Library hours,Manual hours,Total hours" and rows[1] == "WP1,Welder,0,3,3"


def test_format_and_tidy_hours():
    assert calc.format_hours(6) == "6" and calc.format_hours(6.0) == "6" and calc.format_hours(0) == "0" and calc.format_hours(None) == "0"
    assert calc.format_hours(4.5) == "4.50" and calc.format_hours(0.333) == "0.33"
    assert calc.tidy_hours(6.0) == 6 and isinstance(calc.tidy_hours(6.0), int) and calc.tidy_hours(4.567) == 4.57


# ---- the norm suggestions can be closed, and are not offered where they do not belong ----------------------------
def test_the_editor_script_can_close_the_suggestions_and_only_offers_them_where_they_belong(client):
    c, _ = client
    js = c.get("/jobcards/static/jobcards.js").get_data(as_text=True)
    assert "function closeSuggestions" in js and "function wantsSuggestions" in js
    assert '"Close suggestions"' in js and 'e.key === "Escape"' in js                   # a Close button, and Escape
    assert "!row.state.role" in js and 'row.state.kind !== "note"' in js and "!row.norm.value.trim()" in js
    assert "document.activeElement !== row.desc" in js                                  # a late reply is dropped
    assert 'desc.addEventListener("blur"' in js and "row.dismissed" in js
    css = c.get("/jobcards/static/jobcards.css").get_data(as_text=True)
    assert ".sugg-head .btn" in css and "border-radius" not in css


def test_the_suggest_endpoint_gives_nothing_for_an_unrelated_long_description(tmp_path):
    c = create_app(tmp_path, "tester").test_client()                                     # with the norms module, unlike the fixture
    q = "Install blind flange c/w DBB instrument valve assembly at TP-13."
    assert c.get("/jobcards/api/norm-suggest", query_string={"q": q}).get_json() == {"available": True, "rows": []}
    ok = c.get("/jobcards/api/norm-suggest", query_string={"q": "install junction box"}).get_json()
    assert ok["available"] and ok["rows"]

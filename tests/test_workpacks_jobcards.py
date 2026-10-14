import sqlite3

import pytest

from hosts.standalone import create_app
from modules.jobcards.repo import Repo as JobcardsRepo
from modules.workpacks.web import parse_count, parse_ids, parse_prefix


@pytest.fixture()
def both(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["jobcards", "workpacks"])
    return app.test_client(), tmp_path, app


@pytest.fixture()
def alone(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester", modules=["workpacks"])
    return app.test_client(), tmp_path, app


def jc_repo(tmp):
    return JobcardsRepo(tmp / "jobcards.sqlite")


def jc_rows(tmp, sql, *args):
    return sqlite3.connect(tmp / "jobcards.sqlite").execute(sql, args).fetchall()


def wp_count(tmp):
    return sqlite3.connect(tmp / "workpacks.sqlite").execute("SELECT COUNT(*) FROM workpack").fetchone()[0]


def audit(tmp):
    return [r[0] for r in sqlite3.connect(tmp / "audit.sqlite").execute("SELECT action FROM audit")]


def page(c, url):
    return c.get(url, follow_redirects=True).get_data(as_text=True)


def new_wp(c, **more):
    data = {"title": "Wellbay 18", "project_no": "FCP-9", "workpack_no": "WPK-18"}
    data.update(more)
    return c.post("/workpacks/", data=data)


# ---- without the jobcards module ---------------------------------------------------------------
def test_nothing_about_jobcards_appears_without_the_module(alone):
    c, _, app = alone
    assert not app.config["CTX"].services.has("jobcards.link")
    new_wp(c)
    for url in ("/workpacks/", "/workpacks/1"):
        html = c.get(url).get_data(as_text=True)
        assert 'name="jc_' not in html and "Jobcards" not in html and 'id="jobcards"' not in html
        assert "/jobcards" not in html
    assert "kept but unlinked" not in c.get("/workpacks/1").get_data(as_text=True)


def test_the_jobcards_routes_do_not_exist_without_the_module(alone):
    c, tmp, _ = alone
    new_wp(c)
    for url in ("/workpacks/1/jobcards/link", "/workpacks/1/jobcards/create", "/workpacks/1/jobcards/5/unlink"):
        assert c.post(url, data={}).status_code == 404
    assert c.post("/workpacks/", data={"title": "X", "jc_mode": "create", "jc_number": "A"}).status_code == 404
    assert wp_count(tmp) == 1                                          # the refused post created nothing


def test_the_workpacks_module_works_as_before_alone(alone):
    c, tmp, _ = alone
    r = new_wp(c)
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/1")
    assert c.post("/workpacks/", data={"title": "Y", "jc_mode": "none"}).status_code == 302
    assert c.post("/workpacks/1/delete").status_code == 302 and wp_count(tmp) == 1


def test_a_jobcards_mode_is_ignored_when_it_is_none_or_unknown(alone):
    c, _, _ = alone
    assert c.post("/workpacks/", data={"title": "Z", "jc_mode": "bogus"}).status_code == 302


# ---- the forms ---------------------------------------------------------------------------------
def test_the_new_workpack_form_offers_the_choices(both):
    c, tmp, _ = both
    jc_repo(tmp).create_workpack({"number": "OLD-1", "title": "Old job"}, "k")
    html = c.get("/workpacks/").get_data(as_text=True)
    assert 'name="jc_mode" value="none" checked' in html
    assert 'value="create"' in html and 'value="link"' in html
    assert 'name="jc_number"' in html and 'name="jc_count"' in html and 'name="jc_prefix"' in html
    assert 'name="jc_trade"' not in html and "Welder" not in html          # trades are multi-discipline, so not offered
    assert "OLD-1 &middot; Old job (0 jobcards)" in html


def test_create_with_no_jobcards_changes_nothing_in_jobcards(both):
    c, tmp, _ = both
    assert new_wp(c).status_code == 302
    assert new_wp(c, jc_mode="none").status_code == 302
    assert jc_rows(tmp, "SELECT COUNT(*) FROM workpack") == [(0,)]
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "No jobcards linked yet." in html and "Create jobcards" in html


def test_create_now_makes_a_linked_workpack_with_jobcards(both):
    c, tmp, _ = both
    r = new_wp(c, jc_mode="create", jc_number="JW-18", jc_count="3", jc_prefix="NMC-BB18-", location="Deck 2")
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/1")
    assert jc_rows(tmp, "SELECT number, title, fcp_no, location, workpacks_ref, asset, discipline, ces_doc_no, jobcard_prefix "
                        "FROM workpack") == [("JW-18", "Wellbay 18", "FCP-9", "Deck 2", 1, "", "", "", "NMC-BB18-")]
    assert jc_rows(tmp, "SELECT number, trade FROM jobcard ORDER BY id") == [
        ("NMC-BB18-001", ""), ("NMC-BB18-002", ""), ("NMC-BB18-003", "")]
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "NMC-BB18-001" in html and "NMC-BB18-003" in html and 'href="/jobcards/workpacks/1"' in html
    assert 'href="/jobcards/cards/1"' in html
    assert "workpack_linked" in audit(tmp)


def test_the_prefix_decides_the_jobcard_numbers(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="A", jc_count="2", jc_prefix="  NMC-BB18  ")      # no closing dash: one is added
    new_wp(c, title="Two", jc_mode="create", jc_number="B", jc_count="1", jc_prefix="NMC_BB19_")
    new_wp(c, title="Three", jc_mode="create", jc_number="C", jc_count="1", jc_prefix="")   # blank: the number is the prefix
    assert jc_rows(tmp, "SELECT number FROM jobcard ORDER BY id") == [
        ("NMC-BB18-001",), ("NMC-BB18-002",), ("NMC_BB19_001",), ("C-001",)]
    assert jc_rows(tmp, "SELECT jobcard_prefix FROM workpack ORDER BY id") == [("NMC-BB18-",), ("NMC_BB19_",), ("C-",)]


def test_a_trade_posted_anyway_is_ignored(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="A", jc_count="1", jc_trade="Welder")
    assert jc_rows(tmp, "SELECT trade FROM jobcard") == [("",)]


def test_a_prefix_already_in_use_is_explained_and_the_workpack_kept(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="A", jc_count="1", jc_prefix="NMC-BB18-")
    r = new_wp(c, title="Second", jc_mode="create", jc_number="B", jc_count="1", jc_prefix="NMC-BB18-")
    html = page(c, r.headers["Location"])
    assert "Jobcards with that prefix already exist. Choose a different prefix" in html and "Something went wrong" not in html
    assert wp_count(tmp) == 2
    assert jc_rows(tmp, "SELECT number FROM workpack") == [("A",)]                          # nothing left behind for B
    r = c.post("/workpacks/2/jobcards/create", data={"jc_number": "B", "jc_count": "1", "jc_prefix": "NMC-BB19-"})
    assert "error" not in r.headers["Location"]
    assert jc_rows(tmp, "SELECT number FROM jobcard ORDER BY id") == [("NMC-BB18-001",), ("NMC-BB19-001",)]


def test_a_very_long_prefix_is_refused(both):
    c, tmp, _ = both
    r = new_wp(c, jc_mode="create", jc_number="A", jc_count="1", jc_prefix="X" * 41)
    assert "at most 40 characters" in page(c, r.headers["Location"]) and wp_count(tmp) == 1
    assert jc_rows(tmp, "SELECT COUNT(*) FROM workpack") == [(0,)]


def test_the_jobcards_number_falls_back_to_the_workpack_number(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="  ", jc_count="1")
    assert jc_rows(tmp, "SELECT number FROM workpack") == [("WPK-18",)]


def test_no_number_anywhere_keeps_the_workpack_and_says_why(both):
    c, tmp, _ = both
    r = c.post("/workpacks/", data={"title": "No numbers", "jc_mode": "create", "jc_count": "2"})
    assert r.status_code == 302 and "/workpacks/1" in r.headers["Location"] and "error=" in r.headers["Location"]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "The workpack was created, but the jobcards step failed" in html and "number is required" in html
    assert wp_count(tmp) == 1 and jc_rows(tmp, "SELECT COUNT(*) FROM workpack") == [(0,)]


@pytest.mark.parametrize("count", ["-1", "101", "x", "2.5", "99999999999999999999"])
def test_a_bad_count_keeps_the_workpack_and_creates_no_jobcards(both, count):
    c, tmp, _ = both
    r = new_wp(c, jc_mode="create", jc_number="JW", jc_count=count)
    assert "error=" in r.headers["Location"]
    assert "jobcards step failed" in page(c, r.headers["Location"])
    assert wp_count(tmp) == 1 and jc_rows(tmp, "SELECT COUNT(*) FROM workpack") == [(0,)]


def test_a_duplicate_jobcards_number_keeps_the_workpack(both):
    c, tmp, _ = both
    jc_repo(tmp).create_workpack({"number": "JW"}, "k")
    r = new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    assert "already exists" in page(c, r.headers["Location"]) and wp_count(tmp) == 1
    assert jc_rows(tmp, "SELECT COUNT(*) FROM workpack") == [(1,)]


def test_an_unexpected_failure_in_the_jobcards_step_keeps_the_workpack(both, monkeypatch):
    c, tmp, app = both
    service = app.config["CTX"].services.get("jobcards.link")

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(service, "create_for", boom)
    r = new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    html = page(c, r.headers["Location"])
    assert "jobcards step failed" in html and "Something went wrong" in html and "secret internal detail" not in html
    assert wp_count(tmp) == 1


def test_link_existing_at_creation_takes_several(both):
    c, tmp, _ = both
    repo = jc_repo(tmp)
    a = repo.create_workpack({"number": "A"}, "k")
    b = repo.create_workpack({"number": "B"}, "k")
    repo.create_workpack({"number": "C"}, "k")
    r = c.post("/workpacks/", data={"title": "T", "jc_mode": "link", "jc_link": [str(a), str(b)]})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert jc_rows(tmp, "SELECT number, workpacks_ref FROM workpack ORDER BY id") == [("A", 1), ("B", 1), ("C", None)]
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "No jobcards linked yet." not in html and 'href="/jobcards/workpacks/1"' in html


def test_link_at_creation_with_nothing_chosen_keeps_the_workpack(both):
    c, tmp, _ = both
    r = c.post("/workpacks/", data={"title": "T", "jc_mode": "link"})
    assert "Choose at least one" in page(c, r.headers["Location"]) and wp_count(tmp) == 1


# ---- the workpack page -------------------------------------------------------------------------
def test_the_panel_shows_each_jobcard_with_its_hours_and_checks(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="2")
    repo = jc_repo(tmp)
    first = repo.list_jobcards(1)[0]
    repo.save_jobcard(first["id"], {"title": "Lift it", "trade": "Rigger", "revision": "C", "tasks": [
        {"description": "a", "qty": 2, "norm_hours": 2.5, "source": "manual", "basis": "quote"},
        {"description": "b", "norm_hours": 1, "source": "manual", "basis": "quote"}]}, "k")
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "Lift it" in html and "Rigger" in html and ">C<" in html
    assert '<td class="num">7</td>' in html and "1 to check" in html            # 5 of ours + the 2 standard hours
    assert html.index('id="jobcards"') < html.index("<h2>Project details</h2>")


def test_link_a_second_and_unlink(both):
    c, tmp, _ = both
    new_wp(c)
    repo = jc_repo(tmp)
    a = repo.create_workpack({"number": "A", "title": "Alpha"}, "k")
    r = c.post("/workpacks/1/jobcards/link", data={"jc_link": str(a)})
    assert r.status_code == 302 and r.headers["Location"].endswith("/workpacks/1#jobcards")
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(1,)]
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "Alpha" in html and "No jobcards in this workpack yet." in html
    assert f'/workpacks/1/jobcards/{a}/unlink' in html and "Its jobcards are kept." in html
    r = c.post(f"/workpacks/1/jobcards/{a}/unlink")
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(None,)]
    assert "workpack_unlinked" in audit(tmp)


def test_create_another_from_the_workpack_page(both):
    c, tmp, _ = both
    new_wp(c)
    r = c.post("/workpacks/1/jobcards/create", data={"jc_number": "EXTRA", "jc_count": "2", "jc_prefix": "NMC-BB18-"})
    assert r.headers["Location"].endswith("/workpacks/1#jobcards")
    assert jc_rows(tmp, "SELECT number, workpacks_ref, fcp_no, title FROM workpack") == [("EXTRA", 1, "FCP-9", "Wellbay 18")]
    assert jc_rows(tmp, "SELECT number FROM jobcard") == [("NMC-BB18-001",), ("NMC-BB18-002",)]
    r = c.post("/workpacks/1/jobcards/create", data={"jc_count": "1"})            # falls back to WPK-18
    assert jc_rows(tmp, "SELECT number FROM workpack ORDER BY id")[-1] == ("WPK-18",)
    r = c.post("/workpacks/1/jobcards/create", data={"jc_number": "EXTRA", "jc_count": "1"})
    assert "error=" in r.headers["Location"] and "already exists" in page(c, r.headers["Location"])
    r = c.post("/workpacks/1/jobcards/create", data={"jc_number": "Q", "jc_count": "500"})
    assert "error=" in r.headers["Location"] and "0 to 100" in page(c, r.headers["Location"])


def test_a_workpack_linked_elsewhere_is_refused(both):
    c, tmp, _ = both
    new_wp(c)
    new_wp(c, title="Second")
    jc_repo(tmp).create_workpack({"number": "A"}, "k")
    c.post("/workpacks/1/jobcards/link", data={"jc_link": "1"})
    r = c.post("/workpacks/2/jobcards/link", data={"jc_link": "1"})
    assert "already+linked" in r.headers["Location"] or "already%20linked" in r.headers["Location"]
    assert "already linked to another workpack" in page(c, r.headers["Location"])
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(1,)]
    html = c.get("/workpacks/2").get_data(as_text=True)
    assert "There are no unlinked jobcards workpacks" in html or 'id="jc_link"' not in html


def test_part_of_a_link_can_fail_and_the_rest_still_links(both):
    c, tmp, _ = both
    new_wp(c)
    new_wp(c, title="Second")
    repo = jc_repo(tmp)
    repo.create_workpack({"number": "A"}, "k")
    repo.create_workpack({"number": "B"}, "k")
    c.post("/workpacks/1/jobcards/link", data={"jc_link": "1"})
    r = c.post("/workpacks/2/jobcards/link", data={"jc_link": ["2", "1"]})
    assert "1 of 2 linked" in page(c, r.headers["Location"])
    assert jc_rows(tmp, "SELECT number, workpacks_ref FROM workpack ORDER BY id") == [("A", 1), ("B", 2)]


def test_you_cannot_unlink_another_workpacks_jobcards(both):
    c, tmp, _ = both
    new_wp(c)
    new_wp(c, title="Second")
    jc_repo(tmp).create_workpack({"number": "A"}, "k")
    c.post("/workpacks/1/jobcards/link", data={"jc_link": "1"})
    r = c.post("/workpacks/2/jobcards/1/unlink")
    assert "not linked to this workpack" in page(c, r.headers["Location"])
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(1,)]


def test_unknown_workpacks_and_bad_ids_are_rejected(both):
    c, tmp, _ = both
    new_wp(c)
    jc_repo(tmp).create_workpack({"number": "A"}, "k")
    for url in ("/workpacks/99/jobcards/link", "/workpacks/99/jobcards/create", "/workpacks/99/jobcards/1/unlink"):
        assert c.post(url, data={"jc_link": "1", "jc_number": "N"}).status_code == 404
    assert c.post("/workpacks/1/jobcards/x/unlink").status_code == 404           # not a whole number in the address
    for bad in ("x", "1.5", "-1", "0", "", " ", "1e3", "٣"):
        r = c.post("/workpacks/1/jobcards/link", data={"jc_link": bad})
        assert "error=" in r.headers["Location"], bad
    r = c.post("/workpacks/1/jobcards/link", data={"jc_link": ["1", "x"]})
    assert "not recognised" in page(c, r.headers["Location"])
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(None,)]
    c.post("/workpacks/", data={"title": "T", "jc_mode": "link", "jc_link": "abc"})
    assert wp_count(tmp) == 2                                                      # kept, with the error shown


def test_deleting_a_workpack_keeps_and_unlinks_its_jobcards(both):
    c, tmp, _ = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="2")
    jc = jc_repo(tmp)
    jc.save_jobcard(1, {"title": "Keep me", "tasks": [{"description": "a", "qty": 1, "norm_hours": 1, "source": "manual", "basis": "q"}]}, "k")
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "Linked jobcards are kept but unlinked." in html and "Jobcards linked to it are kept, but unlinked." in html
    assert c.post("/workpacks/1/delete").status_code == 302
    assert wp_count(tmp) == 0
    assert jc_rows(tmp, "SELECT number, workpacks_ref FROM workpack") == [("JW", None)]
    assert jc_rows(tmp, "SELECT COUNT(*) FROM jobcard") == [(2,)]
    assert jc.get_jobcard(1)["title"] == "Keep me" and len(jc.get_jobcard(1)["tasks"]) == 3
    # a later workpack that reuses id 1 does not inherit the old jobcards
    new_wp(c, title="Later")
    assert "JW-001" not in c.get("/workpacks/1").get_data(as_text=True)
    assert "workpack_unlinked" in audit(tmp)


def test_deleting_a_workpack_without_jobcards_edit_still_unlinks(both):
    c, tmp, app = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    app.config["CTX"]._permissions = {"workpacks.view", "workpacks.edit", "jobcards.view"}
    assert c.post("/workpacks/1/delete").status_code == 302
    assert jc_rows(tmp, "SELECT workpacks_ref FROM workpack") == [(None,)]


# ---- permissions -------------------------------------------------------------------------------
def test_viewers_see_the_panel_read_only_and_cannot_change_it(both):
    c, tmp, app = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    spare = jc_repo(tmp).create_workpack({"number": "SPARE"}, "k")
    app.config["CTX"]._permissions = {"workpacks.view", "jobcards.view"}
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert 'id="jobcards"' in html and "JW-001" in html
    assert "/jobcards/link" not in html and "/unlink" not in html and "jobcards/create" not in html and 'name="jc_' not in html
    assert 'name="jc_mode"' not in c.get("/workpacks/").get_data(as_text=True)
    for url, data in (("/workpacks/1/jobcards/link", {"jc_link": str(spare)}), ("/workpacks/1/jobcards/create", {"jc_number": "N"}),
                      ("/workpacks/1/jobcards/1/unlink", {})):
        assert c.post(url, data=data).status_code == 403
    assert jc_rows(tmp, "SELECT number, workpacks_ref FROM workpack ORDER BY id") == [("JW", 1), ("SPARE", None)]


def test_workpacks_edit_without_jobcards_edit_is_refused_for_jobcards_only(both):
    c, tmp, app = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    app.config["CTX"]._permissions = {"workpacks.view", "workpacks.edit", "jobcards.view"}
    html = c.get("/workpacks/").get_data(as_text=True)
    assert 'name="title"' in html and 'name="jc_mode"' not in html                 # can create, with no jobcards options
    assert "Create jobcards" not in c.get("/workpacks/1").get_data(as_text=True)
    assert c.post("/workpacks/1/jobcards/create", data={"jc_number": "N"}).status_code == 403
    assert c.post("/workpacks/1/jobcards/link", data={"jc_link": "1"}).status_code == 403
    assert c.post("/workpacks/1/jobcards/1/unlink").status_code == 403
    before = wp_count(tmp)
    assert c.post("/workpacks/", data={"title": "Sneaky", "jc_mode": "create", "jc_number": "S"}).status_code == 403
    assert wp_count(tmp) == before                                                  # refused before anything was created
    assert c.post("/workpacks/", data={"title": "Plain"}).status_code == 302        # a plain workpack is still fine
    assert c.post("/workpacks/1", data={"title": "Renamed"}).status_code == 302


def test_jobcards_edit_without_workpacks_edit_is_refused(both):
    c, tmp, app = both
    new_wp(c)
    app.config["CTX"]._permissions = {"workpacks.view", "jobcards.view", "jobcards.edit"}
    assert c.post("/workpacks/1/jobcards/create", data={"jc_number": "N"}).status_code == 403
    assert c.post("/workpacks/", data={"title": "x"}).status_code == 403


def test_without_jobcards_view_the_panel_is_hidden(both):
    c, tmp, app = both
    new_wp(c, jc_mode="create", jc_number="JW", jc_count="1")
    app.config["CTX"]._permissions = {"workpacks.view", "workpacks.edit", "workpacks.fill"}
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert 'id="jobcards"' not in html and "JW-001" not in html
    assert c.get("/workpacks/1").status_code == 200


# ---- escaping and parsing ----------------------------------------------------------------------
def test_titles_and_numbers_are_escaped(both):
    c, tmp, _ = both
    r = new_wp(c, title="<b>Big</b>", jc_mode="create", jc_number="<i>JW</i>", jc_count="1")
    html = c.get("/workpacks/1").get_data(as_text=True)
    assert "<b>Big</b>" not in html and "<i>JW</i>" not in html and "&lt;i&gt;JW&lt;/i&gt;" in html
    jc_repo(tmp).create_workpack({"number": "<u>OLD</u>", "title": "<script>x()</script>"}, "k")
    assert "<u>OLD</u>" not in c.get("/workpacks/").get_data(as_text=True)
    assert "<script>x()</script>" not in c.get("/workpacks/1").get_data(as_text=True)
    html = c.get("/workpacks/1?error=%3Cb%3Eno%3C/b%3E").get_data(as_text=True)
    assert "<b>no</b>" not in html


def test_parse_prefix():
    assert parse_prefix("") == "" and parse_prefix(None) == "" and parse_prefix("   ") == ""
    assert parse_prefix("NMC-BB18") == "NMC-BB18-" and parse_prefix(" NMC-BB18- ") == "NMC-BB18-"
    assert parse_prefix("NMC_BB18_") == "NMC_BB18_" and parse_prefix("A/") == "A/" and parse_prefix("A.") == "A."
    assert parse_prefix("X" * 40) == "X" * 40 + "-"
    with pytest.raises(ValueError):
        parse_prefix("X" * 41)


def test_parse_count_and_parse_ids():
    assert parse_count("") == 0 and parse_count(None) == 0 and parse_count(" 7 ") == 7 and parse_count("0") == 0
    for bad in ("x", "-1", "1.5", "1e2", "٣"):
        with pytest.raises(ValueError):
            parse_count(bad)
    assert parse_count("9" * 50) > 100                         # left for the jobcards module to refuse
    assert parse_ids(["3", " 1 ", "3"]) == [3, 1] and parse_ids([]) == []
    for bad in (["0"], ["-2"], [""], ["a"], ["1", "1.0"], ["9" * 30]):
        with pytest.raises(ValueError):
            parse_ids(bad)


def test_the_stylesheet_still_has_sharp_edges_and_the_script_is_served(both):
    c, _, _ = both
    assert b"border-radius" not in c.get("/workpacks/static/workpacks.css").data
    assert b"jc_mode" in c.get("/workpacks/static/workpacks.js").data

import sqlite3

import pytest

from hosts import security
from hosts.standalone import create_app

EVIL = {"Origin": "http://evil.example"}


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester")
    return app.test_client(), tmp_path


def count(tmp, db, table):
    path = tmp / db
    if not path.exists():
        return 0
    with sqlite3.connect(path) as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def everything(tmp):
    return (count(tmp, "workpacks.sqlite", "workpack"), count(tmp, "jobcards.sqlite", "workpack"),
            count(tmp, "jobcards.sqlite", "jobcard"), count(tmp, "audit.sqlite", "audit"))


# ---- the attack, and that it stops -------------------------------------------------------------------------
def test_another_site_cannot_create_anything(client):
    c, tmp = client
    before = everything(tmp)
    for headers in (EVIL, {"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "cross-site"},
                    {"Referer": "http://evil.example/page"}):
        assert c.post("/workpacks/", data={"title": "X"}, headers=headers).status_code == 403
        assert c.post("/jobcards/workpacks", data={"number": "J"}, headers=headers).status_code == 403
    assert everything(tmp) == before


def test_another_site_cannot_change_or_delete_existing_data(client):
    c, tmp = client
    c.post("/workpacks/", data={"title": "Keep me", "jc_mode": "create", "jc_number": "JW", "jc_count": "1", "jc_prefix": "P-"})
    c.post("/workpacks/1/certificates", data={"cert_id": "AS1-1", "form": "AS1"})
    before = everything(tmp)
    for url, data in (("/workpacks/1/delete", {}), ("/workpacks/1", {"title": "Hacked"}), ("/workpacks/1/certificates", {"cert_id": "X", "form": "AS1"}),
                      ("/workpacks/certificates/1/delete", {}), ("/workpacks/1/jobcards/1/unlink", {}),
                      ("/workpacks/1/jobcards/create", {"jc_number": "Z", "jc_count": "1"}),
                      ("/jobcards/cards/1/delete", {}), ("/jobcards/cards/1/duplicate", {}), ("/jobcards/workpacks/1/delete", {}),
                      ("/jobcards/workpacks/1/snapshots", {"label": "x"}), ("/norms/api/copied", {})):
        r = c.post(url, data=data, headers=EVIL)
        assert r.status_code == 403, url
    assert everything(tmp) == before
    assert c.get("/workpacks/1").get_data(as_text=True).count("Keep me") >= 1      # still there, unrenamed
    assert b"Hacked" not in c.get("/workpacks/1").data


def test_json_saves_from_another_site_are_refused_too(client):
    c, tmp = client
    c.post("/jobcards/workpacks", data={"number": "WP1"})
    c.post("/jobcards/workpacks/1/jobcards", data={})
    r = c.post("/jobcards/cards/1/save", json={"title": "Hacked", "tasks": []}, headers=EVIL)
    assert r.status_code == 403
    assert b"Hacked" not in c.get("/jobcards/cards/1").data


def test_the_fill_and_import_routes_are_covered_as_well(client):
    c, tmp = client
    c.post("/workpacks/", data={"title": "W"})
    assert c.post("/workpacks/1/fill", data={"cert": ["1"]}, headers=EVIL).status_code == 403
    assert c.post("/workpacks/import", data={}, headers=EVIL).status_code == 403
    assert c.post("/workpacks/1/runs/20260101-000000/delete", headers=EVIL).status_code == 403


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_changing_methods_are_checked_the_same_way(client, method):
    c, _ = client
    assert c.open("/workpacks/", method=method, headers=EVIL).status_code == 403
    assert c.open("/workpacks/", method=method).status_code == 405                    # from no browser: reaches routing, which says no


# ---- what must keep working ------------------------------------------------------------------------------------
def test_the_apps_own_pages_can_still_post(client):
    c, tmp = client
    own = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin", "Referer": "http://localhost/workpacks/"}
    assert c.post("/workpacks/", data={"title": "Mine"}, headers=own).status_code == 302
    assert c.post("/jobcards/workpacks", data={"number": "WP1"}, headers={"Origin": "http://localhost"}).status_code == 302
    c.post("/jobcards/workpacks/1/jobcards", data={}, headers=own)
    assert c.post("/jobcards/cards/1/save", json={"title": "Fine", "tasks": []}, headers={"Origin": "http://localhost"}).status_code == 200
    assert count(tmp, "workpacks.sqlite", "workpack") == 1 and count(tmp, "jobcards.sqlite", "jobcard") == 1


def test_requests_that_say_nothing_about_where_they_came_from_are_not_browsers_and_pass(client):
    c, _ = client
    assert c.post("/workpacks/", data={"title": "From a script"}).status_code == 302


@pytest.mark.parametrize("value, allowed", [("same-origin", True), ("none", True), ("cross-site", False), ("same-site", False)])
def test_sec_fetch_site_decides_when_there_is_no_origin(client, value, allowed):
    c, _ = client
    r = c.post("/workpacks/", data={"title": "T"}, headers={"Sec-Fetch-Site": value})
    assert (r.status_code == 302) is allowed and (r.status_code == 403) is not allowed


@pytest.mark.parametrize("origin, allowed", [
    ("http://localhost", True), ("HTTP://LOCALHOST", True), ("http://localhost:6000", False), ("https://localhost", False),
    ("http://127.0.0.1", False), ("http://evil.example", False), ("http://localhost.evil.example", False),
    ("http://evil.example/http://localhost", False), ("null", False), ("", False)])
def test_the_origin_must_be_exactly_this_app(client, origin, allowed):
    c, _ = client
    r = c.post("/workpacks/", data={"title": "T"}, headers={"Origin": origin})
    assert (r.status_code == 302) is allowed and (r.status_code == 403) is not allowed


def test_a_matching_origin_wins_over_other_headers_and_a_wrong_one_cannot_be_overridden(client):
    c, _ = client
    assert c.post("/workpacks/", data={"title": "T"}, headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin",
                                                              "Referer": "http://localhost/"}).status_code == 403


@pytest.mark.parametrize("referer, allowed", [("http://localhost/workpacks/1?x=1", True), ("http://localhost:7/x", False),
                                              ("http://evil.example/http://localhost/", False), ("not a url", False)])
def test_the_referer_is_used_when_nothing_better_is_sent(client, referer, allowed):
    c, _ = client
    r = c.post("/workpacks/", data={"title": "T"}, headers={"Referer": referer})
    assert (r.status_code == 302) is allowed and (r.status_code == 403) is not allowed


def test_reading_pages_is_not_blocked_by_where_the_link_came_from(client):
    c, _ = client
    for headers in (EVIL, {"Sec-Fetch-Site": "cross-site"}, {"Referer": "http://evil.example/"}):
        assert c.get("/workpacks/", headers=headers).status_code == 200
        assert c.get("/jobcards/", headers=headers).status_code == 200
        assert c.get("/norms/", headers=headers).status_code == 200


def test_the_origin_is_compared_with_the_address_the_request_used(tmp_path):
    c = create_app(userdata=tmp_path, user_name="t").test_client()
    ours = {"Origin": "http://127.0.0.1:5050"}
    assert c.post("/workpacks/", data={"title": "A"}, base_url="http://127.0.0.1:5050", headers=ours).status_code == 302
    assert c.post("/workpacks/", data={"title": "B"}, base_url="http://127.0.0.1:5050", headers={"Origin": "http://localhost:5050"}).status_code == 403
    assert c.post("/workpacks/", data={"title": "C"}, base_url="http://[::1]:5050", headers={"Origin": "http://[::1]:5050"}).status_code == 302


# ---- DNS rebinding: a hostile name pointed at this computer ----------------------------------------------------------
@pytest.mark.parametrize("base, ok", [("http://localhost", True), ("http://127.0.0.1:5050", True), ("http://LOCALHOST:5050", True),
                                      ("http://[::1]:5050", True), ("http://evil.example", False), ("http://evil.example:5050", False),
                                      ("http://127.0.0.1.evil.example", False), ("http://localhost.evil.example", False),
                                      ("http://192.168.1.20:5050", False)])
def test_only_this_computers_names_are_answered(client, base, ok):
    c, _ = client
    r = c.get("/workpacks/", base_url=base)
    assert (r.status_code == 200) is ok and (r.status_code == 400) is not ok


def test_a_rebound_name_cannot_post_either_even_with_a_matching_origin(client):
    c, tmp = client
    r = c.post("/workpacks/", data={"title": "X"}, base_url="http://evil.example", headers={"Origin": "http://evil.example"})
    assert r.status_code == 400 and count(tmp, "workpacks.sqlite", "workpack") == 0


def test_other_names_can_be_allowed_on_purpose(tmp_path, monkeypatch):
    app = create_app(userdata=tmp_path / "a", user_name="t", allowed_hosts=["tools.internal"])
    assert app.test_client().get("/workpacks/", base_url="http://tools.internal:5050").status_code == 200
    assert app.test_client().get("/workpacks/", base_url="http://other.internal").status_code == 400
    monkeypatch.setenv("NMC_ALLOWED_HOSTS", "Desk-PC, laptop.local ,")
    app = create_app(userdata=tmp_path / "b", user_name="t")
    for name in ("desk-pc", "laptop.local", "localhost"):
        assert app.test_client().get("/workpacks/", base_url=f"http://{name}").status_code == 200
    assert app.config["ALLOWED_HOSTS"] == sorted({"127.0.0.1", "localhost", "::1", "desk-pc", "laptop.local"})
    assert app.test_client().get("/workpacks/", base_url="http://evil.example").status_code == 400


# ---- framing, and the error pages ---------------------------------------------------------------------------------------
def test_pages_cannot_be_put_in_another_sites_frame(client):
    c, _ = client
    for url in ("/workpacks/", "/jobcards/", "/norms/", "/workpacks/static/workpacks.css", "/nope"):
        r = c.get(url)
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN" and r.headers["Content-Security-Policy"] == "frame-ancestors 'self'", url
    assert c.post("/workpacks/", data={"title": "x"}, headers=EVIL).headers["X-Frame-Options"] == "SAMEORIGIN"     # refusals too


def test_the_refusal_says_what_happened_and_never_echoes_markup(client):
    c, _ = client
    r = c.post("/workpacks/", data={"title": "X"}, headers={"Origin": "<script>alert(1)</script>"})
    body = r.get_data(as_text=True)
    assert r.status_code == 403 and "Nothing was changed" in body and "Blocked for your safety" in body
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body
    assert "answers to" in c.get("/workpacks/", base_url="http://evil.example").get_data(as_text=True)


def test_the_refused_request_is_not_audited_or_partly_done(client):
    c, tmp = client
    c.post("/workpacks/", data={"title": "Real"})
    audit_before = count(tmp, "audit.sqlite", "audit")
    c.post("/workpacks/1/delete", headers=EVIL)
    assert count(tmp, "audit.sqlite", "audit") == audit_before and count(tmp, "workpacks.sqlite", "workpack") == 1


# ---- the helpers ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [("127.0.0.1:5050", "127.0.0.1"), ("localhost", "localhost"), ("LocalHost:80", "localhost"),
                                           ("[::1]:5050", "::1"), ("", ""), (None, ""), ("evil.example:abc", "evil.example"), ("bad:port:9", "bad")])      # an odd one is read as some name, and refused
def test_hostname(raw, expected):
    assert security.hostname(raw) == expected


@pytest.mark.parametrize("raw, expected", [("http://localhost:5050/a/b?c=1", "http://localhost:5050"), ("HTTPS://Example.COM", "https://example.com"),
                                           ("", ""), (None, ""), ("null", ""), ("/relative/path", ""), ("http://", ""), ("not a url", "")])
def test_origin_of(raw, expected):
    assert security.origin_of(raw) == expected


def test_allowed_hosts_defaults_and_extras(monkeypatch):
    monkeypatch.delenv("NMC_ALLOWED_HOSTS", raising=False)
    assert security.allowed_hosts() == {"127.0.0.1", "localhost", "::1"}
    assert security.allowed_hosts([" X.Test ", "", None]) == {"127.0.0.1", "localhost", "::1", "x.test"}

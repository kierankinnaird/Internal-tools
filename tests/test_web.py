import sqlite3

import pytest

from hosts.standalone import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(userdata=tmp_path, user_name="tester")
    return app.test_client(), tmp_path


def test_home_redirects_to_norms(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/norms/")


def test_page_renders_with_user_and_edition(client):
    c, _ = client
    html = c.get("/norms/").get_data(as_text=True)
    assert "Working as tester" in html and "Standalone" in html and "Norms library" in html


def test_search_api(client):
    c, _ = client
    data = c.get("/norms/api/search?q=bevel&discipline=1%20Piping").get_json()
    assert data["total"] > 0 and data["shown"] == len(data["rows"])
    assert all("bevel" in (r["item"] + r["row_desc"] + r["col_desc"]).lower() for r in data["rows"])


def test_copy_is_audited_only_for_real_keys(client):
    c, tmp = client
    assert c.post("/norms/api/copied", json={"key": "1-1-01-00-01"}).status_code == 204
    assert c.post("/norms/api/copied", json={"key": "nonsense"}).status_code == 204
    rows = sqlite3.connect(tmp / "audit.sqlite").execute("SELECT user, module, action, detail FROM audit").fetchall()
    assert rows == [("tester", "norms", "key_copied", "1-1-01-00-01")]

def test_the_app_font_is_the_bundled_montserrat_with_a_fallback_and_controls_follow_it(client):
    c, _ = client
    css = c.get("/static/host.css").get_data(as_text=True)
    assert '--sans: "Montserrat", "Segoe UI"' in css and "font: 15px/1.45 var(--sans)" in css
    assert "button, input, select, textarea { font-family: inherit; }" in css
    font = c.get("/static/fonts/montserrat-latin-wght.woff2")                 # served from the app, so no internet is needed
    assert "fonts/montserrat-latin-wght.woff2" in css and font.status_code == 200 and font.data[:4] == b"wOF2"
    assert b"SIL OPEN FONT LICENSE" in c.get("/static/fonts/Montserrat-OFL.txt").data.upper()

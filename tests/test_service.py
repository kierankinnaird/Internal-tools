import pytest

from modules.norms.service import NormsService, suggest_tokens, whole_number, words_needed


svc = NormsService()


def test_every_word_must_match():
    broad = svc.search("pipe").total
    narrow = svc.search("pipe bevel").total
    assert 0 < narrow < broad


def test_usable_only_by_default():
    rows = svc.search("", limit=500).rows
    assert rows and all(r["status"] == "OK" for r in rows)
    assert svc.search("", usable_only=False).total > svc.search("").total


def test_discipline_and_item_filters():
    d = svc.disciplines()
    assert d and "1 Piping" in d
    items = svc.items("1 Piping")
    assert items and all(i["discipline"] == "1 Piping" for i in items)
    res = svc.search("", discipline="1 Piping", item_id=items[1]["item_id"], usable_only=False)
    assert res.total > 0 and all(r["item_id"] == items[1]["item_id"] for r in res.rows)


def test_known_key_round_trips():
    row = svc.get("1-1-01-00-01")
    assert row and row["hours"] == 0.18 and row["status"] == "OK"
    assert svc.get("9-9-99") is None


def test_wildcard_characters_are_literal():
    assert svc.search("100%").total == svc.search("100%").total  # does not error
    assert svc.search("%").total < svc.search("").total + 1


def test_limit_is_capped():
    assert len(svc.search("", limit=100000, usable_only=False).rows) <= 500


def test_words_match_from_the_start_of_a_word():
    rows = svc.search("butt welds sch 40 6", limit=200).rows
    assert rows and all(r["col_desc"] not in ('16"', '36"') for r in rows)


def test_title_does_not_pull_in_lines_that_do_not_match():
    rows = svc.search("triple", discipline="3 E&I", usable_only=False, limit=500).rows
    assert rows
    assert all("triple" in (r["row_desc"] + " " + r["col_desc"]).lower() for r in rows)


def test_title_words_still_find_items_when_no_line_mentions_them():
    rows = svc.search("gland terminate", discipline="3 E&I", limit=500).rows
    assert rows and any("GLAND" in r["item"] for r in rows)
    both = svc.search("gland triple", discipline="3 E&I", usable_only=False, limit=500).rows
    assert both and all("triple" in (r["row_desc"] + " " + r["col_desc"]).lower() for r in both)
    assert all("GLAND" in r["item"] for r in both)

    

def test_suggest_tokens_drop_filler_and_stem():
    from modules.norms.service import suggest_tokens
    assert suggest_tokens("Install the cable glands on junction box") == ["install", "cable", "gland", "junction", "box"]
    assert suggest_tokens("") == [] and suggest_tokens("the and of") == []


def test_suggest_finds_usable_norms_from_free_text():
    rows = svc.suggest("Cut and bevel 6\" sch 40 pipe for welding").rows
    assert rows and len(rows) <= 5 and all(r["status"] == "OK" for r in rows)
    assert svc.suggest("zzzqqq xxyyzz").rows == []


def test_suggest_needs_two_matching_words_unless_only_one_given():
    assert svc.suggest("weld").rows
    one_real_word = svc.suggest("weld zzzqqq").rows
    assert one_real_word == []

# ---- a bad limit is not an error ----------------------------------------------------------------------------
@pytest.mark.parametrize("value, expected", [("abc", 50), ("", 50), (None, 50), ("1.5", 50), ("  7 ", 7), (7, 7), ("-5", 1), ("0", 1),
                                              ("99999", 500), (True, 50), ("٣", 3), ("1e3", 50), ("0x10", 50), ("%00", 50)])
def test_whole_number_falls_back_to_the_default_and_stays_in_range(value, expected):
    assert whole_number(value, default=50, low=1, high=500) == expected


@pytest.mark.parametrize("limit", ["abc", "", "-5", "0", "99999", "1.5", "10", None, "٣"])
def test_search_and_suggest_accept_any_limit(limit):
    result = svc.search("pipe", limit=limit)
    assert 1 <= len(result.rows) <= 500 and result.total > 0
    suggested = svc.suggest("install junction box", limit=limit)
    assert 1 <= len(suggested.rows) <= 20


def test_the_norms_api_never_fails_on_a_bad_limit(tmp_path):
    from hosts.standalone import create_app
    c = create_app(userdata=tmp_path, user_name="t").test_client()
    for value in ("abc", "", "-5", "0", "99999", "1.5", "%00", " 7 "):
        r = c.get("/norms/api/search", query_string={"q": "pipe", "limit": value})
        assert r.status_code == 200 and r.get_json()["shown"] == len(r.get_json()["rows"]) >= 1, value
    assert c.get("/norms/api/search?q=pipe&limit=3").get_json()["shown"] == 3
    assert c.get("/norms/api/search?q=pipe&limit=abc").get_json()["shown"] == 200          # the default


# ---- suggestions need a real match, in proportion to the description ----------------------------------------------
@pytest.mark.parametrize("words, needed", [(0, 1), (1, 1), (2, 2), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4)])
def test_words_needed_grows_with_the_description(words, needed):
    assert words_needed(words) == needed


def test_a_long_description_that_only_shares_a_couple_of_words_gets_no_suggestions():
    # these share "install" and one more word with some norm, which used to be enough to offer an unrelated one
    for text in ("Install blind flange c/w DBB instrument valve assembly at TP-13.",
                 "Break flange & hub type connections from TP-12 to TP-14",
                 "Existing spring support cans on retained p/work to be gagged prior to destruct as per Note P2 / P3"):
        assert len(suggest_tokens(text)) >= 6
        assert svc.suggest(text).rows == [], text


def test_short_descriptions_that_really_match_still_get_suggestions():
    for text in ("Install junction box", "Install cable glands on junction box", "Weld 6 inch pipe butt weld",
                 'Cut and bevel 6" sch 40 pipe for welding'):
        rows = svc.suggest(text).rows
        assert rows and all(r["status"] == "OK" for r in rows), text


def test_a_longer_description_is_suggested_for_when_most_of_it_matches():
    rows = svc.suggest("install junction box 3 way welding socket").rows           # 6 words, needs 3 and a norm has them all
    assert rows and "JUNCTION" in rows[0]["item"].upper()

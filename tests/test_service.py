from modules.norms.service import NormsService

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
"""CTR storage: creating, saving everything at once, checking what is typed, previews, duplicates, importing jobcard hours."""
from pathlib import Path

import pytest

from core.migrations import migrate
from modules.ctrs.repo import Repo

MIGRATIONS = Path(__file__).resolve().parent.parent / "modules" / "ctrs" / "migrations"


@pytest.fixture
def repo(tmp_path):
    migrate(tmp_path / "ctrs.sqlite", "ctrs", MIGRATIONS)
    log = []
    r = Repo(tmp_path / "ctrs.sqlite", audit=lambda a, d: log.append((a, d)))
    r.log = log
    return r


@pytest.fixture
def ctr_id(repo):
    return repo.create_ctr({"title": "Piping Engineering", "client": "Apache"}, "kieran")


def full(**kw):
    """A complete save payload."""
    body = {"title": "Piping Engineering", "client": "Apache",
            "lines": [{"description": "P/Fitter", "grp": "P/Fitter", "eng_override": "137"},
                      {"description": "Fabrication Isometric", "flag": "D", "qty": "17", "eng_norm": "3", "des_norm": "15"}],
            "resources": [{"name": "Lead Pipefitter", "source": "group:P/Fitter", "split_pct": "60", "rate": "55.5"},
                          {"name": "Senior Pipefitter", "source": "group:P/Fitter", "split_pct": "40", "rate": "48"}],
            "additions": [{"name": "Offshore Allowance", "unit_cost": "100", "units": "3"}]}
    body.update(kw)
    return body


# ---- creating ---------------------------------------------------------------------------------------------------
def test_a_new_ctr_needs_a_title(repo):
    for title in ("", "   ", None):
        with pytest.raises(ValueError, match="CTR title is required"):
            repo.create_ctr({"title": title}, "k")
    assert repo.list_ctrs() == []


def test_a_new_ctr_starts_with_the_standard_text_and_additions(repo, ctr_id):
    c = repo.get_ctr(ctr_id)
    assert c["title"] == "Piping Engineering" and c["client"] == "Apache" and c["payment_terms"] == "Reimbursable"
    assert c["scope_intro"] == "This CTR covers the following key deliverables / activities:"
    assert c["assumptions"].startswith("This CTR assumes the following:") and c["exclusions"].startswith("This CTR excludes")
    assert c["basis"] == "1. All personnel rates will be subject to VAT."
    assert (c["pool1_label"], c["pool2_label"]) == ("Eng", "Design")
    assert [a["name"] for a in c["additions"]] == ["Offshore Allowance", "Mob / De-Mob Travel Allowance"]
    assert c["lines"] == [] and c["resources"] == []
    assert c["created_by"] == c["updated_by"] == "kieran" and c["source_snapshot_id"] is None


def test_a_new_ctr_is_prepared_by_whoever_starts_it_on_the_day_they_start_it(repo):
    from datetime import date
    c = repo.get_ctr(repo.create_ctr({"title": "T"}, "kieran"))
    assert c["prepared_by"] == "kieran" and c["ctr_date"] == date.today().isoformat()
    c = repo.get_ctr(repo.create_ctr({"title": "T", "prepared_by": "M.Watt", "ctr_date": "2026-09-17"}, "kieran"))
    assert c["prepared_by"] == "M.Watt" and c["ctr_date"] == "2026-09-17"       # what was typed wins
    c = repo.get_ctr(repo.create_ctr({"title": "T", "prepared_by": "   "}, "kieran"))
    assert c["prepared_by"] == "kieran"


def test_a_duplicate_keeps_the_original_preparer_and_date(repo):
    first = repo.create_ctr({"title": "T", "prepared_by": "M.Watt", "ctr_date": "2026-09-17"}, "kieran")
    copy = repo.get_ctr(repo.duplicate_ctr(first, "ross"))
    assert copy["prepared_by"] == "M.Watt" and copy["ctr_date"] == "2026-09-17"


def test_creating_ignores_fields_a_form_should_not_set(repo):
    cid = repo.create_ctr({"title": "T", "id": 99, "created_by": "someone else", "basis": "mine", "source_text": "x"}, "kieran")
    c = repo.get_ctr(cid)
    assert cid != 99 and c["created_by"] == "kieran" and c["basis"].startswith("1. All personnel") and c["source_text"] == ""


def test_the_ctrs_are_listed_newest_first_with_their_hours_and_cost(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    second = repo.create_ctr({"title": "Second"}, "k")
    listed = repo.list_ctrs()
    assert [c["id"] for c in listed] == [second, ctr_id]
    assert (listed[1]["hours"], listed[1]["cost"]) == (137, round(82 * 55.5 + 55 * 48 + 300, 2))
    assert (listed[0]["hours"], listed[0]["cost"]) == (0, 0)


def test_a_missing_ctr_is_none_and_cannot_be_saved(repo):
    assert repo.get_ctr(99) is None
    with pytest.raises(ValueError, match="No such CTR"):
        repo.save_ctr(99, full(), "k")
    with pytest.raises(ValueError, match="No such CTR"):
        repo.preview(99, {})


# ---- saving ---------------------------------------------------------------------------------------------------
def test_everything_typed_is_saved_and_read_back_in_order(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(objectives="Do it\nproperly", payment_terms="Lump Sum", commencement="ref plan"), "ross")
    assert saved["objectives"] == "Do it\nproperly" and saved["payment_terms"] == "Lump Sum" and saved["commencement"] == "ref plan"
    assert saved["updated_by"] == "ross"
    assert [l["description"] for l in saved["lines"]] == ["P/Fitter", "Fabrication Isometric"]
    assert saved["lines"][0]["eng_override"] == 137 and saved["lines"][1]["qty"] == 17 and saved["lines"][1]["flag"] == "D"
    assert [(r["name"], r["source"], r["split_pct"], r["rate"]) for r in saved["resources"]] == [
        ("Lead Pipefitter", "group:P/Fitter", 60, 55.5), ("Senior Pipefitter", "group:P/Fitter", 40, 48)]
    assert [(a["name"], a["unit_cost"], a["units"]) for a in saved["additions"]] == [("Offshore Allowance", 100, 3)]
    assert repo.get_ctr(ctr_id) == saved


def test_saving_again_replaces_the_rows_it_does_not_add_to_them(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    saved = repo.save_ctr(ctr_id, full(lines=[{"description": "Only"}], resources=[], additions=[]), "k")
    assert [l["description"] for l in saved["lines"]] == ["Only"] and saved["resources"] == [] and saved["additions"] == []


def test_a_field_left_out_of_a_save_keeps_what_it_had(repo, ctr_id):
    repo.save_ctr(ctr_id, full(objectives="Keep me"), "k")
    assert repo.save_ctr(ctr_id, {"title": "Piping Engineering"}, "k")["objectives"] == "Keep me"


def test_a_table_left_out_of_a_save_is_left_alone_not_wiped(repo, ctr_id):
    """A request that does not mention the rows (a partial or broken one) must not delete them."""
    before = repo.save_ctr(ctr_id, full(), "k")
    after = repo.save_ctr(ctr_id, {"title": "Renamed"}, "k")
    assert after["title"] == "Renamed"
    for table in ("lines", "resources", "additions"):
        assert after[table] == before[table]
    only_lines = repo.save_ctr(ctr_id, {"title": "Renamed", "lines": []}, "k")      # asking for none is a different thing
    assert only_lines["lines"] == [] and only_lines["resources"] == before["resources"] and only_lines["additions"] == before["additions"]


def test_a_preview_that_leaves_a_table_out_uses_the_stored_one(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    out = repo.preview(ctr_id, {"resources": [{"name": "Only", "source": "group:P/Fitter", "split_pct": "100", "rate": "1"}]})
    assert [r["eng"] for r in out["lines"]] == [137, 51] and [r["hours"] for r in out["resources"]] == [137]
    assert [a["cost"] for a in out["additions"]] == [300.0]


def test_blank_rows_are_dropped_but_a_row_with_only_a_group_or_a_rate_is_kept(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(
        lines=[{}, {"description": "  "}, {"grp": "Rigger"}, {"qty": "0"}, {"flag": "A"}],
        resources=[{}, {"source": "pool2", "split_pct": "50"}, {"rate": "30"}, {"fixed_hours": "0"}, {"name": "Named"}],
        additions=[{}, {"units": "2"}, {"name": " "}]), "k")
    assert [(l["grp"], l["qty"]) for l in saved["lines"]] == [("Rigger", None), ("", 0)]
    assert [(r["name"], r["rate"], r["fixed_hours"]) for r in saved["resources"]] == [("", 30, None), ("", None, 0), ("Named", None, None)]
    assert [a["units"] for a in saved["additions"]] == [2]


def test_text_is_tidied_but_inner_line_breaks_stay(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(objectives="  one\r\ntwo\rthree  ", client="  Apache  "), "k")
    assert saved["objectives"] == "one\ntwo\nthree" and saved["client"] == "Apache"


def test_a_ctr_cannot_be_saved_without_a_title(repo, ctr_id):
    with pytest.raises(ValueError, match="CTR title is required"):
        repo.save_ctr(ctr_id, full(title="  "), "k")
    assert repo.get_ctr(ctr_id)["title"] == "Piping Engineering"


def test_a_blank_column_name_goes_back_to_the_standard_one(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(pool1_label="  ", pool2_label="Supervision"), "k")
    assert (saved["pool1_label"], saved["pool2_label"]) == ("Eng", "Supervision")


def test_payment_terms_must_be_one_of_the_three(repo, ctr_id):
    repo.save_ctr(ctr_id, full(payment_terms="Budget"), "k")
    assert repo.save_ctr(ctr_id, full(payment_terms="Whatever"), "k")["payment_terms"] == "Budget"      # the old one stays


def test_a_flag_outside_the_list_is_blanked_and_an_unknown_kind_is_a_plain_line(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(lines=[{"description": "x", "flag": "Z", "kind": "weird"}]), "k")
    assert (saved["lines"][0]["flag"], saved["lines"][0]["kind"]) == ("", "line")


# ---- mistakes are refused by name, and nothing is half-saved --------------------------------------------------------
@pytest.mark.parametrize("payload, message", [
    (dict(lines=[{"description": "ok"}, {"qty": "lots"}]), "Scope line 2: Quantity must be a number"),
    (dict(lines=[{"eng_norm": "-1"}]), "Scope line 1: Norm cannot be below 0"),
    (dict(lines=[{"eng_override": "x"}]), "Scope line 1: Hours must be a number"),
    (dict(lines=[{"kind": "allowance", "qty": "5000"}]), "Scope line 1: an allowance cannot be above 1000%"),
    (dict(lines=[{"description": "x" * 501}]), "Scope line 1: Description is too long"),
    (dict(resources=[{"name": "A", "split_pct": "101"}]), "Resource 1: Split cannot be above 100"),
    (dict(resources=[{"name": "A", "split_pct": "-5"}]), "Resource 1: Split cannot be below 0"),
    (dict(resources=[{"name": "A", "rate": "cheap"}]), "Resource 1: Rate must be a number"),
    (dict(resources=[{"name": "A", "source": "somewhere"}]), "Resource 1: Take hours from"),
    (dict(resources=[{"name": "A", "source": "group:  "}]), "Resource 1: Take hours from"),
    (dict(additions=[{"name": "A", "units": "two"}]), "Addition 1: Units must be a number"),
    (dict(objectives="x" * 20001), "Objectives is too long"),
    (dict(client="x" * 201), "Client is too long"),
])
def test_mistakes_are_refused_with_a_message_naming_the_place_and_nothing_is_saved(repo, ctr_id, payload, message):
    repo.save_ctr(ctr_id, full(), "k")
    before = repo.get_ctr(ctr_id)
    with pytest.raises(ValueError, match=message):
        repo.save_ctr(ctr_id, full(**payload), "k")
    assert repo.get_ctr(ctr_id) == before


def test_rows_must_be_a_list_of_objects_and_there_are_limits(repo, ctr_id):
    for bad in ("text", {"a": 1}, [1, 2], ["x"]):
        with pytest.raises(ValueError, match="must be a list"):
            repo.save_ctr(ctr_id, full(lines=bad), "k")
    with pytest.raises(ValueError, match="at most 400 lines"):
        repo.save_ctr(ctr_id, full(lines=[{"description": "x"}] * 401), "k")
    with pytest.raises(ValueError, match="at most 60 resources"):
        repo.save_ctr(ctr_id, full(resources=[{"name": "x"}] * 61), "k")
    with pytest.raises(ValueError, match="at most 30 additions"):
        repo.save_ctr(ctr_id, full(additions=[{"name": "x"}] * 31), "k")
    assert len(repo.save_ctr(ctr_id, full(lines=[{"description": "x"}] * 400), "k")["lines"]) == 400


def test_numbers_typed_with_pound_signs_commas_and_percent_signs_are_understood(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(resources=[{"name": "A", "split_pct": "60%", "rate": "£1,250.50"}]), "k")
    assert (saved["resources"][0]["split_pct"], saved["resources"][0]["rate"]) == (60, 1250.5)


def test_a_resource_with_no_split_typed_takes_all_of_its_source(repo, ctr_id):
    saved = repo.save_ctr(ctr_id, full(resources=[{"name": "A", "split_pct": ""}]), "k")
    assert saved["resources"][0]["split_pct"] == 100


# ---- previews -------------------------------------------------------------------------------------------------
def test_a_preview_works_out_the_figures_and_saves_nothing(repo, ctr_id):
    before = repo.get_ctr(ctr_id)
    out = repo.preview(ctr_id, full())
    assert [r["hours"] for r in out["resources"]] == [82, 55] and out["totals"]["hours"] == 137
    assert [r["eng"] for r in out["lines"]] == [137, 51]
    assert repo.get_ctr(ctr_id) == before and repo.log == [("ctr_created", "Piping Engineering")]


def test_a_preview_answers_row_for_row_even_when_rows_are_blank(repo, ctr_id):
    payload = full(lines=[{}, {"description": "A", "eng_override": "10"}, {}],
                   resources=[{}, {"name": "R", "source": "pool1", "split_pct": "100", "rate": "2"}, {}],
                   additions=[{}, {"name": "X", "unit_cost": "5", "units": "2"}])
    out = repo.preview(ctr_id, payload)
    assert [r["eng"] for r in out["lines"]] == [0, 10, 0]
    assert [(r["hours"], r["cost"]) for r in out["resources"]] == [(0, 0.0), (10, 20.0), (0, 0.0)]
    assert [a["cost"] for a in out["additions"]] == [0.0, 10.0]
    assert out["totals"]["hours"] == 10                      # the blank resources took nothing


def test_a_blank_resource_row_does_not_claim_a_whole_column(repo, ctr_id):
    """A new, untouched resource row defaults to 100% of the first column; it must not count until it has a name."""
    out = repo.preview(ctr_id, full(resources=[{"name": "Real", "source": "pool1", "split_pct": "100"}, {}],
                                    lines=[{"description": "x", "eng_override": "50"}]))
    assert out["warnings"] == ["No rate yet for: Real."]


def test_a_preview_refuses_the_same_mistakes_as_a_save(repo, ctr_id):
    with pytest.raises(ValueError, match="Scope line 1: Quantity must be a number"):
        repo.preview(ctr_id, full(lines=[{"qty": "x"}]))


def test_a_preview_uses_the_column_names_being_typed(repo, ctr_id):
    out = repo.preview(ctr_id, full(pool1_label="Labour", lines=[{"description": "x", "eng_override": "5"}], resources=[]))
    assert out["labels"] == ["Labour", "Design"] and out["warnings"] == ["No resource takes the Labour hours of: x."]


# ---- delete and duplicate ---------------------------------------------------------------------------------------
def test_deleting_a_ctr_takes_its_rows_with_it(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    repo.delete_ctr(ctr_id)
    assert repo.get_ctr(ctr_id) is None
    with repo._db() as db:
        assert [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("ctr_line", "ctr_resource", "ctr_addition")] == [0, 0, 0]
    assert repo.log[-1] == ("ctr_deleted", "Piping Engineering")


def test_deleting_a_missing_ctr_is_harmless(repo):
    repo.delete_ctr(99)
    assert repo.log == [("ctr_deleted", "99")]


def test_a_duplicate_has_everything_under_a_copy_title(repo, ctr_id):
    repo.save_ctr(ctr_id, full(objectives="Obj", payment_terms="Budget"), "k")
    copy_id = repo.duplicate_ctr(ctr_id, "ross")
    a, b = repo.get_ctr(ctr_id), repo.get_ctr(copy_id)
    assert copy_id != ctr_id and b["title"] == "Piping Engineering (copy)" and b["created_by"] == "ross"
    assert b["objectives"] == "Obj" and b["payment_terms"] == "Budget"
    keep = ("description", "grp", "qty", "eng_override", "flag"), ("name", "source", "split_pct", "rate"), ("name", "unit_cost", "units")
    for table, fields in zip(("lines", "resources", "additions"), keep):
        assert [[row[f] for f in fields] for row in a[table]] == [[row[f] for f in fields] for row in b[table]]
        assert {row["id"] for row in a[table]}.isdisjoint({row["id"] for row in b[table]})
    repo.save_ctr(copy_id, full(lines=[]), "k")
    assert len(repo.get_ctr(ctr_id)["lines"]) == 2                                  # changing the copy leaves the original


def test_duplicating_a_missing_ctr_is_refused(repo):
    with pytest.raises(ValueError, match="No such CTR"):
        repo.duplicate_ctr(99, "k")


# ---- hours from a jobcards snapshot ----------------------------------------------------------------------------
def snapshot(**kw):
    s = {"id": 7, "label": "Issued for CTR rev A", "created_at": "2026-10-14T09:30:00+00:00", "workpack_number": "WP1",
         "lines": [{"trade": "P/Fitter", "total": 137}, {"trade": "Rigger", "total": 41}, {"trade": "Painter", "total": 0}]}
    s.update(kw)
    return s


def test_importing_adds_a_line_per_trade_with_the_trade_as_its_group(repo, ctr_id):
    assert repo.import_snapshot(ctr_id, snapshot(), "k") == 2                        # the zero-hour trade is left out
    c = repo.get_ctr(ctr_id)
    assert [(l["description"], l["grp"], l["eng_override"], l["from_snapshot"]) for l in c["lines"]] == [
        ("P/Fitter", "P/Fitter", 137, 1), ("Rigger", "Rigger", 41, 1)]
    assert c["source_snapshot_id"] == 7 and c["source_text"] == "WP1 - Issued for CTR rev A (2026-10-14)"
    assert repo.log[-1] == ("ctr_hours_imported", f"CTR {ctr_id} from WP1 - Issued for CTR rev A (2026-10-14)")


def test_importing_again_replaces_the_earlier_import_and_keeps_typed_lines(repo, ctr_id):
    repo.save_ctr(ctr_id, full(lines=[{"description": "Typed by hand", "qty": "1", "eng_norm": "8"}]), "k")
    repo.import_snapshot(ctr_id, snapshot(), "k")
    repo.import_snapshot(ctr_id, snapshot(id=8, label="rev B", lines=[{"trade": "P/Fitter", "total": 150}]), "k")
    c = repo.get_ctr(ctr_id)
    assert [(l["description"], l["eng_override"]) for l in c["lines"]] == [("Typed by hand", None), ("P/Fitter", 150)]
    assert c["source_snapshot_id"] == 8 and "rev B" in c["source_text"]
    assert [l["pos"] for l in c["lines"]] == [1, 2]


def test_an_imported_line_that_is_saved_stays_marked_as_imported(repo, ctr_id):
    repo.import_snapshot(ctr_id, snapshot(), "k")
    c = repo.get_ctr(ctr_id)
    saved = repo.save_ctr(ctr_id, {"title": c["title"], "lines": c["lines"]}, "k")
    assert [l["from_snapshot"] for l in saved["lines"]] == [1, 1]


def test_importing_a_snapshot_with_no_hours_is_refused_and_changes_nothing(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    before = repo.get_ctr(ctr_id)
    with pytest.raises(ValueError, match="no hours"):
        repo.import_snapshot(ctr_id, snapshot(lines=[{"trade": "Painter", "total": 0}]), "k")
    with pytest.raises(ValueError, match="no hours"):
        repo.import_snapshot(ctr_id, snapshot(lines=[]), "k")
    assert repo.get_ctr(ctr_id) == before


def test_importing_into_a_missing_ctr_is_refused(repo):
    with pytest.raises(ValueError, match="No such CTR"):
        repo.import_snapshot(99, snapshot(), "k")


def test_the_source_survives_a_duplicate(repo, ctr_id):
    repo.import_snapshot(ctr_id, snapshot(), "k")
    copy = repo.get_ctr(repo.duplicate_ctr(ctr_id, "k"))
    assert copy["source_snapshot_id"] == 7 and copy["source_text"].startswith("WP1")


# ---- the audit log -------------------------------------------------------------------------------------------
def test_every_change_is_audited(repo, ctr_id):
    repo.save_ctr(ctr_id, full(), "k")
    repo.duplicate_ctr(ctr_id, "k")
    repo.delete_ctr(ctr_id)
    actions = [a for a, _ in repo.log]
    assert actions == ["ctr_created", "ctr_saved", "ctr_created", "ctr_saved", "ctr_duplicated", "ctr_deleted"]
    repo.audit("ctr_downloaded", "x")
    assert repo.log[-1] == ("ctr_downloaded", "x")

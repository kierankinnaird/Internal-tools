"""The CTR arithmetic: whole hours, percentage splits that add back up, allowances, and the checks."""
import math

import pytest

from modules.ctrs import calc


def line(**kw):
    base = dict(kind="line", description="", grp="", qty=None, eng_norm=None, des_norm=None, factor=None,
                eng_override=None, des_override=None)
    base.update(kw)
    return base


def resource(name="R", source="pool1", split=100.0, rate=None, fixed=None):
    return dict(name=name, source=source, split_pct=split, rate=rate, fixed_hours=fixed)


def ctr(lines=(), resources=(), additions=(), **kw):
    return dict(pool1_label="Eng", pool2_label="Design", lines=list(lines), resources=list(resources),
                additions=list(additions), **kw)


# ---- rounding and typed numbers ----------------------------------------------------------------------------------
def test_hours_round_up_but_an_exact_figure_stays():
    assert calc.round_up_hours(2.1) == 3 and calc.round_up_hours(2.0) == 2 and calc.round_up_hours(0) == 0
    assert calc.round_up_hours(11.000000000000002) == 11        # floating point noise is not an extra hour
    assert calc.round_up_hours(0.0000001) == 0                   # below the 6 places that count


@pytest.mark.parametrize("typed, expected", [("12", 12.0), (" 7.5 ", 7.5), ("£1,200.50", 1200.5), ("60%", 60.0), ("", None),
                                             ("   ", None), (None, None), (3, 3.0), (0, 0.0)])
def test_typed_numbers_are_read_the_way_people_type_them(typed, expected):
    assert calc.number(typed, "Rate") == expected


@pytest.mark.parametrize("typed", ["abc", "1.2.3", "12 hours", True, float("nan"), float("inf"), "inf", "nan"])
def test_something_that_is_not_a_number_is_refused_by_name(typed):
    with pytest.raises(ValueError, match="Rate must be a number"):
        calc.number(typed, "Rate")


def test_limits_are_enforced_with_a_plain_message():
    with pytest.raises(ValueError, match="Split cannot be below 0"):
        calc.number("-1", "Split", 0, 100)
    with pytest.raises(ValueError, match="Split cannot be above 100"):
        calc.number("100.5", "Split", 0, 100)
    assert calc.number("100", "Split", 0, 100) == 100.0 and calc.number("0", "Split", 0, 100) == 0.0
    assert calc.number("-5", "Offset", None) == -5.0


# ---- sharing hours out by percentage -----------------------------------------------------------------------------
def test_three_hours_at_sixty_forty_is_two_and_one_never_two_and_two():
    assert calc.share_out(3, [60, 40]) == [2, 1]


def test_the_shares_always_add_back_up_to_the_hours_when_the_splits_make_100():
    for splits in ([60, 40], [70, 30], [50, 50], [33.3, 33.3, 33.4], [25, 25, 25, 25], [100], [10, 20, 70], [1, 99]):
        for total in range(0, 120):
            shares = calc.share_out(total, splits)
            assert sum(shares) == total, (total, splits, shares)
            assert all(isinstance(s, int) and s >= 0 for s in shares)


def test_each_share_is_within_one_hour_of_its_exact_share():
    for total in (7, 41, 137, 1001):
        for share, pct in zip(calc.share_out(total, [60, 40]), [60, 40]):
            assert abs(share - total * pct / 100) < 1


def test_left_over_hours_go_to_the_largest_fraction_and_ties_to_the_first():
    assert calc.share_out(137, [60, 40]) == [82, 55]            # 82.2 and 54.8: the 55 gets the spare hour
    assert calc.share_out(3, [50, 50]) == [2, 1]                 # 1.5 and 1.5: first listed wins
    assert calc.share_out(5, [50, 50]) == [3, 2]


def test_splits_that_do_not_make_100_share_out_what_was_typed():
    assert calc.share_out(100, [70]) == [70]                     # the rest is simply nobody's
    assert calc.share_out(10, [60, 60]) == [6, 6]                # over 100% is shared as typed (and flagged elsewhere)
    assert calc.share_out(0, [60, 40]) == [0, 0]
    assert calc.share_out(10, [0, 0]) == [0, 0]
    assert calc.share_out(137, []) == []


def test_the_sharing_is_not_thrown_by_floating_point_noise():
    assert calc.share_out(10, [70, 30]) == [7, 3]
    assert calc.share_out(100, [33.3, 33.3, 33.4]) == [33, 33, 34]


# ---- scope lines ---------------------------------------------------------------------------------------------------
def test_a_lines_hours_are_qty_times_norm_times_factor_rounded_up():
    lines = [line(qty=17, eng_norm=3, des_norm=15, factor=1), line(qty=20, eng_norm=5, des_norm=15, factor=0.5),
             line(qty=2, eng_norm=1.1), line(qty=1, eng_norm=2.5, factor=1.5)]
    assert [(r["eng"], r["des"]) for r in calc.line_results(lines)] == [(51, 255), (50, 150), (3, 0), (4, 0)]


def test_a_line_missing_its_quantity_or_norm_has_no_hours_yet_and_a_missing_factor_is_one():
    lines = [line(qty=None, eng_norm=5), line(qty=3, eng_norm=None), line(qty=2, eng_norm=4, factor=None)]
    assert [r["eng"] for r in calc.line_results(lines)] == [0, 0, 8]


def test_typed_hours_replace_the_sum_and_are_also_rounded_up():
    lines = [line(qty=10, eng_norm=10, eng_override=137), line(eng_override=12.2, des_override=0.5)]
    assert [(r["eng"], r["des"]) for r in calc.line_results(lines)] == [(137, 0), (13, 1)]


def test_an_allowance_is_a_percentage_of_every_other_lines_hours_added_to_the_first_column():
    lines = [dict(line(qty=15), kind="allowance"), line(qty=17, eng_norm=3, des_norm=15), line(qty=20, eng_norm=5, des_norm=15)]
    out = calc.line_results(lines)
    assert out[0] == {"eng": math.ceil((51 + 255 + 100 + 300) * 0.15), "des": 0}      # 706 x 15% = 105.9 -> 106
    assert out[0]["eng"] == 106


def test_an_allowance_ignores_other_allowances_and_works_wherever_it_sits():
    lines = [line(qty=10, eng_norm=10), dict(line(qty=10), kind="allowance"), dict(line(qty=50), kind="allowance")]
    out = calc.line_results(lines)
    assert out[1]["eng"] == 10 and out[2]["eng"] == 50           # 10% and 50% of the 100 on the one real line


def test_an_allowance_with_no_percentage_adds_nothing_and_typed_hours_win():
    assert calc.line_results([dict(line(), kind="allowance"), line(qty=1, eng_norm=9)])[0]["eng"] == 0
    typed = dict(line(qty=15, eng_override=4), kind="allowance")
    assert calc.line_results([typed, line(qty=1, eng_norm=100)])[0]["eng"] == 4


# ---- resources --------------------------------------------------------------------------------------------------
def test_resources_take_a_split_of_a_whole_column():
    c = calc.compute(ctr([line(qty=1, eng_norm=345, des_norm=100)],
                         [resource("Lead", "pool1", 70, 50), resource("Senior", "pool1", 30, 40), resource("Designer", "pool2", 100, 30)]))
    assert [r["hours"] for r in c["resources"]] == [242, 103, 100]          # 241.5 and 103.5 -> 242 + 103 = 345
    assert [r["source_hours"] for r in c["resources"]] == [345, 345, 100]
    assert c["totals"]["hours"] == 445 and c["totals"]["resources_cost"] == 242 * 50 + 103 * 40 + 100 * 30


def test_resources_take_a_split_of_a_group_of_lines_such_as_a_trade():
    lines = [line(description="P/Fitter", grp="P/Fitter", eng_override=137), line(description="Rigger", grp="Rigger", eng_override=41)]
    rs = [resource("Lead Pipefitter", "group:P/Fitter", 60, 55.5), resource("Senior Pipefitter", "group:P/Fitter", 40, 48),
          resource("Rigger", "group:Rigger", 100, 40)]
    c = calc.compute(ctr(lines, rs))
    assert [r["hours"] for r in c["resources"]] == [82, 55, 41]
    assert c["resources"][0]["cost"] == round(82 * 55.5, 2) and c["totals"]["hours"] == 178
    assert c["groups"] == {"P/Fitter": 137, "Rigger": 41}


def test_a_group_counts_the_hours_of_both_columns():
    c = calc.compute(ctr([line(grp="G", qty=2, eng_norm=3, des_norm=4)], [resource("R", "group:G", 100)]))
    assert c["groups"] == {"G": 14} and c["resources"][0]["hours"] == 14


def test_a_resource_with_typed_hours_ignores_splits_and_rounds_up():
    c = calc.compute(ctr([line(qty=1, eng_norm=500)], [resource("Manager", "fixed", 10, 90, fixed=12.2)]))
    assert c["resources"][0]["hours"] == 13 and c["resources"][0]["source_hours"] is None and c["resources"][0]["cost"] == 1170.0


def test_a_resource_with_no_rate_costs_nothing_rather_than_failing():
    c = calc.compute(ctr([line(qty=1, eng_norm=10)], [resource("R")]))
    assert c["resources"][0]["cost"] == 0.0 and c["totals"]["cost"] == 0.0


def test_a_missing_split_counts_as_100():
    r = dict(resource("R"), split_pct=None)
    assert calc.compute(ctr([line(qty=1, eng_norm=10)], [r]))["resources"][0]["hours"] == 10


def test_additions_cost_unit_cost_times_units_and_the_total_includes_them():
    c = calc.compute(ctr([line(qty=1, eng_norm=10)], [resource("R", rate=10)],
                         [dict(name="Offshore", unit_cost=100, units=3), dict(name="Blank", unit_cost=None, units=None)]))
    assert [a["cost"] for a in c["additions"]] == [300.0, 0.0]
    assert c["totals"] == {"hours": 10, "line_hours": 10, "resources_cost": 100.0, "additions_cost": 300.0, "cost": 400.0}


def test_money_is_kept_to_the_penny():
    c = calc.compute(ctr([line(qty=1, eng_norm=3)], [resource("R", rate=33.333)], [dict(name="A", unit_cost=0.1, units=3)]))
    assert c["resources"][0]["cost"] == 100.0 and c["additions"][0]["cost"] == 0.3 and c["totals"]["cost"] == 100.3


def test_the_choices_for_where_hours_come_from_list_the_columns_the_groups_and_typed_hours():
    lines = [line(grp="Rigger", eng_override=5), line(grp="Rigger", eng_override=2), line(grp="Welder", des_override=9)]
    c = calc.compute(ctr(lines))
    assert [(o["value"], o["label"], o["hours"]) for o in c["options"]] == [
        ("pool1", "All Eng hours", 7), ("pool2", "All Design hours", 9), ("group:Rigger", "“Rigger” lines", 7),
        ("group:Welder", "“Welder” lines", 9), ("fixed", "Hours typed in", None)]


def test_the_two_hours_columns_can_be_renamed_for_a_ctr_that_is_not_engineering():
    c = calc.compute(dict(ctr([line(eng_override=5)]), pool1_label="Labour", pool2_label="Supervision"))
    assert c["labels"] == ["Labour", "Supervision"] and c["options"][0]["label"] == "All Labour hours"


def test_an_empty_ctr_computes_to_zeros_without_error():
    c = calc.compute(ctr())
    assert c["totals"]["hours"] == 0 and c["totals"]["cost"] == 0 and c["warnings"] == []


# ---- the checks ------------------------------------------------------------------------------------------------
def warn(lines, resources):
    return calc.compute(ctr(lines, resources))["warnings"]


def test_a_clean_ctr_has_nothing_to_check():
    assert warn([line(qty=1, eng_norm=100)], [resource("A", "pool1", 60, 1), resource("B", "pool1", 40, 1)]) == []


def test_splits_that_do_not_make_100_are_flagged_with_what_they_add_up_to():
    w = warn([line(qty=1, eng_norm=100)], [resource("A", "pool1", 70, 1)])
    assert w == ["Splits taking the Eng hours add up to 70%, not 100%."]
    assert "110%" in warn([line(qty=1, eng_norm=100)], [resource("A", "pool1", 60, 1), resource("B", "pool1", 50, 1)])[0]


def test_hours_nobody_takes_are_flagged_by_line_and_by_column():
    w = warn([line(description="3D model", qty=1, eng_norm=10, des_norm=5)], [])
    assert w == ["No resource takes the Eng hours of: 3D model.", "No resource takes the Design hours of: 3D model."]
    # a resource on the other column does not cover it (and has no hours, so it is not asked for a rate)
    assert warn([line(description="3D model", qty=1, eng_norm=10)], [resource("D", "pool2", 100)]) == [
        "No resource takes the Eng hours of: 3D model."]


def test_a_group_taken_by_a_resource_counts_as_taken():
    lines = [line(description="P/Fitter", grp="P/Fitter", eng_override=100)]
    assert warn(lines, [resource("L", "group:P/Fitter", 100, 1)]) == []
    assert warn(lines, []) == ["No resource takes the Eng hours of: P/Fitter."]


def test_hours_shared_out_twice_are_flagged():
    lines = [line(description="P/Fitter", grp="P/Fitter", eng_override=100)]
    w = warn(lines, [resource("All", "pool1", 100, 1), resource("L", "group:P/Fitter", 100, 1)])
    assert w == ["These hours are shared out twice, once as a whole column and once as a group: P/Fitter."]


def test_a_resource_pointing_at_a_group_no_line_uses_is_flagged():
    w = warn([line(qty=1, eng_norm=5, description="x")], [resource("Lead", "group:Gone", 100, 1), resource("All", "pool1", 100, 1)])
    assert any("Lead take hours from “Gone”, which no scope line uses." in x for x in w)


def test_resources_with_hours_but_no_rate_are_named_and_the_list_is_kept_short():
    lines = [line(qty=1, eng_norm=100)]
    rs = [resource(f"R{i}", "pool1", 10, None) for i in range(10)]
    w = [x for x in warn(lines, rs) if x.startswith("No rate")]
    assert w == ["No rate yet for: R0, R1, R2, R3 and 6 more."]


def test_a_resource_with_no_hours_is_not_asked_for_a_rate():
    assert warn([], [resource("Idle", "pool1", 100, None)]) == []


def test_the_warnings_use_the_column_names_the_ctr_gives_its_hours():
    c = calc.compute(dict(ctr([line(description="x", qty=1, eng_norm=5)], []), pool1_label="Hours"))
    assert c["warnings"] == ["No resource takes the Hours hours of: x."]

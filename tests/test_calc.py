import pytest

from modules.jobcards import calc


def test_line_hours():
    assert calc.line_hours(10, 0.5, 1.2) == pytest.approx(6.0)
    assert calc.line_hours(None, 0.5, 1) == 0
    assert calc.line_hours(2, 3, None) == 6


def test_warnings():
    assert calc.warnings({}) == []
    w = calc.warnings({"description": "x", "qty": 1, "norm_hours": 1, "factor": 1.5, "source": "manual"})
    assert "Factor changed without a reason" in w and "Manual norm without a basis" in w
    assert calc.warnings({"description": "x", "qty": 1, "norm_hours": 1, "factor": 1, "source": "library"}) == []


def test_rollup_splits_library_and_manual():
    jcs = [{"trade": "P/Fitter", "tasks": [{"qty": 2, "norm_hours": 1, "factor": 1, "source": "library"},
                                           {"qty": 1, "norm_hours": 3, "factor": 2, "source": "manual"}]},
           {"trade": "P/Fitter", "tasks": [{"qty": 1, "norm_hours": 1, "factor": 1, "source": "manual"}]}]
    r = calc.rollup(jcs)
    assert r == [{"trade": "P/Fitter", "library": 2.0, "manual": 7.0, "total": 9.0}]

# ---- each task's hours are rounded up to the next whole hour -----------------------------------------------
@pytest.mark.parametrize("qty, norm, factor, expected", [
    (1, 2.5, 1, 3),            # 2.5 -> 3
    (2, 1.25, 1, 3),           # 2.5 -> 3
    (1, 0.1, 1, 1),            # a fraction of an hour still counts as one
    (1, 2, 1, 2),              # a whole number stays as it is
    (4, 0.5, 1, 2),
    (3, 1.5, 1, 5),            # 4.5 -> 5
    (1, 2, 1.5, 3),            # the factor counts before rounding: 3.0
    (1, 2.1, 1.5, 4),          # 3.15 -> 4
    (10, 1.1, 1, 11),          # 11.000000000000002 in floating point, but exactly 11 hours
    (3, 0.1, 10, 3),           # 3.0000000000000004
    (7, 0.3, 1, 3),            # 2.0999999999999996 -> 3
    (0, 5, 1, 0),              # no quantity means no hours
    (1, 0, 1, 0),
])
def test_a_tasks_hours_round_up_to_the_next_whole_hour(qty, norm, factor, expected):
    assert calc.line_hours(qty, norm, factor) == expected


def test_hours_are_whole_numbers_and_missing_values_still_count_as_nothing():
    assert calc.line_hours(None, 2.5, 1) == 0 and calc.line_hours(2, None, 1) == 0 and calc.line_hours(None, None, None) == 0
    assert calc.line_hours(2, 2.5, None) == 5                              # a missing factor counts as 1
    assert isinstance(calc.line_hours(1, 2.5, 1), float) and calc.line_hours(1, 2.5, 1).is_integer()


def test_totals_add_up_the_rounded_hours_of_each_task_not_the_raw_total():
    tasks = [{"qty": 1, "norm_hours": 0.2, "factor": 1, "source": "manual"}] * 3        # 0.6 raw, but 3 x 1 hour
    assert calc.jobcard_totals(tasks)["total"] == 3
    mixed = [{"qty": 1, "norm_hours": 2.5, "factor": 1, "source": "library"},
             {"qty": 1, "norm_hours": 1.2, "factor": 1, "source": "manual"}]
    assert calc.jobcard_totals(mixed) == {"library": 3.0, "manual": 2.0, "total": 5.0}


def test_the_rollup_uses_rounded_hours():
    jcs = [{"trade": "Welder", "tasks": [{"qty": 1, "norm_hours": 2.5, "factor": 1, "source": "manual"}]},
           {"trade": "Welder", "tasks": [{"qty": 1, "norm_hours": 2.5, "factor": 1, "source": "manual"}]}]
    assert calc.rollup(jcs) == [{"trade": "Welder", "library": 0.0, "manual": 6.0, "total": 6.0}]    # 3 + 3, not 5


def test_a_note_carries_no_hours_even_if_given_some():
    assert calc.jobcard_totals([{"kind": "note", "qty": 5, "norm_hours": 5, "factor": 1, "source": "manual"}])["total"] == 0

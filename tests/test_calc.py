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
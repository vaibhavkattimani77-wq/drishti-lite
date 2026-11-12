"""Trend rule (spec §4.5): complete quarters only, rising/falling/stable/insufficient."""

from datetime import date

import pandas as pd
import pytest

from src.trend import (DECREASING, INCREASING, INSUFFICIENT, NO_CHANGE, classify,
                       complete_quarters, daily_to_quarters, parse_data_date)


def test_incomplete_quarter_excluded():
    qs = complete_quarters(date(2026, 10, 28))           # mid Q4 2026 -> Q4 excluded
    assert str(qs[-1]) == "2026Q3"
    assert str(qs[0]) == "2024Q4"
    assert len(qs) == 8


def test_quarter_end_counts_as_complete():
    assert str(complete_quarters(date(2026, 9, 30))[-1]) == "2026Q3"


def test_daily_counts_summed_and_gaps_filled_with_zero():
    qs = complete_quarters(date(2026, 10, 28))
    daily = {"20241001": 2, "20241231": 1, "20260930": 4, "20261005": 99}   # last one is outside
    df = daily_to_quarters(daily, qs)
    assert df["Reports"].tolist() == [3, 0, 0, 0, 0, 0, 0, 4]


@pytest.mark.parametrize("counts, status", [
    ([1, 1, 1, 1, 2, 2, 2, 2], INCREASING),        # 8 vs 4 = 2.0
    ([3, 3, 3, 3, 1, 1, 1, 1], DECREASING),       # 4 vs 12 = 0.33
    ([2, 2, 2, 2, 2, 2, 2, 2], NO_CHANGE),        # 1.0
    ([1, 0, 1, 0, 1, 0, 1, 0], INSUFFICIENT),   # 4 reports < 6
    ([0, 0, 0, 0, 2, 2, 2, 2], INCREASING),        # previous = 0, recent >= 3
    ([3, 3, 0, 0, 0, 0, 0, 0], DECREASING),       # ratio 0
])
def test_classify(counts, status):
    assert classify(counts).status == status


def test_rising_needs_three_recent_reports():
    # Rule check: ratio >= 1.5 alone is not enough. With the 6-report minimum
    # this can only matter if thresholds change, so test the rule directly.
    from src import config
    old = config.TREND_MIN_TOTAL
    config.TREND_MIN_TOTAL = 0
    try:
        res = classify([1, 0, 0, 0, 1, 1, 0, 0])    # ratio 2.0, recent = 2
        assert res.ratio == pytest.approx(2.0)
        assert res.status == NO_CHANGE
    finally:
        config.TREND_MIN_TOTAL = old


def test_ratio_and_boundaries():
    assert classify([1, 1, 1, 1, 2, 1, 2, 1]).ratio == pytest.approx(1.5)
    assert classify([1, 1, 1, 1, 2, 1, 2, 1]).status == INCREASING      # exactly 1.5
    assert classify([0, 0, 0, 0, 3, 3, 0, 0]).ratio is None


def test_wrong_number_of_quarters_rejected():
    with pytest.raises(ValueError):
        classify([1, 2, 3])


def test_parse_data_date_fallback():
    assert parse_data_date("2026-10-28") == date(2026, 10, 28)
    assert isinstance(parse_data_date(None), date)


def test_labels_describe_reporting_not_risk():
    assert classify([1, 1, 1, 1, 2, 2, 2, 2]).status == "Increasing reporting"
    assert "risk" not in " ".join([INCREASING, DECREASING, NO_CHANGE, INSUFFICIENT]).lower()

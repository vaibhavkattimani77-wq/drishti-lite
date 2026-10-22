"""Checks the statistics against values worked out by hand.

Run with:  pytest
"""

import math

import pytest

from src.openfda_client import Filters, build_url, drug_clause
from src.signals import analyse, chi_square_yates, is_signal, prr, ror, two_by_two

# Hand-worked example
#   a = 20 reports with drug + reaction
#   drug total = 1,000  -> b = 980
#   reaction total = 220 -> c = 200
#   database = 101,000  -> d = 101,000 - 1,000 - 220 + 20 = 99,800
A, B, C, D = 20, 980, 200, 99_800


def test_two_by_two():
    assert two_by_two(20, 1_000, 220, 101_000) == (A, B, C, D)


def test_prr_by_hand():
    # PRR = (20/1000) / (200/100000) = 0.02 / 0.002 = 10
    value, low, high = prr(A, B, C, D)
    assert value == pytest.approx(10.0)
    se = math.sqrt(1 / 20 - 1 / 1000 + 1 / 200 - 1 / 100_000)
    assert low == pytest.approx(10 * math.exp(-1.96 * se))
    assert high == pytest.approx(10 * math.exp(1.96 * se))
    assert low < value < high


def test_ror_by_hand():
    # ROR = (20 * 99800) / (980 * 200) = 1,996,000 / 196,000 = 10.1837
    value, low, high = ror(A, B, C, D)
    assert value == pytest.approx(1_996_000 / 196_000)
    assert low < value < high


def test_chi_square_yates():
    n = A + B + C + D
    expected = n * (abs(A * D - B * C) - n / 2) ** 2 / ((A + B) * (C + D) * (A + C) * (B + D))
    assert chi_square_yates(A, B, C, D) == pytest.approx(expected)
    assert chi_square_yates(A, B, C, D) > 4


def test_no_disproportion_gives_prr_one():
    # Reaction is 1% of drug reports and 1% of other reports -> PRR = 1, not a signal
    res = analyse(10, 1_000, 1_010, 101_000)
    assert res.prr == pytest.approx(1.0)
    assert not is_signal(res, 2, 3, 4)


def test_signal_flag():
    res = analyse(20, 1_000, 220, 101_000)
    assert is_signal(res, 2, 3, 4)
    assert not is_signal(res, 2, 25, 4)   # fails the minimum-cases rule


def test_zero_cells_do_not_crash():
    assert all(math.isnan(x) for x in prr(0, 10, 5, 100))
    assert all(math.isnan(x) for x in ror(5, 0, 5, 100))


def test_inconsistent_counts_raise():
    with pytest.raises(ValueError):
        two_by_two(50, 40, 100, 1_000)   # more drug+reaction reports than drug reports


def test_url_building():
    url = build_url([drug_clause("ATORVASTATIN")] + Filters(serious_only=True, year_from=2020).clauses())
    assert 'patient.drug.openfda.generic_name:"ATORVASTATIN"+AND+serious:1' in url
    assert "receivedate:[20200101+TO+21001231]" in url
    assert url.endswith("limit=1")

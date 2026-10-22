"""Checks the statistics against values worked out by hand (spec section 4, Gate 1).

Run with:  pytest
"""

import math

import pytest

from src.openfda_client import Filters, build_url, drug_clause
from src.signals import (Thresholds, analyse, chi_square_yates, explain,
                         information_component, prr, ror, two_by_two, zero_cell_note)

# Hand-worked example
#   a = 20 reports with drug + event
#   drug total     = 1,000   -> b = 980
#   event total    = 220     -> c = 200
#   database total = 101,000 -> d = 101,000 - 1,000 - 220 + 20 = 99,800
A, B, C, D = 20, 980, 200, 99_800
N = A + B + C + D


# --- Normal counts -----------------------------------------------------------

def test_two_by_two():
    assert two_by_two(20, 1_000, 220, 101_000) == (A, B, C, D)


def test_prr_by_hand():
    # PRR = (20/1000) / (200/100000) = 0.02 / 0.002 = 10
    value, low, high = prr(A, B, C, D)
    assert value == pytest.approx(10.0)
    se = math.sqrt(1 / 20 - 1 / 1000 + 1 / 200 - 1 / 100_000)
    assert low == pytest.approx(10 * math.exp(-1.96 * se))
    assert high == pytest.approx(10 * math.exp(1.96 * se))
    assert (round(low, 2), round(high, 2)) == (6.34, 15.77)


def test_ror_by_hand():
    # ROR = (20 * 99800) / (980 * 200) = 1,996,000 / 196,000 = 10.18
    value, low, high = ror(A, B, C, D)
    assert value == pytest.approx(1_996_000 / 196_000)
    assert (round(low, 2), round(high, 2)) == (6.40, 16.20)


def test_chi_square_yates_by_hand():
    expected = N * (abs(A * D - B * C) - N / 2) ** 2 / ((A + B) * (C + D) * (A + C) * (B + D))
    assert chi_square_yates(A, B, C, D) == pytest.approx(expected)
    assert round(chi_square_yates(A, B, C, D), 2) == 139.43


def test_ic_by_hand():
    # E = 1000 * 220 / 101000 = 2.178
    # IC = log2(20.5 / 2.678) = 2.94
    # IC025 = 2.936 - 3.3/sqrt(20.5) - 2/20.5^1.5 = 2.19
    e = 1_000 * 220 / 101_000
    ic, ic025 = information_component(A, B, C, D)
    assert ic == pytest.approx(math.log2(20.5 / (e + 0.5)))
    assert ic025 == pytest.approx(ic - 3.3 * 20.5 ** -0.5 - 2 * 20.5 ** -1.5)
    assert (round(ic, 2), round(ic025, 2)) == (2.94, 2.19)


def test_all_three_rules_met():
    r = analyse(20, 1_000, 220, 101_000)
    assert (r.prr_rule, r.ror_rule, r.ic_rule) == (True, True, True)
    assert r.rules_met == 3
    assert not r.small_numbers
    assert r.ratio_note == ""


def test_explanation_text():
    text = explain(analyse(20, 1_000, 220, 101_000))
    assert "2.0% of reports for this drug" in text
    assert "0.20% of reports for all other drugs" in text


# --- No disproportion (PRR = 1) ---------------------------------------------

def test_no_disproportion():
    # Event is 1% of drug reports and 1% of other reports
    r = analyse(10, 1_000, 1_010, 101_000)
    assert r.prr == pytest.approx(1.0)
    assert r.ic == pytest.approx(0.0, abs=1e-9)   # observed = expected
    assert r.ic025 < 0
    assert r.rules_met == 0


# --- a = 0 -------------------------------------------------------------------

def test_a_zero():
    r = analyse(0, 1_000, 220, 101_000)
    assert math.isnan(r.prr) and math.isnan(r.ror)
    assert math.isnan(r.prr_lower) and math.isnan(r.ror_lower)
    assert r.ratio_note == "not computable (a = 0)"
    # IC is still computed thanks to shrinkage, and is negative (fewer than expected)
    assert not math.isnan(r.ic) and r.ic < 0
    assert r.rules_met == 0
    assert r.small_numbers
    assert "not computable (a = 0)" in explain(r)


# --- b, c or d = 0 -----------------------------------------------------------

@pytest.mark.parametrize("cells, note", [
    ((5, 0, 50, 1_000), "not computable (b = 0)"),
    ((5, 100, 0, 1_000), "not computable (c = 0)"),
    ((5, 100, 50, 0), "not computable (d = 0)"),
])
def test_other_zero_cells(cells, note):
    a, b, c, d = cells
    assert zero_cell_note(a, b, c, d) == note
    assert all(math.isnan(x) for x in prr(a, b, c, d))
    assert all(math.isnan(x) for x in ror(a, b, c, d))
    # No continuity correction: the rules that need PRR/ROR fail
    r = analyse(a, a + b, a + c, a + b + c + d)
    assert r.ratio_note == note
    assert not r.prr_rule and not r.ror_rule


# --- Small numbers (a = 1 to 4) ---------------------------------------------

@pytest.mark.parametrize("a", [1, 2, 3, 4])
def test_small_numbers_flag(a):
    # Same 10-fold disproportion as the main example, but with few cases
    r = analyse(a, 1_000 * a // 2, 11 * a, 101_000)
    assert r.small_numbers


def test_small_numbers_cannot_meet_case_minimum():
    # a = 2: PRR = 10, but the PRR and ROR rules both need a >= 3
    r = analyse(2, 1_000, 22, 101_000)
    assert r.prr == pytest.approx(10.0)
    assert not r.prr_rule and not r.ror_rule
    assert "Small numbers (a = 2)" in explain(r)


def test_five_cases_is_not_small():
    assert not analyse(5, 1_000, 55, 101_000).small_numbers


# --- Thresholds and errors ---------------------------------------------------

def test_thresholds_are_respected():
    r = analyse(20, 1_000, 220, 101_000, Thresholds(prr_cases_min=25, ror_cases_min=25))
    assert not r.prr_rule and not r.ror_rule and r.ic_rule
    assert r.rules_met == 1


def test_inconsistent_counts_raise():
    with pytest.raises(ValueError):
        two_by_two(50, 40, 100, 1_000)   # more drug+event reports than drug reports


# --- URL building (openfda_client) ------------------------------------------

def test_url_building():
    url = build_url([drug_clause("ATORVASTATIN")] + Filters(serious_only=True, year_from=2020).clauses())
    assert 'patient.drug.openfda.generic_name:"ATORVASTATIN"+AND+serious:1' in url
    assert "receivedate:[20200101+TO+21001231]" in url
    assert url.endswith("limit=1")

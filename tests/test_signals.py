"""Statistics checked against values worked out by hand (Gate 1).

Covers: normal counts, a = 0, b/c/d = 0, a = 1-4 (small numbers),
PRR = 1 (no disproportion), inconsistent counts, and the three rules.
Run with:  pytest
"""

import math

import pytest

from src.signals import (TwoByTwo, Thresholds, analyse, analyse_table, chi_square_yates,
                         explain, information_component, prr, ror, rule_breakdown,
                         two_by_two)

# Hand-worked example
#   a = 20 reports with drug + event
#   drug total (a+b) = 1,000      -> b = 980
#   event total (a+c) = 220       -> c = 200
#   database N = 101,000          -> d = 101,000 - 1,000 - 220 + 20 = 99,800
T = TwoByTwo(20, 980, 200, 99_800)


# ---------------------------------------------------------------- normal counts

def test_two_by_two_from_openfda_counts():
    assert two_by_two(20, 1_000, 220, 101_000) == T
    assert T.n == 101_000


def test_prr_by_hand():
    # PRR = (20/1000) / (200/100000) = 0.02 / 0.002 = 10
    est = prr(T)
    assert est.value == pytest.approx(10.0)
    se = math.sqrt(1 / 20 - 1 / 1000 + 1 / 200 - 1 / 100_000)
    assert est.lower == pytest.approx(10 * math.exp(-1.96 * se))
    assert est.upper == pytest.approx(10 * math.exp(1.96 * se))
    assert est.note is None


def test_ror_by_hand():
    # ROR = (20 * 99800) / (980 * 200) = 1,996,000 / 196,000 = 10.1837
    est = ror(T)
    assert est.value == pytest.approx(10.183673, rel=1e-6)
    se = math.sqrt(1 / 20 + 1 / 980 + 1 / 200 + 1 / 99_800)
    assert est.lower == pytest.approx(est.value * math.exp(-1.96 * se))
    assert est.upper == pytest.approx(est.value * math.exp(1.96 * se))


def test_chi_square_yates_by_hand():
    n = 101_000
    expected = n * (abs(20 * 99_800 - 980 * 200) - n / 2) ** 2 / (1_000 * 100_000 * 220 * 100_780)
    assert chi_square_yates(T) == pytest.approx(expected)
    assert chi_square_yates(T) > 4


def test_ic_by_hand():
    # E = 1000 * 220 / 101000 = 2.17822; IC = log2(20.5 / 2.67822) = 2.9363
    ic, ic025 = information_component(T)
    assert ic == pytest.approx(2.936279, abs=1e-5)
    assert ic025 == pytest.approx(2.185883, abs=1e-5)
    assert ic025 < ic


def test_all_three_rules_met_for_strong_pair():
    res = analyse_table(T)
    assert (res.rules.prr, res.rules.ror, res.rules.ic) == (True, True, True)
    assert res.rules.label == "3 of 3"
    assert not res.small_numbers


# ---------------------------------------------------------------- PRR = 1

def test_no_disproportion_gives_prr_one_and_no_rules():
    # Event is 1% of drug reports and 1% of other reports
    res = analyse(10, 1_000, 1_010, 101_000)
    assert res.prr.value == pytest.approx(1.0)
    assert res.ror.value == pytest.approx(1.0)
    assert res.chi2 == pytest.approx(0.0)          # Yates correction floors at 0
    assert res.ic < 0.1                             # shrinkage pulls IC slightly negative
    assert res.rules.count == 0
    assert res.rules.label == "0 of 3"


# ---------------------------------------------------------------- a = 0

def test_a_zero_prr_ror_not_computable_but_ic_computed():
    res = analyse_table(TwoByTwo(0, 1_000, 200, 99_800))
    assert res.prr.value is None and res.prr.note == "not computable (a = 0)"
    assert res.ror.value is None and res.ror.note == "not computable (a = 0)"
    assert res.ic is not None and res.ic < 0
    assert res.ic025 < 0
    assert res.rules.count == 0
    assert res.small_numbers


# ---------------------------------------------------------------- b, c, d = 0

@pytest.mark.parametrize("cells, name", [
    ((5, 0, 200, 99_800), "b"),
    ((5, 995, 0, 99_800), "c"),
    ((5, 995, 200, 0), "d"),
])
def test_ror_not_computable_with_any_zero_cell(cells, name):
    res = analyse_table(TwoByTwo(*cells))
    assert res.ror.value is None and res.ror.note == f"not computable ({name} = 0)"
    assert not res.rules.ror
    assert res.ic is not None          # IC is still computed


def test_prr_needs_only_a_and_c():
    # c = 0 -> PRR not computable (division by zero)
    res = analyse_table(TwoByTwo(5, 995, 0, 99_800))
    assert res.prr.value is None and res.prr.note == "not computable (c = 0)"
    assert not res.rules.prr


@pytest.mark.parametrize("cells", [(10, 0, 100, 500), (10, 90, 100, 0)])
def test_prr_computable_when_b_or_d_is_zero(cells):
    # Reviewer example: a=10, b=0, c=100, d=500 -> PRR = (10/10) / (100/600) = 6.0
    t = TwoByTwo(*cells)
    res = analyse_table(t)
    expected = (t.a / (t.a + t.b)) / (t.c / (t.c + t.d))
    assert res.prr.value == pytest.approx(expected)
    assert res.prr.lower < res.prr.value < res.prr.upper
    assert res.prr.note is None
    assert res.ror.value is None       # ROR still needs all four cells


def test_prr_b_zero_value_by_hand():
    assert analyse_table(TwoByTwo(10, 0, 100, 500)).prr.value == pytest.approx(6.0)


# ---------------------------------------------------------------- small numbers

@pytest.mark.parametrize("a", [1, 2, 3, 4])
def test_small_numbers_warning(a):
    res = analyse(a, 1_000, a + 2, 1_000_000)      # strong ratio, tiny counts
    assert res.small_numbers
    assert not analyse(5, 1_000, 7, 1_000_000).small_numbers


@pytest.mark.parametrize("a", [1, 2])
def test_prr_and_ror_rules_need_three_cases(a):
    res = analyse(a, 1_000, a + 2, 1_000_000)
    assert res.prr.value > 2                        # ratio high ...
    assert not res.rules.prr and not res.rules.ror  # ... but a < 3


def test_ic_shrinks_small_counts():
    # Same observed/expected ratio, fewer reports -> lower IC (shrinkage)
    small = analyse_table(TwoByTwo(2, 998, 20, 998_980))
    large = analyse_table(TwoByTwo(200, 99_800, 2_000, 99_898_000))
    assert small.ic < large.ic
    assert small.ic025 < large.ic025


# ---------------------------------------------------------------- rules + thresholds

def test_thresholds_change_rules():
    assert analyse_table(T).rules.prr
    assert not analyse_table(T, Thresholds(cases_min=25)).rules.prr
    assert not analyse_table(T, Thresholds(prr_min=20)).rules.prr
    assert not analyse_table(T, Thresholds(ic025_min=3)).rules.ic


# ---------------------------------------------------------------- inconsistent counts

def test_inconsistent_counts_raise():
    with pytest.raises(ValueError, match="negative cell"):
        two_by_two(50, 40, 100, 1_000)   # more drug+event reports than drug reports


# ---------------------------------------------------------------- plain language

def test_explanation_text():
    text = explain(T, "RHABDOMYOLYSIS")
    assert "2.0% of reports for this drug (20 of 1,000)" in text
    assert "0.2% of reports for all other drugs (200 of 100,000)" in text


# ---------------------------------------------------------------- rule breakdown

def test_rule_breakdown_counts():
    rows = [
        {"PRR rule": True, "ROR rule": True, "IC rule": True, "Rules met": 3, "Small numbers": False},
        {"PRR rule": False, "ROR rule": False, "IC rule": True, "Rules met": 1, "Small numbers": True},
        {"PRR rule": False, "ROR rule": False, "IC rule": False, "Rules met": 0, "Small numbers": True},
    ]
    b = rule_breakdown(rows)
    assert (b["screened"], b["prr"], b["ror"], b["ic"]) == (3, 1, 1, 2)
    assert (b["met_0"], b["met_1"], b["met_2"], b["met_3"]) == (1, 1, 0, 1)
    assert b["ic_only"] == 1
    assert b["flagged_small_numbers"] == 1     # the 0-rule small-number row is not counted

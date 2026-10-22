"""Disproportionality statistics for spontaneous adverse event reports.

The 2x2 table for one drug (D) and one reaction (R):

                     Reaction R    All other reactions
    Drug D               a                 b
    All other drugs      c                 d

    a = reports with D and R
    b = reports with D but not R
    c = reports with R but not D
    d = reports with neither

PRR  = [a / (a+b)] / [c / (c+d)]
ROR  = (a*d) / (b*c)
95% CIs use the standard log-normal approximation.
Chi-square uses Yates' continuity correction (as in Evans et al., 2001).
"""

import math
from dataclasses import dataclass


@dataclass
class SignalResult:
    a: int
    b: int
    c: int
    d: int
    prr: float
    prr_lower: float
    prr_upper: float
    ror: float
    ror_lower: float
    ror_upper: float
    chi2: float


NAN = float("nan")


def two_by_two(drug_reaction: int, drug_total: int,
               reaction_total: int, all_total: int) -> tuple[int, int, int, int]:
    """Turn the four counts openFDA gives us into the a, b, c, d cells."""
    a = drug_reaction
    b = drug_total - drug_reaction
    c = reaction_total - drug_reaction
    d = all_total - drug_total - reaction_total + drug_reaction
    if min(a, b, c, d) < 0:
        raise ValueError(
            f"Inconsistent counts give a negative cell: a={a}, b={b}, c={c}, d={d}"
        )
    return a, b, c, d


def prr(a: int, b: int, c: int, d: int, z: float = 1.96) -> tuple[float, float, float]:
    """Proportional Reporting Ratio with 95% confidence interval."""
    if a == 0 or c == 0 or (a + b) == 0 or (c + d) == 0:
        return NAN, NAN, NAN
    value = (a / (a + b)) / (c / (c + d))
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    return value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se)


def ror(a: int, b: int, c: int, d: int, z: float = 1.96) -> tuple[float, float, float]:
    """Reporting Odds Ratio with 95% confidence interval."""
    if 0 in (a, b, c, d):
        return NAN, NAN, NAN
    value = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se)


def chi_square_yates(a: int, b: int, c: int, d: int) -> float:
    """Chi-square statistic (1 degree of freedom) with Yates' correction."""
    n = a + b + c + d
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        return NAN
    diff = max(abs(a * d - b * c) - n / 2, 0)
    return n * diff ** 2 / denom


def analyse(drug_reaction: int, drug_total: int,
            reaction_total: int, all_total: int) -> SignalResult:
    """Full calculation for one drug-reaction pair."""
    a, b, c, d = two_by_two(drug_reaction, drug_total, reaction_total, all_total)
    p, pl, pu = prr(a, b, c, d)
    r, rl, ru = ror(a, b, c, d)
    return SignalResult(a, b, c, d, p, pl, pu, r, rl, ru, chi_square_yates(a, b, c, d))


def is_signal(result: SignalResult, prr_min: float, cases_min: int, chi2_min: float) -> bool:
    """Evans criteria: PRR >= prr_min, a >= cases_min, chi-square >= chi2_min."""
    if math.isnan(result.prr) or math.isnan(result.chi2):
        return False
    return result.prr >= prr_min and result.a >= cases_min and result.chi2 >= chi2_min

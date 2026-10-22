"""Disproportionality statistics for spontaneous adverse event reports (spec section 4).

The 2x2 table for one drug and one event (counts are numbers of REPORTS):

                     Event         All other events
    Drug                a                 b
    All other drugs     c                 d

    a = reports with the drug and the event
    b = reports with the drug but not the event
    c = reports with the event but not the drug
    d = reports with neither          N = a + b + c + d

PRR = [a/(a+b)] / [c/(c+d)]            95% CI: exp(ln PRR +/- 1.96*SE),
                                       SE = sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
ROR = (a*d) / (b*c)                    95% CI: exp(ln ROR +/- 1.96*SE),
                                       SE = sqrt(1/a + 1/b + 1/c + 1/d)
Chi-square, Yates-corrected, 1 df:     N * (|ad - bc| - N/2)^2 / [(a+b)(c+d)(a+c)(b+d)]
                                       (|ad - bc| - N/2 is set to 0 if negative)
IC  = log2[(a + 0.5) / (E + 0.5)],     E = (a+b)(a+c)/N  (expected count)
IC025 ~ IC - 3.3(a+0.5)^-1/2 - 2(a+0.5)^-3/2
    Noren GN, Hopstadius J, Bate A. Stat Methods Med Res 2013;22(1):57-69.
    The +0.5 terms shrink small counts towards "no association" (IC = 0).

Zero cells: if any of a, b, c, d is 0, PRR and ROR are reported as
"not computable" with the reason. No continuity correction is applied.
IC is still computed (the shrinkage handles a = 0).

These statistics measure disproportionate reporting. They do not show causation.
"""

import math
from dataclasses import dataclass

from src import config

NAN = float("nan")
Z95 = 1.96


# ---------------------------------------------------------------------------
# Thresholds for the predefined rules (defaults come from config.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    prr_min: float = config.PRR_MIN
    prr_cases_min: int = config.PRR_CASES_MIN
    chi2_min: float = config.CHI2_MIN
    ror_lower_min: float = config.ROR_LOWER_MIN
    ror_cases_min: int = config.ROR_CASES_MIN
    ic025_min: float = config.IC025_MIN
    small_numbers_below: int = config.SMALL_NUMBERS_BELOW


# ---------------------------------------------------------------------------
# The 2x2 table
# ---------------------------------------------------------------------------

def two_by_two(drug_reaction: int, drug_total: int,
               reaction_total: int, all_total: int) -> tuple[int, int, int, int]:
    """Turn the four openFDA counts into the a, b, c, d cells.

    drug_reaction = a, drug_total = a+b, reaction_total = a+c, all_total = N.
    Raises ValueError if the counts are inconsistent (a negative cell).
    """
    a = drug_reaction
    b = drug_total - drug_reaction
    c = reaction_total - drug_reaction
    d = all_total - drug_total - reaction_total + drug_reaction
    if min(a, b, c, d) < 0:
        raise ValueError(
            f"Inconsistent counts give a negative cell: a={a}, b={b}, c={c}, d={d}"
        )
    return a, b, c, d


def zero_cell_note(a: int, b: int, c: int, d: int) -> str:
    """'' if all cells are above 0, else e.g. 'not computable (a = 0)'."""
    zeros = [f"{name} = 0" for name, v in zip("abcd", (a, b, c, d)) if v == 0]
    return f"not computable ({', '.join(zeros)})" if zeros else ""


# ---------------------------------------------------------------------------
# The measures
# ---------------------------------------------------------------------------

def prr(a: int, b: int, c: int, d: int, z: float = Z95) -> tuple[float, float, float]:
    """PRR with 95% CI. (NaN, NaN, NaN) if any cell is 0."""
    if zero_cell_note(a, b, c, d):
        return NAN, NAN, NAN
    value = (a / (a + b)) / (c / (c + d))
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    return value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se)


def ror(a: int, b: int, c: int, d: int, z: float = Z95) -> tuple[float, float, float]:
    """ROR with 95% CI. (NaN, NaN, NaN) if any cell is 0."""
    if zero_cell_note(a, b, c, d):
        return NAN, NAN, NAN
    value = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se)


def chi_square_yates(a: int, b: int, c: int, d: int) -> float:
    """Yates-corrected chi-square, 1 df. NaN if a row or column total is 0."""
    n = a + b + c + d
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        return NAN
    diff = max(abs(a * d - b * c) - n / 2, 0)
    return n * diff ** 2 / denom


def expected_count(a: int, b: int, c: int, d: int) -> float:
    """E = (a+b)(a+c)/N: reports expected if drug and event were unrelated."""
    n = a + b + c + d
    return NAN if n == 0 else (a + b) * (a + c) / n


def information_component(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    """IC and IC025 (Noren et al. 2013 approximation). Works when a = 0."""
    e = expected_count(a, b, c, d)
    if math.isnan(e):
        return NAN, NAN
    ic = math.log2((a + 0.5) / (e + 0.5))
    ic025 = ic - 3.3 * (a + 0.5) ** -0.5 - 2 * (a + 0.5) ** -1.5
    return ic, ic025


# ---------------------------------------------------------------------------
# One full result per drug-event pair
# ---------------------------------------------------------------------------

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
    expected: float
    ic: float
    ic025: float
    ratio_note: str        # '' or 'not computable (<cell> = 0)', applies to PRR and ROR
    prr_rule: bool
    ror_rule: bool
    ic_rule: bool
    small_numbers: bool    # a below the small-numbers threshold

    @property
    def rules_met(self) -> int:
        return int(self.prr_rule) + int(self.ror_rule) + int(self.ic_rule)

    @property
    def n(self) -> int:
        return self.a + self.b + self.c + self.d


def _ok(x: float) -> bool:
    return not math.isnan(x)


def apply_rules(a: int, prr_value: float, chi2: float, ror_lower: float,
                ic025: float, t: Thresholds) -> tuple[bool, bool, bool]:
    """The three predefined rules. A measure that is not computable fails its rule."""
    prr_rule = (_ok(prr_value) and _ok(chi2) and prr_value >= t.prr_min
                and a >= t.prr_cases_min and chi2 >= t.chi2_min)
    ror_rule = _ok(ror_lower) and ror_lower > t.ror_lower_min and a >= t.ror_cases_min
    ic_rule = _ok(ic025) and ic025 > t.ic025_min
    return prr_rule, ror_rule, ic_rule


def analyse(drug_reaction: int, drug_total: int, reaction_total: int, all_total: int,
            thresholds: Thresholds = Thresholds()) -> SignalResult:
    """Full calculation for one drug-event pair from the four openFDA counts."""
    a, b, c, d = two_by_two(drug_reaction, drug_total, reaction_total, all_total)
    p, pl, pu = prr(a, b, c, d)
    r, rl, ru = ror(a, b, c, d)
    chi2 = chi_square_yates(a, b, c, d)
    ic, ic025 = information_component(a, b, c, d)
    prr_rule, ror_rule, ic_rule = apply_rules(a, p, chi2, rl, ic025, thresholds)
    return SignalResult(
        a=a, b=b, c=c, d=d,
        prr=p, prr_lower=pl, prr_upper=pu,
        ror=r, ror_lower=rl, ror_upper=ru,
        chi2=chi2, expected=expected_count(a, b, c, d), ic=ic, ic025=ic025,
        ratio_note=zero_cell_note(a, b, c, d),
        prr_rule=prr_rule, ror_rule=ror_rule, ic_rule=ic_rule,
        small_numbers=a < thresholds.small_numbers_below,
    )


# ---------------------------------------------------------------------------
# Plain-language text for the 2x2 detail panel
# ---------------------------------------------------------------------------

def _pct(x: float) -> str:
    if x == 0:
        return "0%"
    if x >= 0.01:
        return f"{x:.1%}"
    return f"{x:.2%}" if x >= 0.0001 else "<0.01%"


def explain(r: SignalResult) -> str:
    """e.g. 'The event makes up 2.0% of reports for this drug and 0.20% of
    reports for all other drugs.' plus a note on small numbers / zero cells."""
    parts = []
    if r.a + r.b > 0 and r.c + r.d > 0:
        parts.append(
            f"The event makes up {_pct(r.a / (r.a + r.b))} of reports for this drug "
            f"and {_pct(r.c / (r.c + r.d))} of reports for all other drugs."
        )
    if _ok(r.expected):
        parts.append(f"About {r.expected:.1f} reports would be expected if the drug and "
                     f"event were unrelated; {r.a} were observed.")
    if r.ratio_note:
        parts.append(f"PRR and ROR are {r.ratio_note}; no continuity correction is applied.")
    if r.small_numbers:
        parts.append(f"Small numbers (a = {r.a}): estimates are unstable.")
    return " ".join(parts)

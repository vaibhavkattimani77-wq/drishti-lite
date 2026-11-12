"""Disproportionality statistics for spontaneous reports (spec §4).

The 2x2 table for one drug and one event (counts are numbers of REPORTS):

                     Event      All other events    Total
    Drug               a               b             a+b
    All other drugs    c               d             c+d
    Total             a+c             b+d             N

    PRR  = [a/(a+b)] / [c/(c+d)]        95% CI: exp(ln PRR +/- 1.96*SE)
           SE = sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
    ROR  = (a*d) / (b*c)                95% CI: exp(ln ROR +/- 1.96*SE)
           SE = sqrt(1/a + 1/b + 1/c + 1/d)
    chi2 = Yates-corrected, 1 df:
           N * (max(|ad - bc| - N/2, 0))^2 / [(a+b)(c+d)(a+c)(b+d)]
    IC   = log2[(a + 0.5) / (E + 0.5)],  E = (a+b)(a+c)/N
    IC025 ~= IC - 3.3*(a+0.5)^-1/2 - 2*(a+0.5)^-3/2
           (Noren, Hopstadius & Bate, Stat Methods Med Res 2013;22:57-69)

Zero cells (no continuity correction):
  * PRR needs a > 0 and c > 0 (b = 0 or d = 0 still gives a valid PRR and CI).
  * ROR needs all four cells > 0.
  * IC is always computed; the +0.5 terms shrink small counts towards
    "no association".

Chi-square note: the max(..., 0) stops the Yates correction from producing a
positive value when |ad - bc| < N/2 (i.e. when there is essentially no
association). Use MAX(ABS(a*d-b*c)-N/2, 0) in the Excel reference check too.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src import config


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TwoByTwo:
    a: int
    b: int
    c: int
    d: int

    @property
    def n(self) -> int:
        return self.a + self.b + self.c + self.d

    @property
    def drug_total(self) -> int:       # a + b
        return self.a + self.b

    @property
    def other_total(self) -> int:      # c + d
        return self.c + self.d

    @property
    def event_total(self) -> int:      # a + c
        return self.a + self.c

    @property
    def non_event_total(self) -> int:  # b + d
        return self.b + self.d

    def first_zero_cell(self) -> str | None:
        for name in ("a", "b", "c", "d"):
            if getattr(self, name) == 0:
                return name
        return None


@dataclass(frozen=True)
class Estimate:
    """A ratio with its 95% interval, or a reason it could not be computed."""
    value: float | None
    lower: float | None
    upper: float | None
    note: str | None = None          # e.g. "not computable (b = 0)"

    @property
    def computable(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Thresholds:
    prr_min: float = config.PRR_MIN
    cases_min: int = config.CASES_MIN
    chi2_min: float = config.CHI2_MIN
    ror_lower_min: float = config.ROR_LOWER_MIN
    ic025_min: float = config.IC025_MIN

    def as_dict(self) -> dict:
        return {
            "PRR rule": f"PRR >= {self.prr_min} and a >= {self.cases_min} and chi2 >= {self.chi2_min}",
            "ROR rule": f"ROR lower 95% CI > {self.ror_lower_min} and a >= {self.cases_min}",
            "IC rule": f"IC025 > {self.ic025_min}",
        }


@dataclass(frozen=True)
class RulesMet:
    prr: bool
    ror: bool
    ic: bool

    @property
    def count(self) -> int:
        return int(self.prr) + int(self.ror) + int(self.ic)

    @property
    def label(self) -> str:
        return f"{self.count} of 3"


@dataclass(frozen=True)
class SignalResult:
    table: TwoByTwo
    prr: Estimate
    ror: Estimate
    chi2: float | None
    ic: float | None
    ic025: float | None
    rules: RulesMet
    small_numbers: bool


# ---------------------------------------------------------------------------
# 2x2 table
# ---------------------------------------------------------------------------

def two_by_two(drug_event: int, drug_total: int, event_total: int, all_total: int) -> TwoByTwo:
    """Build the 2x2 table from the four counts openFDA returns.

    drug_event = a, drug_total = a+b, event_total = a+c, all_total = N.
    Raises ValueError if the counts are inconsistent (a negative cell).
    """
    a = drug_event
    b = drug_total - drug_event
    c = event_total - drug_event
    d = all_total - drug_total - event_total + drug_event
    if min(a, b, c, d) < 0:
        raise ValueError(
            f"Inconsistent openFDA counts give a negative cell (a={a}, b={b}, c={c}, d={d}); "
            "calculation stopped for this pair."
        )
    return TwoByTwo(a, b, c, d)


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------

def _not_computable(t: TwoByTwo, cells: tuple[str, ...]) -> Estimate | None:
    for name in cells:
        if getattr(t, name) == 0:
            return Estimate(None, None, None, f"not computable ({name} = 0)")
    return None


def prr(t: TwoByTwo, z: float = config.Z_95) -> Estimate:
    """Proportional reporting ratio with 95% CI. Needs a > 0 and c > 0."""
    if (nc := _not_computable(t, ("a", "c"))) is not None:
        return nc
    a, b, c, d = t.a, t.b, t.c, t.d
    value = (a / (a + b)) / (c / (c + d))
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    return Estimate(value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se))


def ror(t: TwoByTwo, z: float = config.Z_95) -> Estimate:
    """Reporting odds ratio with 95% CI. Needs all four cells > 0."""
    if (nc := _not_computable(t, ("a", "b", "c", "d"))) is not None:
        return nc
    a, b, c, d = t.a, t.b, t.c, t.d
    value = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return Estimate(value, math.exp(math.log(value) - z * se), math.exp(math.log(value) + z * se))


def chi_square_yates(t: TwoByTwo) -> float | None:
    """Yates-corrected chi-square, 1 df. None if a margin is zero."""
    denom = t.drug_total * t.other_total * t.event_total * t.non_event_total
    if denom == 0:
        return None
    diff = max(abs(t.a * t.d - t.b * t.c) - t.n / 2, 0)
    return t.n * diff ** 2 / denom


def expected_count(t: TwoByTwo) -> float | None:
    """E = (a+b)(a+c)/N: reports expected with the drug and event if unrelated."""
    if t.n == 0:
        return None
    return t.drug_total * t.event_total / t.n


def information_component(t: TwoByTwo) -> tuple[float | None, float | None]:
    """IC and its approximate lower 95% limit IC025 (Noren et al. 2013)."""
    e = expected_count(t)
    if e is None:
        return None, None
    ic = math.log2((t.a + 0.5) / (e + 0.5))
    ic025 = ic - 3.3 * (t.a + 0.5) ** -0.5 - 2 * (t.a + 0.5) ** -1.5
    return ic, ic025


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def evaluate_rules(t: TwoByTwo, p: Estimate, r: Estimate, chi2: float | None,
                   ic025: float | None, th: Thresholds) -> RulesMet:
    prr_ok = (p.computable and chi2 is not None
              and p.value >= th.prr_min and t.a >= th.cases_min and chi2 >= th.chi2_min)
    ror_ok = r.computable and r.lower > th.ror_lower_min and t.a >= th.cases_min
    ic_ok = ic025 is not None and ic025 > th.ic025_min
    return RulesMet(bool(prr_ok), bool(ror_ok), bool(ic_ok))


def analyse_table(t: TwoByTwo, th: Thresholds = Thresholds()) -> SignalResult:
    p, r = prr(t), ror(t)
    chi2 = chi_square_yates(t)
    ic, ic025 = information_component(t)
    return SignalResult(
        table=t, prr=p, ror=r, chi2=chi2, ic=ic, ic025=ic025,
        rules=evaluate_rules(t, p, r, chi2, ic025, th),
        small_numbers=t.a < config.SMALL_NUMBERS_BELOW,
    )


def analyse(drug_event: int, drug_total: int, event_total: int, all_total: int,
            th: Thresholds = Thresholds()) -> SignalResult:
    """Full calculation for one drug-event pair from the four openFDA counts."""
    return analyse_table(two_by_two(drug_event, drug_total, event_total, all_total), th)


# ---------------------------------------------------------------------------
# How the rules behave across a whole screen
# ---------------------------------------------------------------------------

def rule_breakdown(rows: list[dict]) -> dict:
    """Counts per rule and per number of rules met, for rows with the keys
    'PRR rule', 'ROR rule', 'IC rule', 'Rules met' and 'Small numbers'.
    Rows that stopped with an error (key 'Error' set) are left out."""
    rows = [r for r in rows if not r.get("Error")]
    n = len(rows)
    flagged = [r for r in rows if r["Rules met"] > 0]
    return {
        "screened": n,
        "prr": sum(bool(r["PRR rule"]) for r in rows),
        "ror": sum(bool(r["ROR rule"]) for r in rows),
        "ic": sum(bool(r["IC rule"]) for r in rows),
        "met_0": sum(r["Rules met"] == 0 for r in rows),
        "met_1": sum(r["Rules met"] == 1 for r in rows),
        "met_2": sum(r["Rules met"] == 2 for r in rows),
        "met_3": sum(r["Rules met"] == 3 for r in rows),
        "ic_only": sum(r["Rules met"] == 1 and bool(r["IC rule"]) for r in rows),
        "flagged_small_numbers": sum(bool(r["Small numbers"]) for r in flagged),
    }


# ---------------------------------------------------------------------------
# Plain-language helpers (used by the detail panel)
# ---------------------------------------------------------------------------

def _pct(x: float) -> str:
    p = 100 * x
    if p == 0:
        return "0%"
    if p >= 10:
        return f"{p:.0f}%"
    if p >= 1:
        return f"{p:.1f}%"
    return f"{p:.2g}%"


def explain(t: TwoByTwo, event: str) -> str:
    """'The event makes up 1.6% of reports for this drug and 0.04% for all other drugs.'"""
    if t.drug_total == 0 or t.other_total == 0:
        return "Not enough reports to describe the proportions."
    return (f"{event.capitalize()} makes up {_pct(t.a / t.drug_total)} of reports for this drug "
            f"({t.a:,} of {t.drug_total:,}) and {_pct(t.c / t.other_total)} of reports for all "
            f"other drugs ({t.c:,} of {t.other_total:,}).")

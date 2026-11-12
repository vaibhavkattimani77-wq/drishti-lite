"""Exploratory prioritisation score (spec §5, Screen 2). NOT a validated model.

    Factor                                   Points
    Not found in searched label text           +2
    Possibly labelled                          +1
    On EMA DME list                            +2
    >= 1 report with fatal outcome             +2
    > 50% of reports serious                   +1
    Rules met 3/3 (+2) or 2/3 (+1)            0-2
    Increasing reporting                       +1
    Maximum 10. Higher >= 7, Medium 4-6, Lower <= 3.

Each factor is shown with its points, the evidence behind it and why it counts.
The weights are a documented design choice, not a validated model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import requests

from src import config
from src.label_check import LABELLED, NOT_FOUND, POSSIBLY, UNAVAILABLE
from src.openfda_client import (Filters, drug_clause, escaped_reaction_clause,
                                reaction_clause)
from src.trend import INCREASING

SCORE_NOTE = ("Exploratory prioritisation score with documented but unvalidated weights. "
              "It orders pairs for review; it is not a measure of risk or causality.")


@dataclass
class SeriousnessCounts:
    reports: int            # a: reports with drug and event (same filters as the screen)
    serious: int            # of which serious
    fatal: int              # of which with a fatal outcome (seriousnessdeath)

    @property
    def serious_share(self) -> float | None:
        return self.serious / self.reports if self.reports else None


@dataclass
class Factor:
    name: str
    points: int
    max_points: int
    evidence: str
    rationale: str


@dataclass
class ScoreResult:
    total: int
    band: str
    factors: list[Factor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def band(total: int) -> str:
    if total >= config.BAND_HIGHER_MIN:
        return "Higher"
    if total >= config.BAND_MEDIUM_MIN:
        return "Medium"
    return "Lower"


def fetch_seriousness(client, generic_name: str, event: str, filters: Filters) -> SeriousnessCounts:
    """Counts of all, serious and fatal reports for the pair (report-level flags)."""
    def count(extra: list[str]) -> int:
        base = [drug_clause(generic_name)] + filters.clauses() + extra
        try:
            return client.total(base + [reaction_clause(event)])
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 400:
                raise
            return client.total(base + [escaped_reaction_clause(event)])

    return SeriousnessCounts(count([]), count(["serious:1"]), count(["seriousnessdeath:1"]))


def score(label_status: str, on_dme: bool, seriousness: SeriousnessCounts,
          rules_met: int, trend_status: str | None) -> ScoreResult:
    f: list[Factor] = []

    # Label
    if label_status == NOT_FOUND:
        pts, ev = config.SCORE_NOT_FOUND_IN_LABEL, "Not found in searched label text"
    elif label_status == POSSIBLY:
        pts, ev = config.SCORE_POSSIBLY_LABELLED, "Possibly labelled (reviewer must confirm)"
    elif label_status == LABELLED:
        pts, ev = 0, "Labelled"
    else:
        pts, ev = 0, "Label unavailable: check manually (no points given)"
    f.append(Factor("Label", pts, config.SCORE_NOT_FOUND_IN_LABEL, ev,
                    "Possibly unexpected if not in the label, but needs confirmation; "
                    "'not found' is not the same as 'new'."))

    # DME
    f.append(Factor("EMA DME list", config.SCORE_DME if on_dme else 0, config.SCORE_DME,
                    "On the list" if on_dme else "Not on the list",
                    "Event class of known regulatory concern."))

    # Fatal outcome
    fatal = seriousness.fatal
    f.append(Factor("Fatal outcome", config.SCORE_FATAL if fatal >= 1 else 0, config.SCORE_FATAL,
                    f"{fatal:,} of {seriousness.reports:,} reports with a fatal outcome",
                    "Report-level death; not necessarily caused by the event or the drug."))

    # Seriousness
    share = seriousness.serious_share
    mostly = share is not None and share > 0.5
    f.append(Factor("Seriousness", config.SCORE_MOSTLY_SERIOUS if mostly else 0,
                    config.SCORE_MOSTLY_SERIOUS,
                    "not computable (0 reports)" if share is None else
                    f"{seriousness.serious:,} of {seriousness.reports:,} reports serious ({share:.0%})",
                    "Seriousness pattern (more than half of reports serious)."))

    # Rules met
    rpts = config.SCORE_RULES_3 if rules_met == 3 else config.SCORE_RULES_2 if rules_met == 2 else 0
    f.append(Factor("Rules met", rpts, config.SCORE_RULES_3, f"{rules_met} of 3",
                    "Consistency across predefined rules (they share one 2×2 table, so this "
                    "is consistency, not independent confirmation)."))

    # Trend
    inc = trend_status == INCREASING
    f.append(Factor("Reporting trend", config.SCORE_INCREASING if inc else 0,
                    config.SCORE_INCREASING, trend_status or "not available",
                    "Possible emerging pattern; increases often reflect stimulated reporting."))

    total = sum(x.points for x in f)
    return ScoreResult(min(total, config.SCORE_MAX), band(total), f)

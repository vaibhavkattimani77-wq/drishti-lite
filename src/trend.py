"""Quarterly reporting trend for one drug-event pair (spec §4.5).

* Reports per calendar quarter by FDA receipt date.
* The incomplete quarter is excluded. "Incomplete" is judged against the
  openFDA data date (meta.last_updated), not today's date: the quarter that
  contains last_updated is incomplete unless last_updated is its final day.
* "Increasing reporting": last 4 complete quarters >= 1.5 x previous 4, and
  >= 3 reports in the last 4.
* "Decreasing reporting": ratio <= 0.67.
* Otherwise "No substantial change".
* Fewer than 6 reports across the 8 quarters -> "Insufficient data".
* Quarters with no reports count as 0 (they are filled in, not dropped).

The labels describe reporting volume, not risk: changes often reflect stimulated
reporting, publicity, label changes or changes in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from src import config
from src.openfda_client import Filters, OpenFDAClient, date_clause, drug_clause, reaction_clause


INCREASING = "Increasing reporting"
DECREASING = "Decreasing reporting"
NO_CHANGE = "No substantial change"
INSUFFICIENT = "Insufficient data"


@dataclass(frozen=True)
class TrendResult:
    status: str                 # one of the STATUS_* labels below
    recent: int                 # reports in the last 4 complete quarters
    previous: int               # reports in the 4 quarters before
    ratio: float | None         # recent / previous (None if previous = 0)
    total: int

    @property
    def ratio_text(self) -> str:
        if self.ratio is None:
            return "not computable (0 reports in the previous 4 quarters)"
        return f"{self.ratio:.2f}"


def parse_data_date(last_updated: str | None) -> date:
    """openFDA gives 'YYYY-MM-DD'. Falls back to today if missing."""
    try:
        return datetime.strptime(str(last_updated)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def complete_quarters(reference: date, n: int = config.TREND_QUARTERS) -> list[pd.Period]:
    """The n most recent COMPLETE calendar quarters up to the reference date."""
    q = pd.Period(reference, freq="Q")
    last_complete = q if reference == q.end_time.date() else q - 1
    return [last_complete - i for i in range(n - 1, -1, -1)]     # oldest first


def daily_to_quarters(daily: dict[str, int], quarters: list[pd.Period]) -> pd.DataFrame:
    """Sum daily counts ('YYYYMMDD' -> n) into the given quarters, filling gaps with 0."""
    totals = {q: 0 for q in quarters}
    for day, n in daily.items():
        q = pd.Period(datetime.strptime(str(day), "%Y%m%d"), freq="Q")
        if q in totals:
            totals[q] += n
    return pd.DataFrame({
        "Quarter": [str(q) for q in quarters],
        "Quarter start": [q.start_time for q in quarters],
        "Reports": [totals[q] for q in quarters],
    })


def classify(counts: list[int]) -> TrendResult:
    """Apply the trend rule to 8 quarterly counts (oldest first)."""
    if len(counts) != config.TREND_QUARTERS:
        raise ValueError(f"Need {config.TREND_QUARTERS} quarterly counts, got {len(counts)}")
    half = config.TREND_QUARTERS // 2
    previous, recent = sum(counts[:half]), sum(counts[half:])
    total = previous + recent
    ratio = recent / previous if previous > 0 else None

    if total < config.TREND_MIN_TOTAL:
        status = INSUFFICIENT
    elif (ratio is None or ratio >= config.TREND_RISING_RATIO) and recent >= config.TREND_MIN_RECENT:
        status = INCREASING
    elif ratio is not None and ratio <= config.TREND_FALLING_RATIO:
        status = DECREASING
    else:
        status = NO_CHANGE
    return TrendResult(status, recent, previous, ratio, total)


def quarterly_trend(client: OpenFDAClient, generic_name: str, event: str, filters: Filters,
                    data_date: date) -> tuple[pd.DataFrame, TrendResult]:
    """Fetch daily counts for the 8-quarter window and apply the trend rule.

    The query is limited to the window (about 730 days), so openFDA's
    1,000-value cap on count queries cannot truncate it.
    """
    quarters = complete_quarters(data_date)
    start = quarters[0].start_time.strftime("%Y%m%d")
    end = quarters[-1].end_time.strftime("%Y%m%d")
    search = ([drug_clause(generic_name), reaction_clause(event)]
              + filters.clauses() + [date_clause(start, end)])
    daily = client.counts(search, "receivedate", limit=1000)
    df = daily_to_quarters(daily, quarters)
    return df, classify(df["Reports"].tolist())

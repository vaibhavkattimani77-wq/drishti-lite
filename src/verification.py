"""Checks that openFDA count queries give REPORT counts (spec §3, data validation).

The screen takes a (drug + event) from a count query on the event field, and
a+c (event, whole database) from the background count query. Here the same
numbers are fetched a second, independent way: a direct search for reports
matching drug AND event (or the event alone), whose meta.results.total is a
number of reports. If both ways agree, the 2x2 cells are report counts.
"""

from __future__ import annotations

import pandas as pd

from src.openfda_client import Filters, OpenFDAClient, background_clauses, drug_clause, reaction_clause


def pick_pairs(table: pd.DataFrame, n: int = 3) -> list[str]:
    """A common, a middle and a rare event from the screen (by a)."""
    ok = table[table["Error"].isna()].sort_values("a", ascending=False).reset_index(drop=True)
    if ok.empty:
        return []
    idx = sorted({0, len(ok) // 2, len(ok) - 1})[:n]
    return [ok.loc[i, "Reaction (PT)"] for i in idx]


def verify_counts(client: OpenFDAClient, generic_name: str, filters: Filters,
                  table: pd.DataFrame, events: list[str] | None = None) -> list[dict]:
    events = events or pick_pairs(table)
    checks = []
    for term in events:
        row = table[table["Reaction (PT)"] == term].iloc[0]
        a_screen, ac_screen = int(row["a"]), int(row["a"] + row["c"])
        a_search = client.total([drug_clause(generic_name), reaction_clause(term)]
                                + filters.clauses())
        ac_search = client.total([reaction_clause(term)] + background_clauses(filters))
        checks.append({
            "event": term,
            "a (screen)": a_screen, "a (direct search)": a_search,
            "a+c (screen)": ac_screen, "a+c (direct search)": ac_search,
            "match": a_screen == a_search and ac_screen == ac_search,
        })
    return checks

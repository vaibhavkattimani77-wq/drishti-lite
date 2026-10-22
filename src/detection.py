"""(Formerly pipeline.py.) Turns openFDA counts into a ranked signal table and a quarterly trend."""

import pandas as pd

from src import config
from src.openfda_client import Filters, OpenFDAClient, drug_clause, reaction_clause
from src.signals import analyse, is_signal

REACTION_FIELD = "patient.reaction.reactionmeddrapt.exact"


def signal_table(client: OpenFDAClient, generic_name: str, filters: Filters,
                 top_n: int = config.TOP_N_REACTIONS,
                 prr_min: float = config.SIGNAL_PRR_MIN,
                 cases_min: int = config.SIGNAL_CASES_MIN,
                 chi2_min: float = config.SIGNAL_CHI2_MIN) -> tuple[pd.DataFrame, dict]:
    """One row per reaction reported with the drug, with PRR/ROR and a signal flag.

    Returns (table, totals) where totals holds the report counts used.
    """
    f = filters.clauses()
    drug = [drug_clause(generic_name)] + f

    all_total = client.total(f)            # every report in the (filtered) database
    drug_total = client.total(drug)        # reports mentioning the drug
    totals = {"all_reports": all_total, "drug_reports": drug_total}
    if drug_total == 0:
        return pd.DataFrame(), totals

    # a: reports with the drug AND each reaction (top N reactions for the drug)
    drug_reactions = dict(list(client.counts(drug, REACTION_FIELD).items())[:top_n])

    # a+c: reports with each reaction in the whole database.
    # One call gets the 1,000 most common reactions; rarer ones are asked one by one.
    background = client.counts(f, REACTION_FIELD, limit=1000)
    for term in drug_reactions:
        if term not in background:
            background[term] = client.total([reaction_clause(term)] + f)

    rows = []
    for term, a in drug_reactions.items():
        res = analyse(a, drug_total, background[term], all_total)
        rows.append({
            "Reaction (MedDRA PT)": term,
            "Cases (a)": res.a,
            "b": res.b, "c": res.c, "d": res.d,
            "PRR": res.prr, "PRR 95% low": res.prr_lower, "PRR 95% high": res.prr_upper,
            "ROR": res.ror, "ROR 95% low": res.ror_lower, "ROR 95% high": res.ror_upper,
            "Chi-square": res.chi2,
            "Signal": is_signal(res, prr_min, cases_min, chi2_min),
        })

    table = (pd.DataFrame(rows)
             .sort_values(["Signal", "PRR"], ascending=[False, False])
             .reset_index(drop=True))
    return table, totals


def quarterly_trend(client: OpenFDAClient, generic_name: str, reaction: str,
                    filters: Filters) -> pd.DataFrame:
    """Reports per calendar quarter for a drug-reaction pair, by FDA receipt date."""
    search = [drug_clause(generic_name), reaction_clause(reaction)] + filters.clauses()
    daily = client.counts(search, "receivedate", limit=1000)
    if not daily:
        return pd.DataFrame(columns=["Quarter", "Reports"])
    df = pd.DataFrame({"date": pd.to_datetime(list(daily.keys()), format="%Y%m%d"),
                       "Reports": list(daily.values())})
    df["Quarter"] = df["date"].dt.to_period("Q").dt.start_time
    return df.groupby("Quarter", as_index=False)["Reports"].sum()

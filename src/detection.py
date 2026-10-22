"""(Formerly pipeline.py.) Turns openFDA counts into a ranked signal table and a quarterly trend."""

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src import config
from src.dme import dme_list_version
from src.openfda_client import (Filters, OpenFDAClient, drug_clause, extraction_record,
                                reaction_clause)
from src.signals import Thresholds, analyse

REACTION_FIELD = "patient.reaction.reactionmeddrapt.exact"


def signal_table(client: OpenFDAClient, generic_name: str, filters: Filters,
                 top_n: int = config.TOP_N_REACTIONS,
                 thresholds: Thresholds = Thresholds()) -> tuple[pd.DataFrame, dict]:
    """One row per reaction reported with the drug: 2x2 cells, PRR/ROR/IC, rules met.

    Returns (table, totals) where totals holds the report counts used.
    A pair whose counts give a negative cell is kept as a row with an error
    message instead of statistics (spec 4.1).
    """
    f = filters.clauses()
    drug = [drug_clause(generic_name)] + f

    all_total = client.total(f)            # N: every report in the (filtered) database
    drug_total = client.total(drug)        # a+b: reports mentioning the drug (any role)
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
        row = {"Reaction (MedDRA PT)": term}
        try:
            r = analyse(a, drug_total, background[term], all_total, thresholds)
        except ValueError as err:
            row.update({"Cases (a)": a, "Error": str(err), "Rules met": 0})
            rows.append(row)
            continue
        row.update({
            "Cases (a)": r.a, "b": r.b, "c": r.c, "d": r.d,
            "PRR": r.prr, "PRR 95% low": r.prr_lower, "PRR 95% high": r.prr_upper,
            "ROR": r.ror, "ROR 95% low": r.ror_lower, "ROR 95% high": r.ror_upper,
            "Chi-square": r.chi2, "Expected (E)": r.expected,
            "IC": r.ic, "IC025": r.ic025,
            "PRR/ROR note": r.ratio_note,
            "PRR rule": r.prr_rule, "ROR rule": r.ror_rule, "IC rule": r.ic_rule,
            "Rules met": r.rules_met,
            "Small numbers": r.small_numbers,
            "Error": "",
        })
        rows.append(row)

    table = (pd.DataFrame(rows)
             .sort_values(["Rules met", "Cases (a)"], ascending=[False, False])
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


# ---------------------------------------------------------------------------
# One full analysis: table + extraction record, saved to disk
# ---------------------------------------------------------------------------

def run_detection(client: OpenFDAClient, generic_name: str, filters: Filters,
                  top_n: int = config.TOP_N_REACTIONS,
                  thresholds: Thresholds = Thresholds()) -> tuple[pd.DataFrame, dict]:
    """Build the results table and its extraction record (spec section 3)."""
    client.reset_tracking()
    table, totals = signal_table(client, generic_name, filters, top_n, thresholds)
    record = extraction_record(
        client, generic_name, filters, top_n,
        reactions_analysed=len(table), totals=totals,
        thresholds=asdict(thresholds), dme_version=dme_list_version(),
    )
    return table, record


def save_run(table: pd.DataFrame, record: dict,
             folder: str = config.EXTRACTIONS_DIR) -> Path:
    """Save record.json and results.csv in data/extractions/<extraction_id>/."""
    out = Path(folder) / record["extraction_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    table.to_csv(out / "results.csv", index=False)
    return out


if __name__ == "__main__":
    # Quick check from the terminal, e.g.:
    #   python -m src.detection ATORVASTATIN RHABDOMYOLYSIS
    import sys

    drug = sys.argv[1].upper() if len(sys.argv) > 1 else "ATORVASTATIN"
    event = sys.argv[2].upper() if len(sys.argv) > 2 else "RHABDOMYOLYSIS"

    table, record = run_detection(OpenFDAClient(), drug, Filters())
    if table.empty:
        sys.exit(f"No reports found with {drug} in {record['query_parameters']['drug_match_field']}.")
    folder = save_run(table, record)

    print(f"Drug reports matched: {record['counts']['drug_reports_matched']:,}")
    print(f"Database reports:     {record['counts']['database_reports_filtered']:,}")
    print(f"Reactions analysed:   {record['counts']['reactions_analysed']}")
    print(f"openFDA last updated: {record['openfda_last_updated']}")
    print(f"Pairs meeting >= 1 rule: {(table['Rules met'] > 0).sum()}")
    match = table[table["Reaction (MedDRA PT)"] == event]
    if match.empty:
        print(f"\n{event} is not among the top {record['query_parameters']['top_n_reactions']} reactions.")
    else:
        r = match.iloc[0]
        print(f"\n{event}: a = {r['Cases (a)']}, b = {r['b']}, c = {r['c']}, d = {r['d']}")
        print(f"  PRR {r['PRR']:.2f} ({r['PRR 95% low']:.2f}-{r['PRR 95% high']:.2f})"
              f" | ROR {r['ROR']:.2f} ({r['ROR 95% low']:.2f}-{r['ROR 95% high']:.2f})"
              f" | chi2 {r['Chi-square']:.2f} | IC {r['IC']:.2f} (IC025 {r['IC025']:.2f})")
        print(f"  Rules met: {r['Rules met']} of 3")
    print(f"\nSaved to {folder}")

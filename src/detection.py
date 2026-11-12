"""Builds the Detection results table for one drug (spec §5, Screen 1).

For each of the drug's top-N reported events (MedDRA PTs) we fetch the four
counts a, a+b, a+c and N with the SAME filters for drug and background, then
compute PRR/ROR/chi-square/IC and the three predefined rules.

A drug counts in any role (suspect, concomitant or interacting).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import pandas as pd

from src import config
from src.dme import DMEList
from src.openfda_client import (DRUG_FIELD, DRUG_FIELD_EXACT, DRUG_MATCHING_NOTE,
                                REACTION_FIELD, ExtractionRecord, Filters, OpenFDAClient,
                                UnsearchableTerm, background_clauses, drug_clause)
from src.signals import SignalResult, Thresholds, analyse, rule_breakdown


@dataclass
class DetectionResult:
    generic_name: str
    filters: Filters
    thresholds: Thresholds
    table: pd.DataFrame
    totals: dict
    name_variants: dict[str, int]        # harmonised generic-name strings that matched
    results: dict[str, SignalResult]     # PT -> full result (for the detail panel)
    record: ExtractionRecord


def _row(term: str, res: SignalResult | None, error: str | None, on_dme: bool) -> dict:
    if res is None:
        return {"Reaction (PT)": term, "a": None, "b": None, "c": None, "d": None,
                "PRR": None, "PRR low": None, "PRR high": None, "PRR note": None,
                "ROR": None, "ROR low": None, "ROR high": None, "ROR note": None,
                "Chi-square": None, "IC": None, "IC025": None,
                "PRR rule": False, "ROR rule": False, "IC rule": False, "Rules met": 0,
                "Small numbers": False, "DME": on_dme, "Error": error}
    t = res.table
    return {
        "Reaction (PT)": term, "a": t.a, "b": t.b, "c": t.c, "d": t.d,
        "PRR": res.prr.value, "PRR low": res.prr.lower, "PRR high": res.prr.upper,
        "PRR note": res.prr.note,
        "ROR": res.ror.value, "ROR low": res.ror.lower, "ROR high": res.ror.upper,
        "ROR note": res.ror.note,
        "Chi-square": res.chi2, "IC": res.ic, "IC025": res.ic025,
        "PRR rule": res.rules.prr, "ROR rule": res.rules.ror, "IC rule": res.rules.ic,
        "Rules met": res.rules.count,
        "Small numbers": res.small_numbers, "DME": on_dme, "Error": None,
    }


def run_detection(client: OpenFDAClient, generic_name: str, filters: Filters,
                  thresholds: Thresholds, dme: DMEList,
                  top_n: int = config.TOP_N_REACTIONS) -> DetectionResult:
    generic_name = generic_name.strip().upper()
    f = background_clauses(filters)         # filters, or "all reports" if none
    drug = [drug_clause(generic_name)] + filters.clauses()

    client.last_updated()
    all_total = client.total(f)            # N: every report in the (filtered) database
    drug_total = client.total(drug)        # a+b: reports mentioning the drug (any role)

    # a: reports with the drug AND each of its top-N events
    drug_events = client.counts(drug, REACTION_FIELD, limit=top_n) if drug_total else {}
    drug_events = dict(list(drug_events.items())[:top_n])

    # a+c: reports with each event in the whole (filtered) database.
    # One call returns the 1,000 most common events; rarer ones are asked one by one.
    background = client.counts(f, REACTION_FIELD, limit=config.TOP_N_MAX) if drug_events else {}
    unsearchable = {}
    for term in drug_events:
        if term not in background:
            try:
                background[term] = client.event_total(term, f)
            except UnsearchableTerm as exc:     # skip this event only, keep the screen
                unsearchable[term] = str(exc).split(" (special")[0] + " (special character); not analysed."

    # Which generic-name strings were matched (salts, combination products).
    # The count covers every drug in those reports, so keep only names containing the drug.
    variants = {}
    if drug_total:
        word = re.compile(rf"\b{re.escape(generic_name)}\b")
        variants = {k: v for k, v in client.counts(drug, DRUG_FIELD_EXACT, limit=1000).items()
                    if word.search(str(k).upper())}

    rows, results = [], {}
    for term, a in drug_events.items():
        if term in unsearchable:
            rows.append(_row(term, None, unsearchable[term], dme.contains(term)))
            continue
        try:
            res = analyse(a, drug_total, background[term], all_total, thresholds)
            results[term] = res
            rows.append(_row(term, res, None, dme.contains(term)))
        except ValueError as exc:            # negative cell: stop this pair, show why
            rows.append(_row(term, None, str(exc), dme.contains(term)))

    table = pd.DataFrame(rows)
    if not table.empty:
        table = (table.sort_values(["Rules met", "IC025"], ascending=[False, False],
                                   na_position="last")
                      .reset_index(drop=True))

    totals = {
        "all_reports": all_total,
        "drug_reports": drug_total,
        "reactions_analysed": len(rows),
        "pairs_meeting_any_rule": int((table["Rules met"] > 0).sum()) if not table.empty else 0,
        "pairs_with_errors": int(table["Error"].notna().sum()) if not table.empty else 0,
        "combination_names_matched": sum(1 for k in variants if str(k).upper() != generic_name
                                          and re.search(r"\bAND\b|;|,", str(k).upper())),
    }

    query_parameters = {
        "drug_match_field": DRUG_FIELD,
        "generic_name": generic_name,
        "drug_role": "any (suspect, concomitant or interacting)",
        "drug_matching": DRUG_MATCHING_NOTE,
        "event_field": REACTION_FIELD,
        "filters": asdict(filters),
        "filter_clauses": filters.clauses(),
        "background_search": f,
        "top_n_reactions": top_n,
        "thresholds": asdict(thresholds),
        "rules": thresholds.as_dict(),
    }
    record = ExtractionRecord.create(client, query_parameters, dme.version)
    record.name_variants = variants
    record.rule_breakdown = rule_breakdown(rows)

    return DetectionResult(generic_name, filters, thresholds, table, totals, variants,
                           results, record)

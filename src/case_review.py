"""Case review: individual FAERS reports for one drug–event pair (spec §5, Screen 3).

Everything is shown "as reported". Missing fields are "not reported" and are never
counted as "no". openFDA codes (E2B) are translated with the tables below, which are
also listed on the Method page.

Dechallenge has no field of its own in openFDA. It is DERIVED from two reported
fields: the action taken with the drug (withdrawn or dose reduced) and the outcome of
the event (recovered or recovering = positive; not recovered = negative). Rechallenge
uses the reported field drugrecurreadministration (1 = reaction recurred = positive,
2 = did not recur = negative).

Possible duplicates are not built (cut under the spec's cut order); openFDA does not
de-duplicate reports, which is stated in the limitations.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

import requests

from src.openfda_client import (Filters, build_url, drug_clause, escaped_reaction_clause,
                                reaction_clause)

NR = "not reported"

SEX = {"0": "Unknown", "1": "Male", "2": "Female"}
QUALIFICATION = {"1": "Physician", "2": "Pharmacist", "3": "Other health professional",
                 "4": "Lawyer", "5": "Consumer or non-health professional"}
ROLE = {"1": "Suspect", "2": "Concomitant", "3": "Interacting"}
ROLE_RANK = {"Suspect": 3, "Interacting": 2, "Concomitant": 1}
OUTCOME = {"1": "Recovered/resolved", "2": "Recovering/resolving", "3": "Not recovered/not resolved",
           "4": "Recovered with sequelae", "5": "Fatal", "6": "Unknown"}
ACTION = {"1": "Drug withdrawn", "2": "Dose reduced", "3": "Dose increased", "4": "Dose not changed",
          "5": "Unknown", "6": "Not applicable"}
RECHALLENGE = {"1": "Positive (reaction recurred)", "2": "Negative (did not recur)", "3": "Unknown"}
AGE_UNIT_YEARS = {"800": 10.0, "801": 1.0, "802": 1 / 12, "803": 1 / 52.18, "804": 1 / 365.25,
                  "805": 1 / 8766}
SERIOUSNESS = [("seriousnessdeath", "Death"), ("seriousnesslifethreatening", "Life-threatening"),
               ("seriousnesshospitalization", "Hospitalisation"), ("seriousnessdisabling", "Disability"),
               ("seriousnesscongenitalanomali", "Congenital anomaly"), ("seriousnessother", "Other serious")]

# Words too general to suggest confounding on their own
GENERIC_WORDS = {"blood", "increased", "decreased", "abnormal", "disorder", "syndrome", "disease",
                 "level", "levels", "count", "positive", "negative", "acute", "chronic", "test",
                 "type", "mellitus", "nos", "condition", "aggravated", "pain", "failure"}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_reports(client, generic_name: str, event: str, filters: Filters,
                  n: int = 50) -> tuple[list[dict], int]:
    """Most recent n reports (by FDA receipt date) for the pair, and the total available."""
    base = [drug_clause(generic_name)] + filters.clauses()
    last_exc = None
    for clause in (reaction_clause(event), escaped_reaction_clause(event)):
        for sort in ("receivedate:desc", None):
            try:
                body = client.get(build_url(base + [clause], limit=n, sort=sort))
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 400:
                    raise
                last_exc = exc
                continue
            results = body.get("results", []) if body else []
            total = body.get("meta", {}).get("results", {}).get("total", len(results)) if body else 0
            results = sorted(results, key=lambda r: str(r.get("receivedate", "")), reverse=True)
            return results, total
    raise last_exc


# ---------------------------------------------------------------------------
# Parsing one report
# ---------------------------------------------------------------------------

def _word_in(word: str, text) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", str(text or ""), re.IGNORECASE))


def _is_drug_of_interest(d: dict, generic: str) -> bool:
    of = d.get("openfda", {}) or {}
    names = (of.get("generic_name") or []) + (of.get("substance_name") or [])
    names += [d.get("medicinalproduct", ""), (d.get("activesubstance") or {}).get("activesubstancename", "")]
    return any(_word_in(generic, n) for n in names)


def _drug_name(d: dict) -> str:
    of = d.get("openfda", {}) or {}
    name = (of.get("generic_name") or [None])[0] or d.get("medicinalproduct") or NR
    return str(name).upper()


def age_years(patient: dict) -> float | None:
    age, unit = patient.get("patientonsetage"), str(patient.get("patientonsetageunit", ""))
    try:
        return round(float(age) * AGE_UNIT_YEARS[unit], 1)
    except (TypeError, ValueError, KeyError):
        return None


def parse_report(raw: dict, generic: str, event: str) -> dict:
    patient = raw.get("patient", {}) or {}
    drugs = patient.get("drug", []) or []
    mine = [d for d in drugs if _is_drug_of_interest(d, generic)]
    others = [d for d in drugs if not _is_drug_of_interest(d, generic)]

    roles = [ROLE.get(str(d.get("drugcharacterization")), None) for d in mine]
    roles = [r for r in roles if r]
    role = max(roles, key=lambda r: ROLE_RANK[r]) if roles else NR

    reaction = next((r for r in patient.get("reaction", []) or []
                     if str(r.get("reactionmeddrapt", "")).upper() == event.upper()), {})
    outcome = OUTCOME.get(str(reaction.get("reactionoutcome")), NR)

    actions = [ACTION.get(str(d.get("actiondrug"))) for d in mine if d.get("actiondrug")]
    action = actions[0] if actions else NR
    rech = [RECHALLENGE.get(str(d.get("drugrecurreadministration"))) for d in mine
            if d.get("drugrecurreadministration")]
    rechallenge = rech[0] if rech else NR

    if action in ("Drug withdrawn", "Dose reduced") and outcome in ("Recovered/resolved",
                                                                      "Recovering/resolving",
                                                                      "Recovered with sequelae"):
        dechallenge = "Positive (derived)"
    elif action in ("Drug withdrawn", "Dose reduced") and outcome == "Not recovered/not resolved":
        dechallenge = "Negative (derived)"
    else:
        dechallenge = NR

    serious_flags = [label for key, label in SERIOUSNESS if str(raw.get(key)) == "1"]
    src = raw.get("primarysource", {}) or {}
    rd = str(raw.get("receivedate", ""))

    return {
        "Report ID": raw.get("safetyreportid", NR),
        "Received": f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) >= 8 else NR,
        "Age (years)": age_years(patient),
        "Sex": SEX.get(str(patient.get("patientsex")), NR),
        "Country": raw.get("occurcountry") or src.get("reportercountry") or NR,
        "Reporter": QUALIFICATION.get(str(src.get("qualification")), NR),
        "Serious": {"1": "Yes", "2": "No"}.get(str(raw.get("serious")), NR),
        "Seriousness criteria": ", ".join(serious_flags) if serious_flags else NR,
        "Event outcome": outcome,
        "Drug role": role,
        "Indication": next((str(d["drugindication"]).upper() for d in mine if d.get("drugindication")), NR),
        "Action taken": action,
        "Dechallenge": dechallenge,
        "Rechallenge": rechallenge,
        "Other suspect drugs": ", ".join(sorted({_drug_name(d) for d in others
                                                 if str(d.get("drugcharacterization")) == "1"})) or "none reported",
        "Other events": ", ".join(str(r.get("reactionmeddrapt", "")).capitalize()
                                  for r in patient.get("reaction", []) or []
                                  if str(r.get("reactionmeddrapt", "")).upper() != event.upper()) or "none",
        "_serious_flags": serious_flags,
        "_other_suspects": sorted({_drug_name(d) for d in others if str(d.get("drugcharacterization")) == "1"}),
        "_indications": sorted({str(d["drugindication"]).upper() for d in mine if d.get("drugindication")}),
    }


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

@dataclass
class CaseSummary:
    retrieved: int
    total: int
    age_median: float | None
    age_min: float | None
    age_max: float | None
    age_missing_pct: float
    counts: dict[str, dict[str, int]] = field(default_factory=dict)   # field -> value -> n
    co_suspects: list[tuple[str, int]] = field(default_factory=list)
    indications: list[tuple[str, int]] = field(default_factory=list)
    confounding: str | None = None


def _count(rows: list[dict], key: str) -> dict[str, int]:
    return dict(Counter(r[key] for r in rows).most_common())


def summarise(rows: list[dict], total: int, event: str) -> CaseSummary:
    ages = [r["Age (years)"] for r in rows if r["Age (years)"] is not None]
    n = len(rows)
    counts = {k: _count(rows, k) for k in ("Sex", "Reporter", "Country", "Serious", "Event outcome",
                                           "Drug role", "Dechallenge", "Rechallenge", "Action taken")}
    crit = Counter(flag for r in rows for flag in r["_serious_flags"])
    counts["Seriousness criteria"] = dict(crit.most_common())
    co = Counter(d for r in rows for d in r["_other_suspects"]).most_common(10)
    ind = Counter(i for r in rows for i in r["_indications"]).most_common(10)
    return CaseSummary(
        retrieved=n, total=total,
        age_median=round(statistics.median(ages), 1) if ages else None,
        age_min=min(ages) if ages else None, age_max=max(ages) if ages else None,
        age_missing_pct=round(100 * (n - len(ages)) / n, 0) if n else 0.0,
        counts=counts, co_suspects=co, indications=ind,
        confounding=confounding_hint(event, [i for i, _ in ind]),
    )


def _significant_words(term: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", term.lower()) if len(w) >= 5 and w not in GENERIC_WORDS]


def _stem(w: str) -> str:
    # British/US spelling and common endings: cholesterol ~ hypercholesterolaemia
    w = w.replace("ae", "e").replace("oe", "e")
    return w[:7] if len(w) > 7 else w


def confounding_hint(event: str, indications: list[str]) -> str | None:
    """Indication that resembles the event (shared significant word stem), if any."""
    ev = event.upper().strip()
    for ind in indications:
        if ind.upper().strip() == ev:
            return ind
    stems = {_stem(w) for w in _significant_words(event)}
    for ind in indications:
        ind_text = ind.lower().replace("ae", "e").replace("oe", "e")
        if any(s in ind_text for s in stems):
            return ind
    return None


def public_rows(rows: list[dict]) -> list[dict]:
    """Rows without the helper fields, for display and export."""
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

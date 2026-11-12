"""Detection pipeline with a fake openFDA client (no network)."""

import pytest

from src.detection import run_detection
from src.dme import DMEList
from src.openfda_client import DRUG_FIELD_EXACT, Filters, OpenFDAClient, REACTION_FIELD
from src.signals import Thresholds


class FakeClient:
    """Answers total/counts from fixed numbers, like openFDA would."""

    def __init__(self, n, drug_n, drug_events, background, rare):
        self.n, self.drug_n = n, drug_n
        self.drug_events, self.background, self.rare = drug_events, background, rare
        self.query_log = []

    def _log(self):
        self.query_log.append({"url": "fake", "from_cache": False,
                               "fetched_at_utc": "2026-11-03T00:00:00+00:00",
                               "last_updated": "2026-10-28"})

    def last_updated(self):
        self._log()
        return "2026-10-28"

    def total(self, search):
        self._log()
        reaction = [s for s in search if "reactionmeddrapt" in s]
        term = reaction[0].split('"')[1] if reaction else None
        if term and "^" in term:                      # openFDA rejects these (400)
            import requests
            resp = requests.Response(); resp.status_code = 400
            raise requests.HTTPError("400 Bad Request: Search not supported", response=resp)
        if any("generic_name" in s for s in search):
            return self.drug_events[term] if term else self.drug_n
        if term:
            return self.background.get(term, self.rare.get(term))
        return self.n

    def counts(self, search, field, limit=1000):
        self._log()
        assert search, "openFDA rejects count queries without a search (403)"
        if field == DRUG_FIELD_EXACT:
            # every generic name in the matched reports, including co-medications
            return {"ATORVASTATIN CALCIUM": 900, "AMLODIPINE BESYLATE AND ATORVASTATIN CALCIUM": 60,
                    "METFORMIN": 300, "ROSUVASTATIN": 5}
        assert field == REACTION_FIELD
        if any("generic_name" in s for s in search):
            return dict(list(self.drug_events.items())[:limit])
        return dict(self.background)

    provenance = OpenFDAClient.provenance   # reuse the real summary logic
    event_total = OpenFDAClient.event_total


DME = DMEList(frozenset({"RHABDOMYOLYSIS"}), "test list")


def make_client():
    return FakeClient(
        n=101_000, drug_n=1_000,
        drug_events={"RHABDOMYOLYSIS": 20, "NAUSEA": 10, "RARE EVENT": 3, "BROKEN": 50},
        background={"RHABDOMYOLYSIS": 220, "NAUSEA": 1_010, "BROKEN": 30},  # BROKEN: a > a+c
        rare={"RARE EVENT": 4},
    )


def test_table_built_and_sorted():
    res = run_detection(make_client(), "atorvastatin", Filters(), Thresholds(), DME)
    t = res.table
    assert res.generic_name == "ATORVASTATIN"
    assert t.iloc[0]["Rules met"] >= t.iloc[-1]["Rules met"]
    rhabdo = t[t["Reaction (PT)"] == "RHABDOMYOLYSIS"].iloc[0]
    assert rhabdo["a"] == 20 and rhabdo["d"] == 99_800
    assert rhabdo["PRR"] == pytest.approx(10.0)
    assert rhabdo["Rules met"] == 3
    assert rhabdo["DME"]


def test_rare_event_background_fetched_individually():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(), Thresholds(), DME)
    rare = res.table[res.table["Reaction (PT)"] == "RARE EVENT"].iloc[0]
    assert rare["c"] == 1 and rare["Small numbers"]


def test_negative_cell_stops_that_pair_only():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(), Thresholds(), DME)
    broken = res.table[res.table["Reaction (PT)"] == "BROKEN"].iloc[0]
    assert "negative cell" in broken["Error"]
    assert broken["Rules met"] == 0
    assert res.totals["pairs_with_errors"] == 1
    assert res.totals["reactions_analysed"] == 4


def test_extraction_record_contents():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(serious_only=True),
                        Thresholds(), DME, top_n=2)
    rec = res.record
    assert rec.openfda_last_updated == "2026-10-28"
    assert rec.dme_list_version == "test list"
    assert rec.query_parameters["top_n_reactions"] == 2
    assert rec.query_parameters["filters"]["serious_only"] is True
    assert rec.query_parameters["thresholds"]["prr_min"] == 2.0
    assert len(res.table) == 2


def test_no_reports_for_drug():
    c = make_client()
    c.drug_n, c.drug_events = 0, {}
    res = run_detection(c, "NOTADRUG", Filters(), Thresholds(), DME)
    assert res.table.empty and res.totals["drug_reports"] == 0


def test_background_uses_all_reports_clause_when_unfiltered():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(), Thresholds(), DME)
    assert res.record.query_parameters["background_search"] == ["_exists_:safetyreportid"]
    res = run_detection(make_client(), "ATORVASTATIN", Filters(serious_only=True), Thresholds(), DME)
    assert res.record.query_parameters["background_search"] == ["serious:1"]


def test_name_variants_keep_only_names_containing_the_drug():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(), Thresholds(), DME)
    assert set(res.name_variants) == {"ATORVASTATIN CALCIUM",
                                      "AMLODIPINE BESYLATE AND ATORVASTATIN CALCIUM"}
    assert res.totals["combination_names_matched"] == 1
    assert res.record.name_variants == res.name_variants
    assert "combination" in res.record.query_parameters["drug_matching"]


def test_rule_breakdown_saved_in_record():
    res = run_detection(make_client(), "ATORVASTATIN", Filters(), Thresholds(), DME)
    b = res.record.rule_breakdown
    assert b["screened"] == 3        # BROKEN stopped with an error and is left out
    assert b["met_3"] == 2           # RHABDOMYOLYSIS and RARE EVENT (a=3, c=1)
    assert b["met_0"] == 1           # NAUSEA


def test_count_verification_matches():
    from src.verification import pick_pairs, verify_counts
    client = make_client()
    res = run_detection(client, "ATORVASTATIN", Filters(), Thresholds(), DME)
    events = pick_pairs(res.table)
    assert "BROKEN" not in events and len(events) == 3
    checks = verify_counts(client, "ATORVASTATIN", Filters(), res.table, events)
    assert all(c["match"] for c in checks)


def test_count_verification_detects_mismatch():
    from src.verification import verify_counts
    client = make_client()
    res = run_detection(client, "ATORVASTATIN", Filters(), Thresholds(), DME)
    client.drug_events["RHABDOMYOLYSIS"] = 21      # a direct search now disagrees
    checks = verify_counts(client, "ATORVASTATIN", Filters(), res.table, ["RHABDOMYOLYSIS"])
    assert not checks[0]["match"]


def test_unsearchable_term_is_skipped_not_fatal():
    c = make_client()
    c.drug_events["EWING^S SARCOMA"] = 2          # rare, not in the background top list
    res = run_detection(c, "ATORVASTATIN", Filters(), Thresholds(), DME)
    row = res.table[res.table["Reaction (PT)"] == "EWING^S SARCOMA"].iloc[0]
    assert "cannot search" in row["Error"]
    assert res.totals["reactions_analysed"] == 5          # the screen still finished
    assert "RHABDOMYOLYSIS" in res.results


def test_escaped_clause():
    from src.openfda_client import escaped_reaction_clause
    assert escaped_reaction_clause("EWING^S SARCOMA").endswith('"EWING\\^S SARCOMA"')

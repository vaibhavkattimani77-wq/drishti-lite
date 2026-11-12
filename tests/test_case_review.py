"""Case review parsing and summaries, checked against a saved openFDA-style fixture."""

import json
from pathlib import Path

import requests

from src.case_review import (NR, age_years, confounding_hint, fetch_reports, parse_report,
                             public_rows, summarise)
from src.openfda_client import Filters

FIX = json.loads((Path(__file__).parent / "fixtures" / "reports_atorvastatin_rhabdo.json").read_text())
RAW = FIX["results"]
ROWS = [parse_report(r, "ATORVASTATIN", "RHABDOMYOLYSIS") for r in RAW]


def test_report_one_fields():
    r = ROWS[0]
    assert r["Report ID"] == "20001" and r["Received"] == "2026-09-01"
    assert r["Age (years)"] == 67 and r["Sex"] == "Female" and r["Country"] == "US"
    assert r["Reporter"] == "Physician" and r["Serious"] == "Yes"
    assert r["Seriousness criteria"] == "Hospitalisation"
    assert r["Drug role"] == "Suspect"                       # matched via openfda generic name
    assert r["Indication"] == "HYPERCHOLESTEROLAEMIA"
    assert r["Event outcome"] == "Recovered/resolved"
    assert r["Action taken"] == "Drug withdrawn"
    assert r["Dechallenge"] == "Positive (derived)"           # withdrawn + recovered
    assert r["Other suspect drugs"] == "CLARITHROMYCIN"       # aspirin is concomitant, not listed
    assert r["Other events"] == "Acute kidney injury"


def test_report_two_missing_fields_are_not_reported():
    r = ROWS[1]
    assert r["Sex"] == NR                                     # missing is "not reported", never "no"
    assert r["Age (years)"] == 80                             # 8 decades
    assert r["Country"] == "GB"                               # falls back to reporter country
    assert r["Reporter"] == "Consumer or non-health professional"
    assert r["Seriousness criteria"] == "Death, Hospitalisation"
    assert r["Event outcome"] == "Fatal"
    assert r["Drug role"] == "Concomitant"
    assert r["Rechallenge"] == "Positive (reaction recurred)"
    assert r["Dechallenge"] == NR
    assert r["Other suspect drugs"] == "COLCHICINE"


def test_report_three_sparse():
    r = ROWS[2]
    assert r["Age (years)"] is None and r["Event outcome"] == NR and r["Country"] == NR
    assert r["Serious"] == "No" and r["Seriousness criteria"] == NR
    assert r["Dechallenge"] == NR          # dose reduced but outcome not reported -> cannot derive


def test_age_units():
    assert age_years({"patientonsetage": "18", "patientonsetageunit": "802"}) == 1.5
    assert age_years({"patientonsetage": "x", "patientonsetageunit": "801"}) is None
    assert age_years({}) is None


def test_summary():
    s = summarise(ROWS, FIX["meta"]["results"]["total"], "RHABDOMYOLYSIS")
    assert (s.retrieved, s.total) == (3, 2278)
    assert s.age_median == 73.5 and (s.age_min, s.age_max) == (67, 80)
    assert s.age_missing_pct == 33
    assert s.counts["Drug role"] == {"Suspect": 2, "Concomitant": 1}
    assert s.counts["Seriousness criteria"] == {"Hospitalisation": 2, "Death": 1}
    assert dict(s.co_suspects) == {"CLARITHROMYCIN": 1, "COLCHICINE": 1}
    assert s.confounding is None


def test_confounding_hint():
    assert confounding_hint("BLOOD CHOLESTEROL INCREASED", ["HYPERCHOLESTEROLAEMIA"]) == "HYPERCHOLESTEROLAEMIA"
    assert confounding_hint("TYPE 2 DIABETES MELLITUS", ["TYPE 2 DIABETES MELLITUS"]) == "TYPE 2 DIABETES MELLITUS"
    assert confounding_hint("RHABDOMYOLYSIS", ["HYPERLIPIDAEMIA", "HYPERCHOLESTEROLAEMIA"]) is None
    assert confounding_hint("BLOOD PRESSURE INCREASED", ["BLOOD CHOLESTEROL INCREASED"]) is None  # only generic words shared


def test_public_rows_hide_helpers():
    assert not any(k.startswith("_") for k in public_rows(ROWS)[0])


class FakeGet:
    def __init__(self, reject_sort=False):
        self.urls, self.reject_sort = [], reject_sort

    def get(self, url):
        self.urls.append(url)
        if self.reject_sort and "sort=" in url:
            resp = requests.Response(); resp.status_code = 400
            raise requests.HTTPError("400", response=resp)
        return FIX


def test_fetch_reports_sorted_newest_first_with_total():
    c = FakeGet()
    res, total = fetch_reports(c, "atorvastatin", "RHABDOMYOLYSIS", Filters(serious_only=True), n=50)
    assert total == 2278 and [r["safetyreportid"] for r in res] == ["20001", "20002", "20003"]
    assert "sort=receivedate:desc" in c.urls[0] and "limit=50" in c.urls[0] and "serious:1" in c.urls[0]


def test_fetch_reports_without_sort_if_rejected():
    c = FakeGet(reject_sort=True)
    res, _ = fetch_reports(c, "ATORVASTATIN", "RHABDOMYOLYSIS", Filters())
    assert len(res) == 3 and "sort=" not in c.urls[-1]

"""Checks the results table built by detection.py, using a fake openFDA client
(no internet needed)."""

from src.detection import signal_table
from src.openfda_client import Filters


class FakeClient:
    """Answers like openFDA would, from fixed numbers."""
    N = 101_000
    DRUG_TOTAL = 1_000
    DRUG_REACTIONS = {"RHABDOMYOLYSIS": 20, "NAUSEA": 10, "BROKEN COUNTS": 50}
    BACKGROUND = {"RHABDOMYOLYSIS": 220, "NAUSEA": 1_010, "BROKEN COUNTS": 30}

    def total(self, search):
        return self.DRUG_TOTAL if any("generic_name" in s for s in search) else self.N

    def counts(self, search, field, limit=1000):
        if any("generic_name" in s for s in search):
            return dict(self.DRUG_REACTIONS)
        return dict(self.BACKGROUND)


def test_signal_table():
    table, totals = signal_table(FakeClient(), "ATORVASTATIN", Filters())
    assert totals == {"all_reports": 101_000, "drug_reports": 1_000}
    rows = table.set_index("Reaction (MedDRA PT)")

    assert rows.loc["RHABDOMYOLYSIS", "Rules met"] == 3
    assert rows.loc["NAUSEA", "Rules met"] == 0
    # Negative cell (c = 30 - 50 < 0): kept as a row with a visible error
    assert "negative cell" in rows.loc["BROKEN COUNTS", "Error"]
    # Most rules met comes first
    assert table.iloc[0]["Reaction (MedDRA PT)"] == "RHABDOMYOLYSIS"


# --- Extraction record --------------------------------------------------------

import json

from src.detection import run_detection, save_run
from src.signals import Thresholds


class TrackingFakeClient(FakeClient):
    def reset_tracking(self):
        self.answers_used = 0
        self.answers_from_cache = 0
        self.oldest_answer_at = self.newest_answer_at = None

    def last_updated(self):
        return "2026-10-15"


def test_extraction_record(tmp_path):
    client = TrackingFakeClient()
    table, record = run_detection(client, "ATORVASTATIN", Filters(serious_only=True),
                                  top_n=100, thresholds=Thresholds(prr_min=3.0))
    assert record["openfda_last_updated"] == "2026-10-15"
    q = record["query_parameters"]
    assert q["drug_match_field"] == "patient.drug.openfda.generic_name"
    assert q["generic_name"] == "ATORVASTATIN"
    assert q["filters"]["serious_only"] is True
    assert q["thresholds"]["prr_min"] == 3.0
    assert record["counts"] == {"drug_reports_matched": 1_000,
                                "database_reports_filtered": 101_000,
                                "reactions_analysed": 3}
    assert record["dme_list_version"].startswith("EMA DME list, EMA/326038/2020")
    assert record["label_set_id"] is None          # label check comes in Phase 2
    assert record["app_version"]

    folder = save_run(table, record, folder=str(tmp_path))
    assert json.loads((folder / "record.json").read_text())["extraction_id"] == record["extraction_id"]
    assert (folder / "results.csv").exists()

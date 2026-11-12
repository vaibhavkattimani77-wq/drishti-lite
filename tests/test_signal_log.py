"""Signal log: entries, append-only decisions with rationale, history, export (Gate 3)."""

import csv
import io
import sqlite3

import pytest

from src.signal_log import (DECISIONS, MONITORING, POTENTIAL, REFUTED, UNDER_REVIEW, SignalLog,
                            statistics_snapshot)
from src.signals import analyse

SNAP = {"statistics": statistics_snapshot(analyse(20, 1000, 220, 101000)),
        "extraction": {"extraction_id": "EXT-1", "openfda_last_updated": "2026-10-28"}}
GOOD = "Case review shows the event is the drug's own indication; confounding by indication."


@pytest.fixture
def log(tmp_path):
    return SignalLog(str(tmp_path / "log.sqlite"))


def test_new_entry_is_under_review_with_frozen_snapshot(log):
    sid, created = log.add_signal("atorvastatin", "Rhabdomyolysis", SNAP)
    assert sid == "SIG-0001" and created
    assert log.status(sid) == UNDER_REVIEW
    e = log.get(sid)
    assert e["drug"] == "ATORVASTATIN" and e["event"] == "RHABDOMYOLYSIS"
    assert e["snapshot"]["statistics"]["a"] == 20 and e["snapshot"]["statistics"]["rules_met"] == 3
    assert e["extraction_id"] == "EXT-1"


def test_same_pair_is_not_added_twice(log):
    log.add_signal("ATORVASTATIN", "MYALGIA", SNAP)
    sid, created = log.add_signal("atorvastatin", "myalgia", SNAP)
    assert sid == "SIG-0001" and not created
    sid2, _ = log.add_signal("ATORVASTATIN", "NAUSEA", SNAP)
    assert sid2 == "SIG-0002"


def test_rationale_reviewer_and_decision_are_required(log):
    sid, _ = log.add_signal("A", "E", SNAP)
    with pytest.raises(ValueError, match="at least 50"):
        log.add_decision(sid, REFUTED, "too short", "Vaibhav")
    with pytest.raises(ValueError, match="reviewer"):
        log.add_decision(sid, REFUTED, GOOD, "  ")
    with pytest.raises(ValueError, match="Decision must be"):
        log.add_decision(sid, "Confirmed signal", GOOD, "Vaibhav")
    assert log.status(sid) == UNDER_REVIEW
    assert set(DECISIONS) == {POTENTIAL, REFUTED, MONITORING}


def test_history_keeps_every_decision(log):
    sid, _ = log.add_signal("A", "E", SNAP)
    log.add_decision(sid, MONITORING, GOOD, "Vaibhav", {"score": {"total": 7}})
    log.add_decision(sid, REFUTED, GOOD + " Label also checked.", "Vishal")
    h = log.history(sid)
    assert [x["decision"] for x in h] == [MONITORING, REFUTED]
    assert h[0]["evidence"]["score"]["total"] == 7
    assert log.status(sid) == REFUTED


def test_decisions_cannot_be_overwritten_or_deleted(log):
    sid, _ = log.add_signal("A", "E", SNAP)
    log.add_decision(sid, MONITORING, GOOD, "Vaibhav")
    with pytest.raises(sqlite3.DatabaseError):
        log.db.execute("UPDATE decisions SET decision='Refuted'")
    with pytest.raises(sqlite3.DatabaseError):
        log.db.execute("DELETE FROM decisions")
    with pytest.raises(sqlite3.DatabaseError):
        log.db.execute("UPDATE signals SET event='X'")


def test_csv_export_one_row_per_decision(log):
    s1, _ = log.add_signal("A", "E1", SNAP)
    log.add_signal("A", "E2", SNAP)
    log.add_decision(s1, MONITORING, GOOD, "Vaibhav", {"label": {"status": "Labelled"}})
    log.add_decision(s1, REFUTED, GOOD, "Vaibhav")
    rows = list(csv.DictReader(io.StringIO(log.export_csv())))
    assert len(rows) == 3
    assert rows[0]["label_status"] == "Labelled" and rows[0]["prr"] == "10.0"
    assert rows[2]["decision"] == UNDER_REVIEW


def test_json_round_trip_into_empty_log(log, tmp_path):
    sid, _ = log.add_signal("A", "E", SNAP)
    log.add_decision(sid, REFUTED, GOOD, "Vaibhav")
    other = SignalLog(str(tmp_path / "other.sqlite"))
    assert other.import_json(log.export_json()) == 1
    assert other.status("SIG-0001") == REFUTED
    assert other.history("SIG-0001")[0]["rationale"] == GOOD
    with pytest.raises(ValueError, match="not empty"):
        other.import_json(log.export_json())


def test_entries_listing(log):
    sid, _ = log.add_signal("A", "E", SNAP)
    log.add_decision(sid, POTENTIAL, GOOD, "Vaibhav")
    e = log.entries()[0]
    assert e["Status"] == POTENTIAL and e["Rules met"] == 3 and e["Decisions"] == 1


def test_identical_decision_is_not_saved_twice(log):
    sid, _ = log.add_signal("A", "E", SNAP)
    log.add_decision(sid, REFUTED, GOOD, "Vaibhav")
    with pytest.raises(ValueError, match="identical"):
        log.add_decision(sid, REFUTED, GOOD, "Vaibhav")
    log.add_decision(sid, REFUTED, GOOD + " Corrected PRR.", "Vaibhav")   # a correction is fine
    assert len(log.history(sid)) == 2

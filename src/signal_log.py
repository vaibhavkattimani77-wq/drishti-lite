"""Signal log (spec §5, Screen 4): one entry per drug–event pair, decisions appended.

* An entry is created with status "Under review" and a frozen snapshot of the evidence
  at that moment: the 2×2 table, PRR/ROR/IC with intervals, rules met and the
  extraction record (data date, query, thresholds, DME list version, app version).
* Decisions are APPENDED, never edited or deleted: Potential signal (further evaluation
  warranted), Refuted or Monitoring, each with a rationale of at least 50 characters,
  the reviewer's name, the decision date and the triage / case review evidence
  available when the decision was made. The current status is the latest decision.
* CSV export of the full log (one row per decision). JSON export/import lets a
  deployment start from a committed seed file, since hosted storage is temporary.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import config

UNDER_REVIEW = "Under review"
POTENTIAL = "Potential signal (further evaluation warranted)"
REFUTED = "Refuted"
MONITORING = "Monitoring"
DECISIONS = [POTENTIAL, REFUTED, MONITORING]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SignalLog:
    def __init__(self, path: str = config.SIGNAL_LOG_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                drug TEXT NOT NULL,
                event TEXT NOT NULL,
                detection_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                extraction_id TEXT,
                snapshot TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL REFERENCES signals(signal_id),
                decision TEXT NOT NULL,
                rationale TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                evidence TEXT NOT NULL
            );
            -- nothing is overwritten: decisions cannot be changed or removed
            CREATE TRIGGER IF NOT EXISTS no_update_decisions BEFORE UPDATE ON decisions
                BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS no_delete_decisions BEFORE DELETE ON decisions
                BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS no_update_signals BEFORE UPDATE ON signals
                BEGIN SELECT RAISE(ABORT, 'signal snapshots are frozen'); END;
        """)
        self.db.commit()

    # -- entries -------------------------------------------------------------
    def find(self, drug: str, event: str) -> str | None:
        row = self.db.execute("SELECT signal_id FROM signals WHERE drug=? AND event=? "
                              "ORDER BY signal_id LIMIT 1", (drug.upper(), event.upper())).fetchone()
        return row["signal_id"] if row else None

    def add_signal(self, drug: str, event: str, snapshot: dict,
                   detection_date: str | None = None) -> tuple[str, bool]:
        """Create an entry (status Under review). Returns (signal_id, created). If the pair
        is already in the log, the existing ID is returned and nothing is changed."""
        existing = self.find(drug, event)
        if existing:
            return existing, False
        with self.db:
            n = self.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            sid = f"SIG-{n + 1:04d}"
            self.db.execute(
                "INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, drug.upper(), event.upper(), detection_date or _now()[:10], _now(),
                 snapshot.get("extraction", {}).get("extraction_id"), json.dumps(snapshot)))
        return sid, True

    def get(self, signal_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["snapshot"] = json.loads(d["snapshot"])
        return d

    # -- decisions -----------------------------------------------------------
    def add_decision(self, signal_id: str, decision: str, rationale: str, reviewer: str,
                     evidence: dict | None = None, decision_date: str | None = None) -> int:
        if decision not in DECISIONS:
            raise ValueError(f"Decision must be one of: {', '.join(DECISIONS)}")
        rationale = (rationale or "").strip()
        if len(rationale) < config.RATIONALE_MIN:
            raise ValueError(f"The rationale must be at least {config.RATIONALE_MIN} characters "
                             f"(it has {len(rationale)}).")
        if not (reviewer or "").strip():
            raise ValueError("Enter the reviewer's name.")
        if not self.get(signal_id):
            raise ValueError(f"Unknown signal {signal_id}")
        last = self.history(signal_id)[-1:] or [None]
        if last[0] and last[0]["decision"] == decision and last[0]["rationale"] == rationale:
            raise ValueError("This is identical to the latest decision, which is already saved.")
        with self.db:
            cur = self.db.execute(
                "INSERT INTO decisions (signal_id, decision, rationale, reviewer, decision_date, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (signal_id, decision, rationale, reviewer.strip(), decision_date or _now(),
                 json.dumps(evidence or {})))
        return cur.lastrowid

    def history(self, signal_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM decisions WHERE signal_id=? ORDER BY id",
                               (signal_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d["evidence"])
            out.append(d)
        return out

    def status(self, signal_id: str) -> str:
        h = self.history(signal_id)
        return h[-1]["decision"] if h else UNDER_REVIEW

    # -- listing and export --------------------------------------------------
    def entries(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT * FROM signals ORDER BY signal_id").fetchall():
            snap = json.loads(r["snapshot"])
            hist = self.history(r["signal_id"])
            last = hist[-1] if hist else None
            st = snap.get("statistics", {})
            out.append({
                "Signal ID": r["signal_id"], "Drug": r["drug"], "Event (PT)": r["event"],
                "Detected": r["detection_date"], "a": st.get("a"),
                "Rules met": st.get("rules_met"),
                "Status": last["decision"] if last else UNDER_REVIEW,
                "Decided": last["decision_date"][:10] if last else "",
                "Reviewer": last["reviewer"] if last else "",
                "Decisions": len(hist),
            })
        return out

    def export_csv(self) -> str:
        """Full log, one row per decision (entries without a decision get one row)."""
        buf = io.StringIO()
        cols = ["signal_id", "drug", "event", "detection_date", "extraction_id", "openfda_data_date",
                "a", "b", "c", "d", "prr", "prr_lower", "prr_upper", "ror", "ror_lower", "ror_upper",
                "chi2", "ic", "ic025", "rules_met", "label_status", "label_section", "label_set_id",
                "priority_score", "priority_band", "case_reports_reviewed", "decision", "rationale",
                "reviewer", "decision_date"]
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in self.db.execute("SELECT * FROM signals ORDER BY signal_id").fetchall():
            snap = json.loads(r["snapshot"])
            st, ex = snap.get("statistics", {}), snap.get("extraction", {})
            base = {"signal_id": r["signal_id"], "drug": r["drug"], "event": r["event"],
                    "detection_date": r["detection_date"], "extraction_id": r["extraction_id"],
                    "openfda_data_date": ex.get("openfda_last_updated"),
                    **{k: st.get(k) for k in ("a", "b", "c", "d", "prr", "prr_lower", "prr_upper",
                                              "ror", "ror_lower", "ror_upper", "chi2", "ic",
                                              "ic025", "rules_met")}}
            hist = self.history(r["signal_id"])
            if not hist:
                w.writerow({**base, "decision": UNDER_REVIEW})
            for h in hist:
                ev = h["evidence"]
                lab, sc, cs = ev.get("label") or {}, ev.get("score") or {}, ev.get("case_review") or {}
                w.writerow({**base, "label_status": lab.get("status"), "label_section": lab.get("section"),
                            "label_set_id": lab.get("set_id"), "priority_score": sc.get("total"),
                            "priority_band": sc.get("band"), "case_reports_reviewed": cs.get("retrieved"),
                            "decision": h["decision"], "rationale": h["rationale"],
                            "reviewer": h["reviewer"], "decision_date": h["decision_date"]})
        return buf.getvalue()

    def export_json(self) -> str:
        data = []
        for r in self.db.execute("SELECT * FROM signals ORDER BY signal_id").fetchall():
            d = dict(r)
            d["snapshot"] = json.loads(d["snapshot"])
            d["decisions"] = [{k: v for k, v in h.items() if k not in ("id", "signal_id")}
                              for h in self.history(r["signal_id"])]
            data.append(d)
        return json.dumps(data, indent=2)

    def import_json(self, text: str) -> int:
        """Load entries from export_json() into an EMPTY log (used for the deployed seed)."""
        if self.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]:
            raise ValueError("The log is not empty; import only into an empty log.")
        data = json.loads(text)
        with self.db:
            for d in data:
                self.db.execute("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (d["signal_id"], d["drug"], d["event"], d["detection_date"],
                                 d["created_at"], d.get("extraction_id"), json.dumps(d["snapshot"])))
                for h in d.get("decisions", []):
                    self.db.execute(
                        "INSERT INTO decisions (signal_id, decision, rationale, reviewer, decision_date, evidence) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (d["signal_id"], h["decision"], h["rationale"], h["reviewer"],
                         h["decision_date"], json.dumps(h.get("evidence", {}))))
        return len(data)

    def is_empty(self) -> bool:
        return self.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Building snapshots from the app's objects
# ---------------------------------------------------------------------------

def statistics_snapshot(result) -> dict:
    """From a signals.SignalResult."""
    t = result.table
    return {
        "a": t.a, "b": t.b, "c": t.c, "d": t.d, "n": t.n,
        "prr": result.prr.value, "prr_lower": result.prr.lower, "prr_upper": result.prr.upper,
        "prr_note": result.prr.note,
        "ror": result.ror.value, "ror_lower": result.ror.lower, "ror_upper": result.ror.upper,
        "ror_note": result.ror.note,
        "chi2": result.chi2, "ic": result.ic, "ic025": result.ic025,
        "rules": {"PRR": result.rules.prr, "ROR": result.rules.ror, "IC": result.rules.ic},
        "rules_met": result.rules.count, "small_numbers": result.small_numbers,
    }


def extraction_snapshot(record) -> dict:
    d = record.summary()
    keep = ("extraction_id", "extraction_datetime", "openfda_last_updated", "query_parameters",
            "dme_list_version", "app_version", "label_set_id", "label_effective_date")
    return {k: d.get(k) for k in keep}

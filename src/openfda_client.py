"""Small openFDA client with a SQLite cache.

Every answer from openFDA is saved in data/openfda_cache.sqlite, so:
  * the app is fast after the first load,
  * we stay well under openFDA's rate limits,
  * results are reproducible while the cache is fresh.

Optional: set an OPENFDA_API_KEY environment variable (free key from
https://open.fda.gov/apis/authentication/) to raise the daily limit
from 1,000 to 120,000 requests.
"""

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from src import config


# ---------------------------------------------------------------------------
# Filters -> openFDA search clauses
# ---------------------------------------------------------------------------

AGE_GROUPS = {
    "Child (0-17)": (0, 17),
    "Adult (18-64)": (18, 64),
    "Older adult (65+)": (65, 120),
}

OUTCOMES = {
    "Death": "seriousnessdeath:1",
    "Hospitalisation": "seriousnesshospitalization:1",
    "Life-threatening": "seriousnesslifethreatening:1",
    "Disability": "seriousnessdisabling:1",
}

SEXES = {"Male": "patient.patientsex:1", "Female": "patient.patientsex:2"}


@dataclass(frozen=True)
class Filters:
    """Report-level filters. Applied to BOTH the drug and the background
    database, so the 2x2 table always compares like with like."""
    serious_only: bool = False
    outcome: str | None = None
    sex: str | None = None
    age_group: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    def clauses(self) -> list[str]:
        parts = []
        if self.serious_only:
            parts.append("serious:1")
        if self.outcome:
            parts.append(OUTCOMES[self.outcome])
        if self.sex:
            parts.append(SEXES[self.sex])
        if self.age_group:
            lo, hi = AGE_GROUPS[self.age_group]
            # 801 = age reported in years
            parts.append(f"patient.patientonsetage:[{lo}+TO+{hi}]")
            parts.append("patient.patientonsetageunit:801")
        if self.year_from or self.year_to:
            start = f"{self.year_from or 2004}0101"
            end = f"{self.year_to or 2100}1231"
            parts.append(f"receivedate:[{start}+TO+{end}]")
        return parts


def drug_clause(generic_name: str) -> str:
    return f'patient.drug.openfda.generic_name:"{generic_name}"'


def reaction_clause(term: str) -> str:
    return f'patient.reaction.reactionmeddrapt.exact:"{term}"'


def _encode(clause: str) -> str:
    # Keep openFDA's own syntax characters; encode everything else (spaces, etc.)
    return quote(clause, safe=':"[]+.*_')


def build_url(search: list[str], count: str | None = None, limit: int = 1) -> str:
    params = []
    if search:
        params.append("search=" + "+AND+".join(_encode(c) for c in search))
    if count:
        params.append(f"count={count}")
    params.append(f"limit={limit}")
    return config.OPENFDA_BASE + "?" + "&".join(params)


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------

class OpenFDAClient:
    def __init__(self, cache_path: str = config.CACHE_PATH, api_key: str | None = None):
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, body TEXT, fetched_at REAL)"
        )
        self.api_key = api_key or os.environ.get("OPENFDA_API_KEY")
        self._last_call = 0.0
        self.live_calls = 0  # how many requests actually went to openFDA
        self.reset_tracking()

    # -- which answers were used (for the extraction record) -----------------
    def reset_tracking(self) -> None:
        """Start counting the answers used by one analysis."""
        self.answers_used = 0
        self.answers_from_cache = 0
        self.oldest_answer_at: float | None = None   # when the oldest answer was fetched
        self.newest_answer_at: float | None = None

    def _track(self, fetched_at: float, from_cache: bool) -> None:
        self.answers_used += 1
        self.answers_from_cache += int(from_cache)
        self.oldest_answer_at = min(self.oldest_answer_at or fetched_at, fetched_at)
        self.newest_answer_at = max(self.newest_answer_at or fetched_at, fetched_at)

    # -- cache -------------------------------------------------------------
    def _from_cache(self, url: str) -> tuple[dict, float] | None:
        row = self.db.execute("SELECT body, fetched_at FROM cache WHERE url=?", (url,)).fetchone()
        if row and time.time() - row[1] < config.CACHE_DAYS * 86400:
            return json.loads(row[0]), row[1]
        return None

    def _save(self, url: str, body: dict) -> float:
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (url, json.dumps(body), now))
        self.db.commit()
        return now

    # -- request -----------------------------------------------------------
    def get(self, url: str) -> dict:
        """Return the JSON body. A 'no matches' answer becomes {} (not an error)."""
        cached = self._from_cache(url)
        if cached is not None:
            body, fetched_at = cached
            self._track(fetched_at, from_cache=True)
            return body

        full_url = url + (f"&api_key={self.api_key}" if self.api_key else "")
        for attempt in range(4):
            wait = config.SECONDS_BETWEEN_CALLS - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            self.live_calls += 1
            resp = requests.get(full_url, timeout=30)

            if resp.status_code == 404:          # openFDA's way of saying "0 results"
                body = {}
                break
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)         # back off: 1, 2, 4, 8 seconds
                continue
            resp.raise_for_status()
            body = resp.json()
            break
        else:
            raise RuntimeError(f"openFDA did not respond after retries: {url}")

        self._track(self._save(url, body), from_cache=False)
        return body

    # -- the three kinds of question we ask ---------------------------------
    def total(self, search: list[str]) -> int:
        """Number of reports matching the search."""
        body = self.get(build_url(search, limit=1))
        return body.get("meta", {}).get("results", {}).get("total", 0)

    def counts(self, search: list[str], field: str, limit: int = 1000) -> dict[str, int]:
        """Number of reports per value of `field` (max 1000 values)."""
        body = self.get(build_url(search, count=field, limit=limit))
        # Text fields come back as {"term", "count"}; date fields as {"time", "count"}.
        return {r.get("term", r.get("time")): r["count"] for r in body.get("results", [])}

    def last_updated(self) -> str:
        body = self.get(build_url([], limit=1))
        return body.get("meta", {}).get("last_updated", "unknown")


# ---------------------------------------------------------------------------
# Extraction record (spec section 3)
# ---------------------------------------------------------------------------

DRUG_MATCH_FIELD = "patient.drug.openfda.generic_name"


def _utc(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def app_version() -> str:
    """Config version plus the git commit, if git is available."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{config.APP_VERSION} (commit {commit}{', uncommitted changes' if dirty else ''})"
    except Exception:
        return config.APP_VERSION


def extraction_record(client: "OpenFDAClient", generic_name: str, filters: Filters,
                      top_n: int, reactions_analysed: int, totals: dict,
                      thresholds: dict, dme_version: str,
                      label_set_id: str | None = None,
                      label_effective_date: str | None = None) -> dict:
    """Everything needed to trace a result back to what openFDA returned.

    Call client.reset_tracking() before the analysis and this right after it.
    """
    now = datetime.now(timezone.utc)
    return {
        "extraction_id": f"EXT-{now:%Y%m%dT%H%M%SZ}-{generic_name.replace(' ', '_')}",
        "extraction_datetime": now.isoformat(timespec="seconds"),
        "openfda_last_updated": client.last_updated(),
        "query_parameters": {
            "drug_match_field": DRUG_MATCH_FIELD,
            "generic_name": generic_name,
            "drug_roles_counted": "any (suspect, concomitant, interacting)",
            "filters": asdict(filters),
            "filter_clauses": filters.clauses(),
            "top_n_reactions": top_n,
            "thresholds": thresholds,
        },
        "counts": {
            "drug_reports_matched": totals.get("drug_reports"),
            "database_reports_filtered": totals.get("all_reports"),
            "reactions_analysed": reactions_analysed,
        },
        "api_answers": {
            "used": client.answers_used,
            "from_cache": client.answers_from_cache,
            "oldest_fetched_at": _utc(client.oldest_answer_at),
            "newest_fetched_at": _utc(client.newest_answer_at),
            "cache_days": config.CACHE_DAYS,
        },
        "label_set_id": label_set_id,
        "label_effective_date": label_effective_date,
        "dme_list_version": dme_version,
        "app_version": app_version(),
    }

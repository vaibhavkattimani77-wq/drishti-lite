"""openFDA client with a SQLite cache and an extraction record (spec §3).

Every raw answer is cached for 30 days in data/cache.sqlite, so a result can
be traced back to exactly what openFDA returned. Each client also keeps a log
of the queries it answered (URL, whether it came from the cache, when it was
fetched, and openFDA's meta.last_updated), which feeds the extraction record.

Optional: set OPENFDA_API_KEY (free key: https://open.fda.gov/apis/authentication/)
to raise the daily limit from 1,000 to 120,000 requests.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass, field
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

DRUG_FIELD = "patient.drug.openfda.generic_name"
DRUG_FIELD_EXACT = "patient.drug.openfda.generic_name.exact"
DRUG_MATCHING_NOTE = (
    "Phrase match on the harmonised generic name, drug in any role. A phrase match "
    "also matches salts (e.g. 'ATORVASTATIN CALCIUM') and combination products that "
    "contain the drug (e.g. 'AMLODIPINE BESYLATE AND ATORVASTATIN CALCIUM'); these are "
    "included and listed under name_variants. Reports without the harmonised field "
    "are not matched."
)
REACTION_FIELD = "patient.reaction.reactionmeddrapt.exact"


@dataclass(frozen=True)
class Filters:
    """Report-level filters, applied to BOTH the drug and the background,
    so the 2x2 table always compares like with like."""
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
            parts.append(f"patient.patientonsetage:[{lo}+TO+{hi}]")
            parts.append("patient.patientonsetageunit:801")   # 801 = years
        if self.year_from or self.year_to:
            start = f"{self.year_from or 2004}0101"
            end = f"{self.year_to or 2100}1231"
            parts.append(f"receivedate:[{start}+TO+{end}]")
        return parts


# openFDA refuses count queries without a search (403 Forbidden). This clause
# matches every report (each FAERS report has a safetyreportid), so it is used
# as the background search when no filters are set. N is computed with it too.
ALL_REPORTS = "_exists_:safetyreportid"


def background_clauses(filters: "Filters") -> list[str]:
    """Search clauses for the background database: the filters, or all reports."""
    return filters.clauses() or [ALL_REPORTS]


def drug_clause(generic_name: str) -> str:
    return f'{DRUG_FIELD}:"{generic_name.strip().upper()}"'


def reaction_clause(term: str) -> str:
    return f'{REACTION_FIELD}:"{term}"'


# FAERS writes apostrophes in MedDRA terms as "^" (e.g. "EWING^S SARCOMA"), which
# openFDA's search parser rejects. Escaping with a backslash is tried as a fallback.
SPECIAL_CHARS = '\\^"~*?:/'


def escaped_reaction_clause(term: str) -> str:
    esc = "".join("\\" + ch if ch in SPECIAL_CHARS else ch for ch in term)
    return f'{REACTION_FIELD}:"{esc}"'


class UnsearchableTerm(Exception):
    """openFDA cannot search for this event term (it rejected the query)."""


def date_clause(start_yyyymmdd: str, end_yyyymmdd: str) -> str:
    return f"receivedate:[{start_yyyymmdd}+TO+{end_yyyymmdd}]"


def _encode(clause: str) -> str:
    # Keep openFDA's own syntax characters; encode everything else.
    return quote(clause, safe=':"[]+.*_')


def build_url(search: list[str], count: str | None = None, limit: int = 1,
              base: str | None = None, sort: str | None = None) -> str:
    params = []
    if search:
        params.append("search=" + "+AND+".join(_encode(c) for c in search))
    if count:
        params.append(f"count={count}")
    if sort:
        params.append(f"sort={sort}")
    params.append(f"limit={limit}")
    return (base or config.OPENFDA_EVENT) + "?" + "&".join(params)


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------

class OpenFDAClient:
    def __init__(self, cache_path: str = config.CACHE_PATH, api_key: str | None = None,
                 force_refresh: bool = False):
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False, timeout=30)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, body TEXT, fetched_at REAL)"
        )
        self.api_key = api_key or os.environ.get("OPENFDA_API_KEY")
        self.force_refresh = force_refresh
        self._last_call = 0.0
        self.query_log: list[dict] = []   # one entry per answered query

    # -- cache -------------------------------------------------------------
    def _from_cache(self, url: str) -> tuple[dict, float] | None:
        if self.force_refresh:
            return None
        row = self.db.execute("SELECT body, fetched_at FROM cache WHERE url=?", (url,)).fetchone()
        if row and time.time() - row[1] < config.CACHE_DAYS * 86400:
            return json.loads(row[0]), row[1]
        return None

    def _save(self, url: str, body: dict, fetched_at: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                        (url, json.dumps(body), fetched_at))
        self.db.commit()

    def _log(self, url: str, body: dict, from_cache: bool, fetched_at: float) -> None:
        self.query_log.append({
            "url": url,
            "from_cache": from_cache,
            "fetched_at_utc": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(timespec="seconds"),
            "last_updated": body.get("meta", {}).get("last_updated"),
        })

    # -- request -----------------------------------------------------------
    def get(self, url: str) -> dict:
        """Return the JSON body. openFDA's 'no matches' (404) becomes {}."""
        cached = self._from_cache(url)
        if cached is not None:
            body, fetched_at = cached
            self._log(url, body, True, fetched_at)
            return body

        full_url = url + (f"&api_key={self.api_key}" if self.api_key else "")
        for attempt in range(4):
            wait = config.SECONDS_BETWEEN_CALLS - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            resp = requests.get(full_url, timeout=30)
            if resp.status_code == 404:
                body = {}
                break
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)        # back off: 1, 2, 4, 8 s
                continue
            if not resp.ok:
                # Show openFDA's own explanation, not just the status code.
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = resp.text[:200]
                raise requests.HTTPError(
                    f"openFDA returned {resp.status_code} {resp.reason}"
                    + (f" ({detail})" if detail else "") + f" for {url}", response=resp)
            body = resp.json()
            break
        else:
            raise RuntimeError(f"openFDA did not respond after 4 attempts: {url}")

        now = time.time()
        self._save(url, body, now)
        self._log(url, body, False, now)
        return body

    # -- the kinds of question we ask ----------------------------------------
    def total(self, search: list[str]) -> int:
        """Number of reports matching the search."""
        body = self.get(build_url(search, limit=1))
        return body.get("meta", {}).get("results", {}).get("total", 0)

    def counts(self, search: list[str], field: str, limit: int = 1000) -> dict[str, int]:
        """Number of reports per value of `field` (openFDA returns at most 1,000 values)."""
        body = self.get(build_url(search, count=field, limit=min(limit, config.TOP_N_MAX)))
        # Text fields come back as {"term", "count"}; date fields as {"time", "count"}.
        return {r.get("term", r.get("time")): r["count"] for r in body.get("results", [])}

    def event_total(self, term: str, other: list[str]) -> int:
        """Reports with this event (plus the other clauses). Tries the term as is, then
        escaped; raises UnsearchableTerm if openFDA rejects both (400 Bad Request)."""
        last = None
        for clause in (reaction_clause(term), escaped_reaction_clause(term)):
            try:
                return self.total([clause] + other)
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 400:
                    raise
                last = exc
        raise UnsearchableTerm(f"openFDA cannot search for the term '{term}' "
                               f"(special character); not analysed. {last}")

    def last_updated(self) -> str:
        body = self.get(build_url([], limit=1))
        return body.get("meta", {}).get("last_updated", "unknown")

    # -- provenance ----------------------------------------------------------
    def provenance(self) -> dict:
        """Summary of the answers used so far (for the extraction record)."""
        log = self.query_log
        versions = sorted({q["last_updated"] for q in log if q["last_updated"]})
        fetched = sorted(q["fetched_at_utc"] for q in log)
        return {
            "queries": len(log),
            "from_cache": sum(q["from_cache"] for q in log),
            "live": sum(not q["from_cache"] for q in log),
            "oldest_answer_fetched_utc": fetched[0] if fetched else None,
            "newest_answer_fetched_utc": fetched[-1] if fetched else None,
            "openfda_last_updated_values": versions,
            "mixed_data_versions": len(versions) > 1,
        }


# ---------------------------------------------------------------------------
# Extraction record (spec §3)
# ---------------------------------------------------------------------------

def app_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=3, check=True).stdout.strip()
        return f"{config.APP_VERSION} (git {sha})" if sha else config.APP_VERSION
    except Exception:
        return config.APP_VERSION


@dataclass
class ExtractionRecord:
    extraction_id: str
    extraction_datetime: str
    openfda_last_updated: str
    query_parameters: dict
    dme_list_version: str
    app_version: str
    label_set_id: str | None = None          # filled in Phase 2 (label check)
    label_effective_date: str | None = None
    data_provenance: dict = field(default_factory=dict)
    name_variants: dict = field(default_factory=dict)    # generic-name strings matched -> reports
    rule_breakdown: dict = field(default_factory=dict)
    count_checks: list[dict] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, client: OpenFDAClient, query_parameters: dict, dme_list_version: str
               ) -> "ExtractionRecord":
        now = datetime.now(timezone.utc)
        prov = client.provenance()
        versions = prov["openfda_last_updated_values"]
        if len(versions) == 1:
            last_updated = versions[0]
        elif versions:
            last_updated = "MIXED: " + ", ".join(versions)
        else:
            last_updated = "unknown"
        return cls(
            extraction_id="EXT-" + now.strftime("%Y%m%d-%H%M%S"),
            extraction_datetime=now.isoformat(timespec="seconds"),
            openfda_last_updated=last_updated,
            query_parameters=query_parameters,
            dme_list_version=dme_list_version,
            app_version=app_version(),
            data_provenance=prov,
            queries=list(client.query_log),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> dict:
        """The record without the long per-query list (for display)."""
        d = self.to_dict()
        d.pop("queries")
        return d

    def save(self, folder: str = config.EXTRACTIONS_DIR) -> Path:
        Path(folder).mkdir(parents=True, exist_ok=True)
        path = Path(folder) / f"{self.extraction_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

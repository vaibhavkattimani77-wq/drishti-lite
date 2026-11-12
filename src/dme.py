"""EMA Designated Medical Event (DME) list: loading and matching.

The list is a safety net: events on it deserve attention irrespective of the
statistics. Serious is not the same as DME; many serious events are not on it.
Matching is case-insensitive exact match on the MedDRA Preferred Term.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src import config


@dataclass(frozen=True)
class DMEList:
    terms: frozenset[str]          # upper-case PTs
    version: str

    def contains(self, pt: str) -> bool:
        return pt.strip().upper() in self.terms

    def __len__(self) -> int:
        return len(self.terms)


def _version_line(path: str) -> str:
    """Short version label, e.g. 'EMA DME list, EMA/326038/2020 (15 June 2020), 62 PTs'."""
    text = Path(path).read_text(encoding="utf-8")
    doc = next((ln.split(":", 1)[1].strip() for ln in text.splitlines()
                if ln.lower().startswith("document:")), "version not recorded")
    return f"EMA DME list, {doc}"


def load_dme(csv_path: str = config.DME_CSV, version_path: str = config.DME_VERSION_TXT) -> DMEList:
    df = pd.read_csv(csv_path)
    terms = frozenset(df["pt"].astype(str).str.strip().str.upper())
    return DMEList(terms, f"{_version_line(version_path)}, {len(terms)} PTs")

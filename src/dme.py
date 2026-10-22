"""EMA Designated Medical Event (DME) list: loading, matching and version.

Matching is case-insensitive exact match on the MedDRA PT (FAERS returns PTs in
upper case; the EMA file uses normal case). See data/ema_dme_list_VERSION.txt.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

from src import config


@lru_cache(maxsize=1)
def dme_terms(path: str = config.DME_LIST_PATH) -> frozenset[str]:
    """The DME PTs, upper-cased for matching."""
    return frozenset(pd.read_csv(path)["pt"].str.strip().str.upper())


def is_dme(pt: str) -> bool:
    return pt.strip().upper() in dme_terms()


def dme_list_version(path: str = config.DME_VERSION_PATH) -> str:
    """e.g. 'EMA DME list, EMA/326038/2020, dated 15 June 2020'."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("Document:"):
            return "EMA DME list, " + line.split(":", 1)[1].split(" (")[0].strip()
    return "EMA DME list, version not recorded"

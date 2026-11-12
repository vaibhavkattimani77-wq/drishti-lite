"""Label check against the most recent FDA product label (spec §5, Screen 2).

Sections are searched in this order:
    Boxed Warning -> Warnings and Precautions / Warnings -> Precautions -> Adverse Reactions

Status
    Labelled                        exact PT phrase found (case-insensitive, whole words)
    Possibly labelled               all significant words of the PT in one sentence:
                                    the reviewer must confirm
    Not found in searched label text  neither of the above
    Label unavailable               no label returned: check manually

FAERS PTs use MedDRA (British) spelling, US labels use American spelling, so a US
variant of the term is also tried (e.g. DIARRHOEA -> diarrhea, OEDEMA -> edema)
and reported when it was the one that matched. FAERS writes apostrophes as "^".

Text matching on one US label version: it may miss synonyms or match unrelated text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import requests

from src import config
from src.openfda_client import build_url

LABELLED = "Labelled"
POSSIBLY = "Possibly labelled"
NOT_FOUND = "Not found in searched label text"
UNAVAILABLE = "Label unavailable"

# (display name, openFDA label field), in search order
SECTIONS = [
    ("Boxed Warning", "boxed_warning"),
    ("Warnings and Precautions", "warnings_and_cautions"),
    ("Warnings", "warnings"),
    ("Precautions", "precautions"),
    ("Adverse Reactions", "adverse_reactions"),
]

STOPWORDS = {"of", "the", "and", "in", "to", "a", "an", "with", "on", "for", "by", "at", "or",
             "nos", "site", "type"}

LABEL_NOTE = ("Text matching on one US label version; it may miss synonyms or match unrelated text.")


@dataclass
class LabelResult:
    status: str
    section: str | None = None
    passage: str | None = None
    matched_term: str | None = None        # the phrase that matched (may be a US spelling)
    spelling_note: str | None = None
    set_id: str | None = None
    label_id: str | None = None
    effective_date: str | None = None      # YYYY-MM-DD
    product: str | None = None
    label_note: str | None = None          # e.g. label choice caveats
    sections_searched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Choosing the label
# ---------------------------------------------------------------------------

def _is_combination(label: dict) -> bool:
    names = label.get("openfda", {}).get("generic_name", []) or []
    return any(re.search(r"\bAND\b|;|,|/", str(n).upper()) for n in names)


def choose_label(results: list[dict]) -> tuple[dict | None, str | None]:
    """Most recent label, preferring single-ingredient products over combinations."""
    if not results:
        return None, None
    ordered = sorted(results, key=lambda r: str(r.get("effective_time", "")), reverse=True)
    for lab in ordered:
        if not _is_combination(lab):
            return lab, None
    return ordered[0], "Only combination-product labels were found; this one was used."


def fetch_label(client, generic_name: str) -> tuple[dict | None, str | None]:
    """Fetch recent labels for the drug and choose one. Returns (label, note)."""
    search = [f'openfda.generic_name:"{generic_name.strip().upper()}"']
    try:
        body = client.get(build_url(search, limit=config.LABEL_CANDIDATES,
                                    base=config.OPENFDA_LABEL, sort="effective_time:desc"))
    except requests.HTTPError as exc:          # sort not accepted: fetch more, sort here
        if exc.response is None or exc.response.status_code != 400:
            raise
        body = client.get(build_url(search, limit=100, base=config.OPENFDA_LABEL))
    return choose_label(body.get("results", []) if body else [])


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def us_spelling(text: str) -> str:
    """British -> American spelling for common MedDRA patterns (oedema -> edema)."""
    t = text.lower()
    t = re.sub(r"(?<=[a-z])ae(?=[a-z])", "e", t)      # anaemia -> anemia, haem -> hem
    t = re.sub(r"\bae", "e", t)
    t = re.sub(r"(?<=[a-z])oe(?=[a-z])", "e", t)      # diarrhoea -> diarrhea
    t = re.sub(r"\boe", "e", t)                        # oedema -> edema
    return t


def term_variants(pt: str) -> list[str]:
    base = pt.replace("^", "'").lower().strip()
    out = [base]
    us = us_spelling(base)
    if us != base:
        out.append(us)
    return out


def _sections_text(label: dict) -> list[tuple[str, str]]:
    found = []
    for name, key in SECTIONS:
        parts = label.get(key)
        if parts:
            found.append((name, " ".join(str(p) for p in parts)))
    return found


def _sentences(text: str) -> list[str]:
    # Split on full stops and semicolons only: colons introduce lists ("were: myalgia, ...")
    # and headings ("Myopathy and Rhabdomyolysis: Atorvastatin may cause ..."), which belong
    # with the text after them.
    return [s.strip() for s in re.split(r"(?<=[.;])\s+|\n+", text) if s.strip()]


def _best_sentence(text: str, pattern: re.Pattern) -> str | None:
    """First matching sentence that reads like a sentence (8+ words), else the first match."""
    hits = [s for s in _sentences(text) if pattern.search(s)]
    if not hits:
        return None
    full = [s for s in hits if len(s.split()) >= 8]
    return (full or hits)[0]


def _phrase_regex(phrase: str) -> re.Pattern:
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(r"\b" + r"[\s\-]+".join(words) + r"\b", re.IGNORECASE)


def _trim(sentence: str, limit: int = 600) -> str:
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + " …"


def check_label(label: dict | None, pt: str, label_note: str | None = None) -> LabelResult:
    if not label:
        return LabelResult(UNAVAILABLE, label_note="No label returned by openFDA: check manually.")

    meta = {
        "set_id": label.get("set_id"),
        "label_id": label.get("id"),
        "effective_date": _date(label.get("effective_time")),
        "product": _product(label),
        "label_note": label_note,
    }
    sections = _sections_text(label)
    searched = [name for name, _ in sections]
    variants = term_variants(pt)

    # 1. Labelled: exact phrase, in section order
    for name, text in sections:
        for v in variants:
            m = _phrase_regex(v).search(text)
            if m:
                sent = _best_sentence(text, _phrase_regex(v)) or m.group(0)
                return LabelResult(LABELLED, name, _trim(sent), m.group(0),
                                   _spelling(v, variants), sections_searched=searched, **meta)

    # 2. Possibly labelled: all significant words in one sentence
    for name, text in sections:
        for v in variants:
            words = [w for w in re.findall(r"[a-z0-9']+", v) if w not in STOPWORDS and len(w) > 1]
            if len(words) < 2:
                continue        # a one-word PT was already tried as an exact phrase
            pats = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]
            for sent in _sentences(text):
                if all(p.search(sent) for p in pats):
                    return LabelResult(POSSIBLY, name, _trim(sent), " + ".join(words),
                                       _spelling(v, variants), sections_searched=searched, **meta)

    return LabelResult(NOT_FOUND, sections_searched=searched, **meta)


def _product(label: dict) -> str | None:
    of = label.get("openfda", {})
    names = []
    for n in (of.get("brand_name") or [])[:2] + (of.get("generic_name") or [])[:1]:
        if n and n.upper() not in (x.upper() for x in names):
            names.append(n)
    return ", ".join(names) or None


def _spelling(v: str, variants: list[str]) -> str | None:
    if v != variants[0]:
        return f"Matched the US spelling '{v}' (FAERS uses MedDRA British spelling)."
    return None


def _date(yyyymmdd) -> str | None:
    s = str(yyyymmdd or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None

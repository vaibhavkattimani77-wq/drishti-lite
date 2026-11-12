"""Label check (spec §5 Screen 2; Gate 2: correct on test pairs, with passages)."""

import requests

from src.label_check import (LABELLED, NOT_FOUND, POSSIBLY, UNAVAILABLE, check_label,
                             choose_label, fetch_label, term_variants, us_spelling)

LABEL = {
    "id": "abc-123", "set_id": "set-999", "effective_time": "20250314",
    "openfda": {"brand_name": ["LIPITOR"], "generic_name": ["ATORVASTATIN CALCIUM"]},
    "warnings_and_cautions": [
        "5.1 Myopathy and Rhabdomyolysis Atorvastatin may cause myopathy and rhabdomyolysis. "
        "Acute kidney injury secondary to myoglobinuria and fatalities have occurred. "
        "5.3 Increases in HbA1c and fasting serum glucose levels have been reported."
    ],
    "adverse_reactions": [
        "The most common adverse reactions were nasopharyngitis, arthralgia, diarrhea, "
        "pain in extremity and urinary tract infection. Peripheral edema was reported."
    ],
}


def test_labelled_exact_phrase_with_section_and_passage():
    r = check_label(LABEL, "RHABDOMYOLYSIS")
    assert r.status == LABELLED
    assert r.section == "Warnings and Precautions"          # searched before Adverse Reactions
    assert "may cause myopathy and rhabdomyolysis" in r.passage
    assert r.set_id == "set-999" and r.effective_date == "2025-03-14"


def test_multiword_exact_phrase():
    r = check_label(LABEL, "PAIN IN EXTREMITY")
    assert r.status == LABELLED and r.section == "Adverse Reactions"


def test_british_spelling_matched_as_us():
    r = check_label(LABEL, "DIARRHOEA")
    assert r.status == LABELLED and r.matched_term.lower() == "diarrhea"
    assert "US spelling" in r.spelling_note
    assert check_label(LABEL, "OEDEMA PERIPHERAL").status == POSSIBLY   # words in one sentence


def test_possibly_labelled_needs_all_words_in_one_sentence():
    r = check_label(LABEL, "ACUTE KIDNEY INJURY")
    assert r.status == LABELLED                                    # exact phrase present
    r = check_label(LABEL, "KIDNEY FAILURE ACUTE")
    assert r.status == NOT_FOUND                                   # 'failure' absent
    r = check_label(LABEL, "GLUCOSE INCREASED")
    assert r.status == NOT_FOUND                                   # 'increased' absent (only 'increases')


def test_not_found_and_whole_words_only():
    assert check_label(LABEL, "TREMOR").status == NOT_FOUND
    assert check_label(LABEL, "MYOPATH").status == NOT_FOUND       # no partial-word match


def test_label_unavailable():
    r = check_label(None, "RHABDOMYOLYSIS")
    assert r.status == UNAVAILABLE and "check manually" in r.label_note


def test_faers_apostrophe():
    assert term_variants("EWING^S SARCOMA")[0] == "ewing's sarcoma"


def test_us_spelling_rules():
    assert us_spelling("anaemia") == "anemia"
    assert us_spelling("oedema peripheral") == "edema peripheral"
    assert us_spelling("haemorrhage") == "hemorrhage"
    assert us_spelling("oesophagitis") == "esophagitis"


def test_choose_label_prefers_recent_single_ingredient():
    combo = {"effective_time": "20260101", "openfda": {"generic_name": ["AMLODIPINE BESYLATE AND ATORVASTATIN CALCIUM"]}}
    single_old = {"effective_time": "20240101", "openfda": {"generic_name": ["ATORVASTATIN CALCIUM"]}}
    single_new = {"effective_time": "20250101", "openfda": {"generic_name": ["ATORVASTATIN CALCIUM"]}}
    lab, note = choose_label([single_old, combo, single_new])
    assert lab is single_new and note is None
    lab, note = choose_label([combo])
    assert lab is combo and "combination" in note
    assert choose_label([]) == (None, None)


class FakeLabelClient:
    def __init__(self, reject_sort=False):
        self.reject_sort, self.urls = reject_sort, []

    def get(self, url):
        self.urls.append(url)
        if self.reject_sort and "sort=" in url:
            resp = requests.Response(); resp.status_code = 400
            raise requests.HTTPError("400", response=resp)
        return {"results": [LABEL]}


def test_fetch_label_uses_label_endpoint_and_sort():
    c = FakeLabelClient()
    lab, _ = fetch_label(c, "atorvastatin")
    assert lab is LABEL
    assert "drug/label.json" in c.urls[0] and "sort=effective_time:desc" in c.urls[0]
    assert 'openfda.generic_name:"ATORVASTATIN"' in c.urls[0]


def test_fetch_label_falls_back_when_sort_rejected():
    c = FakeLabelClient(reject_sort=True)
    lab, _ = fetch_label(c, "ATORVASTATIN")
    assert lab is LABEL and "sort=" not in c.urls[-1]


REAL_LIKE = {
    "id": "x", "set_id": "4e06b20d", "effective_time": "20261106",
    "openfda": {"brand_name": ["ATORVASTATIN CALCIUM"], "generic_name": ["ATORVASTATIN CALCIUM"]},
    "warnings_and_cautions": ["5 WARNINGS AND PRECAUTIONS 5.1 Myopathy and Rhabdomyolysis: "
                              "Atorvastatin calcium may cause myopathy and rhabdomyolysis. "
                              "Acute kidney injury has occurred."],
    "adverse_reactions": ["The most common adverse reactions leading to discontinuation were: "
                          "myalgia (0.7%), diarrhea (0.5%), nausea (0.4%)."],
}


def test_passage_is_a_real_sentence_not_a_heading():
    r = check_label(REAL_LIKE, "RHABDOMYOLYSIS")
    assert "may cause myopathy and rhabdomyolysis" in r.passage


def test_passage_keeps_text_before_a_colon():
    r = check_label(REAL_LIKE, "MYALGIA")
    assert r.passage.startswith("The most common adverse reactions leading to discontinuation")


def test_product_name_not_repeated():
    assert check_label(REAL_LIKE, "MYALGIA").product == "ATORVASTATIN CALCIUM"

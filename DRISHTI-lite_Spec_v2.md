# DRISHTI-lite: Specification v2

*A pharmacovigilance research prototype for FAERS signal detection, triage and case review.*
Replaces DRISHTI_Spec_v1.md and DRISHTI_Blueprint.md (full version, now out of scope).
Status: **v2.1** (3 Nov 2026). Changes from v2 after external review: PRR zero-cell rule, trend labels,
rule non-independence note, drug-name variants, count check. See the change log at the end.

---

## 1. Purpose and positioning

**What it is:** a Python research prototype that screens public FDA FAERS data (via openFDA) for
disproportionate drug–event reporting, helps prioritise and review the flagged pairs, and documents
each decision with a written rationale.

**What it is not:** a validated or regulatory-compliant signal management system. Its outputs are
hypothesis-generating and do not establish causality.

**Portfolio position**
| Project | Main competency |
|---|---|
| AVANI | Individual case (ICSR) processing and clinical safety review |
| **DRISHTI-lite** | Aggregate safety data analysis, signal detection, triage and case review |
| CDM package (next) | Clinical data validation, query management, traceability |

### 1.1 Wording rules (use everywhere: app, README, CV, interviews)
| Never say | Say instead |
|---|---|
| validated system / validated score | research prototype / exploratory score |
| GVP IX–compliant / aligned | informed by GVP Module IX signal-management principles |
| new / novel signal | not found in searched label text |
| same patient / duplicate | possible duplicate (matching fields listed) |
| confirmed signal / causes | disproportionate reporting; potential signal |
| methods agree, so it's real | 3 of 3 predefined rules met |
| no rechallenge | rechallenge not reported |

---

## 2. Stack

Python 3.12 · Streamlit · Pandas · Plotly · Requests · SQLite · pytest.
No login, no AI and no document export: AVANI already demonstrates those.
Builds on the existing FAERS dashboard code (`signals.py`, `openfda_client.py`, `pipeline.py`, tests).
Deployment: Streamlit Community Cloud (free).

---

## 3. Data and reproducibility

**Sources**
- openFDA `drug/event` (FAERS reports): aggregate counts and individual report records
- openFDA `drug/label` (FDA product labels, SPL)
- EMA Designated Medical Event (DME) list: the public list, stored as `data/ema_dme_list.csv`
  with its **version/date recorded** in `data/ema_dme_list_VERSION.txt` (download the current
  version from the EMA website; do not invent terms)

**Recorded with every analysis (the "extraction record")**
| Field | Example |
|---|---|
| extraction_datetime | when the queries ran |
| openfda_last_updated | from `meta.last_updated` |
| query_parameters | drug match field, generic name, filters, top-N, thresholds |
| label_set_id, label_effective_date | which label version was searched |
| dme_list_version | e.g. "EMA DME list, <date>" |
| app_version | git commit or version number |

The cache keeps the raw API answers for 30 days, so a result can be traced to exactly what openFDA returned.

**Drug matching:** `patient.drug.openfda.generic_name`. Many reports lack this harmonised field, so
counts are **underestimates**. The app shows how many reports matched. A drug counts in **any role**
(suspect, concomitant or interacting) in the statistics; roles are shown in the case review.

---

## 4. Statistics (exact definitions)

### 4.1 The 2×2 table
|  | Event | All other events | Total |
|---|---|---|---|
| **Drug** | a | b | a+b |
| **All other drugs** | c | d | c+d |
| **Total** | a+c | b+d | N |

- Counts are **numbers of reports**, from openFDA count queries with the same filters applied to drug and background.
- a = reports with drug and event · a+b = drug reports · a+c = event reports · N = all reports.
- b = (a+b) − a · c = (a+c) − a · d = N − (a+b) − (a+c) + a
- A negative cell (inconsistent API counts) stops the calculation for that pair with a visible error.
- **The full 2×2 table is shown for every pair** (expandable row / detail panel).

### 4.2 Methods
| Measure | Formula | Interval |
|---|---|---|
| PRR | [a/(a+b)] / [c/(c+d)] | 95% CI: exp(ln PRR ± 1.96·SE), SE = √(1/a − 1/(a+b) + 1/c − 1/(c+d)) |
| ROR | (a·d) / (b·c) | 95% CI: exp(ln ROR ± 1.96·SE), SE = √(1/a + 1/b + 1/c + 1/d) |
| χ² | Yates-corrected, 1 df: N(\|ad − bc\| − N/2)² / [(a+b)(c+d)(a+c)(b+d)] | — |
| IC | log₂[(a + 0.5) / (E + 0.5)], E = (a+b)(a+c)/N | IC025 ≈ IC − 3.3(a+0.5)^−½ − 2(a+0.5)^−³⁄₂ |

IC reference: Norén GN, Hopstadius J, Bate A. *Shrinkage observed-to-expected ratios for robust and
transparent large-scale pattern discovery.* Stat Methods Med Res 2013;22(1):57–69.
(A shrinkage observed-to-expected ratio; the +0.5 terms shrink small counts towards no association.)

### 4.3 Zero cells and small numbers
| Situation | Handling |
|---|---|
| a = 0 | PRR/ROR "not computable (a = 0)"; IC still computed (shrinkage) |
| c = 0 | PRR "not computable (c = 0)" |
| b, c or d = 0 | ROR "not computable (<cell> = 0)"; PRR is still computed when only b or d is 0; **no continuity correction** (stated on the Method page) |
| a < 5 | **Small-numbers warning** shown on the row and in the detail panel |
| Missing case fields | Shown as "not reported", never counted as "no" |

### 4.4 Predefined signal rules
| Rule | Criteria | Source |
|---|---|---|
| PRR rule | PRR ≥ 2 **and** a ≥ 3 **and** χ² ≥ 4 | Evans et al. 2001 |
| ROR rule | lower 95% CI of ROR > 1 **and** a ≥ 3 | common practice in published FAERS studies |
| IC rule | IC025 > 0 | WHO-UMC practice |

- Display: **"Rules met: 2 of 3"** with a tick or cross per rule. Never a combined "probability".
- Note on screen: *Rules met reflects predefined statistical criteria, not evidence of causality. PRR/ROR (frequentist) and IC (Bayesian) are different measures and are not interchangeable.*
- Thresholds are adjustable in the sidebar; the values used are saved in the extraction record.

### 4.5 Trend
- Reports per calendar quarter by FDA receipt date; the **current incomplete quarter is excluded**.
- "Increasing reporting": last 4 complete quarters ≥ 1.5 × previous 4, **and** ≥ 3 reports in the last 4.
- "Decreasing reporting": ratio ≤ 0.67. Otherwise "No substantial change". Fewer than 6 reports across the 8 quarters → "Insufficient data".
- The labels describe reporting volume, not risk.
- Note: changes in reporting often reflect stimulated reporting, not changes in risk.

### 4.6 Multiple testing
About 100 reactions are screened per drug, so some pairs will meet rules by chance. This is stated in
the limitations and on the Detection screen.

---

## 5. Screens

### Screen 1: Detection
- Drug picker (5 presets + free text), filters (serious only, outcome, sex, age group, years), thresholds, reactions analysed (default 100).
- Tiles: drug reports matched, database reports (filtered), reactions analysed, pairs meeting ≥ 1 rule.
- Results table: PT, a, PRR (CI), ROR (CI), IC (IC025), χ², rules met (✓/✗ ×3), small-number flag.
- Row detail: full 2×2 table + plain-language explanation, e.g. *"The event makes up 1.6% of reports for this drug and 0.04% for all other drugs."*
- Forest plot (PRR or ROR with CI, log scale), top-reactions chart, quarterly trend.
- Button: **Send to triage** (creates a signal log entry with status "Under review").

### Screen 2: Triage
- **Label check:** searches the most recent label (by `effective_time`) in this order: Boxed Warning, Warnings and Precautions / Warnings, Precautions, Adverse Reactions.
  | Status | Rule |
  |---|---|
  | Labelled | Exact PT phrase found (case-insensitive, word boundaries) |
  | Possibly labelled | All significant words of the PT appear in one sentence: **reviewer must confirm** |
  | Not found in searched label text | Neither of the above |
  | Label unavailable | No label returned: **check manually** |
  Always shown with the section, the **exact passage** and the label set ID and date. Note: *text matching on one US label; may miss synonyms or match unrelated text.*
- **EMA DME list match:** yes / no, with the list version. Note: *serious ≠ DME; many serious events are not on the list.*
- **Exploratory prioritisation score (not validated):**
  | Factor | Points | Rationale (shown in app) |
  |---|---|---|
  | Not found in searched label text | +2 | Possibly unexpected, but needs confirmation |
  | Possibly labelled | +1 | Uncertain label coverage |
  | On EMA DME list | +2 | Event class of known regulatory concern |
  | ≥ 1 report with fatal outcome | +2 | Report-level death; not necessarily caused by the event |
  | > 50% of reports serious | +1 | Seriousness pattern |
  | Rules met 3/3 (+2) or 2/3 (+1) | 0–2 | Consistency across predefined rules |
  | Increasing reporting | +1 | Possible emerging pattern |
  Maximum 10 · **Higher ≥ 7 · Medium 4–6 · Lower ≤ 3.** Each factor is shown with its points and evidence. The weights are a documented design choice, not a validated model.

### Screen 3: Case review
- Pulls individual report records for the pair: **default 50, configurable up to 100**, most recent first. Shows "n retrieved of N total".
- Summaries: age (median, range, % missing), sex, country, reporter qualification, seriousness criteria, event outcome.
- **Drug roles:** for the drug of interest, % suspect / concomitant / interacting.
- **Co-reported suspect drugs** (top 10) and **indications for the drug** (top 10).
- **Dechallenge/rechallenge, as reported:** positive / negative / not reported (counts and %).
- **Possible duplicates:** groups of reports matching on age (±1), sex, country, suspect drugs, event and receipt within 90 days, or sharing a reporter duplicate number. Shows the matching fields. Wording: "possible duplicate; cannot be confirmed from public data".
- **Possible confounding by indication:** shown when the event matches one of the drug's top indications.
- **Report browser:** table of the retrieved reports with all available fields; missing = "not reported".
- Field reference: a table on the Method page listing every openFDA field used and its codes.

### Screen 4: Signal log
- Decision form: **Potential signal (further evaluation warranted) / Refuted / Monitoring**, plus a **rationale (required, ≥ 50 characters)**, plus the reviewer's name.
- Log fields:

| Field | Purpose |
|---|---|
| signal_id (SIG-0001) | Unique ID |
| drug, event (PT) | The pair |
| detection_date | When first flagged |
| extraction record (§3) | Data date, query, label and DME versions |
| statistics snapshot | Full 2×2 table, PRR/ROR/IC with intervals, rules met |
| label status + passage | Label evidence |
| priority score + breakdown | Triage evidence |
| case review summary | Key counts from screen 3 |
| decision | Potential signal / Refuted / Monitoring |
| rationale | Why |
| reviewer | Who |
| decision_date | When decided (separate from extraction date) |
| history | Every earlier decision with dates (nothing overwritten) |

- Log table with filters; **CSV export** of the full log.

### Method & limitations page
- All formulas, thresholds, zero-cell rules, IC reference, trend rule, score weights and rationale, field reference.
- Limitations (§8), written in your own words.

---

## 6. Build phases and gates

### Phase 1: Scientific MVP (Week 1)
Data retrieval with extraction record · 2×2 · PRR/ROR/χ²/IC with intervals · rules · zero-cell and small-number handling · results table with 2×2 detail · forest plot · trend.
**Gate 1 (all must pass)**
- [ ] `tests/` cover normal counts, a = 0, b/c/d = 0, a = 1–4 (small numbers), PRR = 1 (no disproportion)
- [ ] `validation/reference_check.xlsx`: 3 real pairs recomputed independently in Excel from the 2×2 counts; all values match the app to 2 decimals
- [ ] Atorvastatin – Rhabdomyolysis shows disproportionate reporting
- [ ] Extraction record saved and visible

### Phase 2: Clinical assessment (Week 2, days 1–4)
Case review · label check · DME match · exploratory score.
**Gate 2**
- [ ] For one pair, take two reports and check their fields by hand against the raw openFDA JSON
- [ ] Label check correct on 4 test pairs (at least one each of Labelled and Not found), with passages
- [ ] Score breakdown adds up by hand
- [ ] **You can take one pair and explain, from the evidence on screen, why it warrants further review or why it is unconvincing**

### Phase 3: Portfolio (Week 2, days 5–7 + buffer)
Signal log · CSV export · Method & limitations page · README · screenshots · deploy · demo video.
**Gate 3**
- [ ] Two documented examples in the log: **one potential signal** and **one refuted**, each with a full rationale
- [ ] A friend can clone the repo, run it from the README and reproduce an example without asking you
- [ ] Live link works
- [ ] Every claim in the README is something the app actually does

### Timeline
| Dates | Work |
|---|---|
| Fri 23 – Thu 29 Oct | Phase 1 |
| Fri 30 Oct – Mon 2 Nov | Phase 2 |
| Tue 3 – Thu 5 Nov | Phase 3 |
| Fri 6 – Sun 8 Nov | Buffer |
| From Mon 9 Nov | CDM package (code part) with the rest of the Pro month |

**If behind, cut in this order:** trend scoring → possible-confounding hint → possible-duplicate screen → deployment (run locally for demo).
**Never cut:** tests, reference check, 2×2 transparency, limitations, rationale.

---

## 7. Folder structure

```
drishti-lite/
├── app.py                         Streamlit entry (4 screens + Method page)
├── src/
│   ├── config.py                  thresholds, weights, limits (all tunables)
│   ├── openfda_client.py          queries, filters, cache, extraction record
│   ├── signals.py                 2x2, PRR, ROR, chi2, IC, rules
│   ├── detection.py               builds the results table (was pipeline.py)
│   ├── trend.py
│   ├── label_check.py
│   ├── dme.py                     loads EMA DME list + version
│   ├── priority.py                exploratory score
│   ├── case_review.py             report retrieval, summaries, roles, de/rechallenge
│   ├── duplicates.py              possible-duplicate grouping
│   └── signal_log.py              SQLite log with history + CSV export
├── data/
│   ├── ema_dme_list.csv
│   ├── ema_dme_list_VERSION.txt
│   └── cache.sqlite               (not committed)
├── validation/
│   └── reference_check.xlsx       independent recalculation of 3 pairs
├── tests/
│   ├── test_signals.py  test_trend.py  test_label_check.py
│   ├── test_priority.py  test_duplicates.py
│   └── fixtures/                  saved openFDA JSON for offline tests
├── docs/                          screenshots, demo video link
├── README.md  ·  PROJECT_NOTES.md  ·  requirements.txt  ·  .gitignore
```

---

## 8. Limitations (shown in the app and README)

1. Spontaneous reports: no exposure denominator, no incidence, cannot establish causality.
2. Reporting biases: under-reporting, stimulated (notoriety) reporting, Weber effect, changes over time.
3. Confounding by indication and by co-medication; drug counted in any role in the statistics.
4. Masking by strongly associated drug–event pairs in the background.
5. Duplicates: openFDA does not de-duplicate; the app flags only possible duplicates.
6. Drug matching relies on the harmonised generic name, which many reports lack, so counts are underestimated.
7. Analysis at MedDRA PT level only; no grouping (HLT, SMQ), so related terms are split.
8. Multiple testing: screening many pairs produces chance findings.
9. Label check is text matching on one US label version; it may miss synonyms or match unrelated text.
10. Prioritisation score is exploratory, with documented but unvalidated weights.
11. Missing case data are common and shown as "not reported".
12. Research prototype for education and portfolio use; not a validated or regulatory-compliant system.

---

## 9. CV and interview

**CV bullet (fill in only what is built and tested):**
> Developed **DRISHTI-lite**, a Python-based pharmacovigilance research prototype for FAERS data
> analysis, incorporating PRR, ROR and Bayesian information component (IC) disproportionality
> analysis, case-level review, FDA label comparison and documented signal prioritisation;
> statistics verified against independent recalculation and [X] automated tests.

**The question to be ready for:**
> "Your tool found a strong signal between Drug X and Reaction Y. How do you know the drug caused it?"

**Answer pattern:** "It doesn't show causation. It shows disproportionate reporting. I'd look at the
counts and intervals, data quality and missing data, the reporting trend and possible stimulated
reporting, the label, and the individual cases: timing, de/rechallenge, co-medications, the
underlying disease and possible duplicates. Then I'd document a conclusion with a rationale. The
statistic is one piece of the assessment."

Other questions to practise: the 2×2 table; PRR vs ROR vs IC; why IC shrinks small counts; why
"not in label" ≠ new; what masking is; why your score is exploratory; your refuted example.

---

## 10. Your role while building

Claude writes most of the code. You:
- Choose the demo pairs and make the clinical decisions (potential signal / refuted) with reasons.
- Build the Excel reference check yourself.
- Check report fields against the raw JSON.
- Write the rationales and limitations in your own words.
- Test every gate in the browser.

---

## Change log

**v2.1 (3 Nov 2026)**, after an external review:
- §4.3: PRR needs only a > 0 and c > 0; it is computed when b or d is 0. ROR still needs all four cells.
- §4.4: on-screen note that the three rules share one 2×2 table and are not independent confirmations.
  A per-screen breakdown shows how many pairs meet each rule and 0–3 rules.
- §4.5: trend labels renamed to describe reporting volume (Increasing / Decreasing reporting, No substantial change).
- §3: the generic-name strings matched (salts, combination products) are listed per screen and saved
  in the extraction record. Combination products are included.
- §3: count check: a and a+c for three events are re-fetched by direct search and must match (saved in the record).
- Out of scope, listed as future work: comparator sensitivity analyses (same class, suspect-only),
  brand-name mapping, exact Bayesian IC025.

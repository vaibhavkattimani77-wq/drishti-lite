# DRISHTI-lite

**FAERS screening, triage and case review**

DRISHTI-lite is a pharmacovigilance research prototype written in Python. It screens public US FDA
adverse event reports (FAERS, through the openFDA API) for drug–event pairs that are reported more
often than expected, and supports the steps a reviewer takes next: triage, individual case review and
a documented decision with a written rationale. The workflow is informed by selected principles of EMA
GVP Module IX (signal management).

> **Research prototype for education and portfolio use.** Results show disproportionate reporting,
> not incidence, risk or causation. Not a validated or regulatory-compliant system; not for clinical
> or regulatory decisions.

*Drishti* means *sight* in Sanskrit: the aim is to help a reviewer see patterns in safety reports
without mistaking them for proof.

**Live app:** _https://drishti-lite.streamlit.app/_

---

## What it does

| Screen | What it shows |
|---|---|
| **Detection** | For a drug's most frequently reported events (MedDRA Preferred Terms): the full 2×2 table, PRR and ROR with 95% confidence intervals, Yates χ², and the information component (IC with IC025). Each pair is checked against three predefined rules and shown as "Rules met: n of 3". Also: small-number warnings, a quarterly reporting trend, a forest plot, an EMA Designated Medical Event (DME) safety-net panel, the drug names matched, and a count check that confirms the counts are report counts. |
| **Triage** | A label check against the most recent FDA label (exact passage, section, label set ID and date) and an exploratory priority score (0–10) with every point explained. |
| **Case review** | Up to 100 individual reports for a pair: age, sex, reporter type, country, seriousness, event outcome, drug role (suspect or concomitant), dechallenge and rechallenge, other suspect drugs and indications, a possible-confounding-by-indication warning, and the raw openFDA record for checking fields by hand. |
| **Signal log** | Decisions (Potential signal / Refuted / Monitoring) with a required rationale of at least 50 characters and the reviewer's name. Evidence is frozen when an entry is added; decisions are append-only (enforced by the database), with full history and CSV export. |
| **Method and limitations** | Formulas, thresholds, zero-cell rules, label-check and score rules, the openFDA fields and codes used, and the limitations. |

## Methods in brief

| Measure | Formula | Rule (defaults, adjustable) |
|---|---|---|
| PRR | [a/(a+b)] / [c/(c+d)], 95% CI on the log scale | PRR ≥ 2, a ≥ 3, χ² ≥ 4 (Evans et al. 2001) |
| ROR | (a·d) / (b·c), 95% CI on the log scale | lower 95% CI > 1, a ≥ 3 |
| IC | log₂[(a+0.5)/(E+0.5)], E = (a+b)(a+c)/N; IC025 approximation | IC025 > 0 (Norén, Hopstadius & Bate 2013) |

- No continuity correction: PRR needs a, c > 0; ROR needs all four cells > 0; IC is always computed.
- The three rules come from the same 2×2 table, so "3 of 3" is consistency, not three independent
  confirmations.
- Trend: 8 most recent complete quarters; labels describe reporting volume, not risk.
- The priority score uses documented but **unvalidated** weights; it orders pairs for review only.

Full details are on the app's **Method and limitations** page.

## How it was checked

- **97 automated tests** (`pytest`): hand-worked statistics, zero cells, small numbers, PRR = 1,
  inconsistent counts, trend rules, label matching, score arithmetic, case-report parsing, and the
  append-only signal log.
- **Independent recalculation** (`validation/reference_check.xlsx`): three real pairs recomputed in
  Excel from the raw counts (a strong pair, a pair meeting no rules, and a small-numbers pair), all
  matching the app to two decimals; one pair also checked by calculator.
- **Report fields checked by hand** against the raw openFDA JSON.
- **Traceability:** every analysis saves an extraction record with the openFDA data date, query
  settings, thresholds, DME list version, label version and every query URL.

## Documented examples (signal log)

| Entry | Pair | Decision | Main reasons |
|---|---|---|---|
| SIG-0001 | Atorvastatin – Type 2 diabetes mellitus | Refuted | Glycaemic risk already labelled (text match missed the synonym); atorvastatin a suspect in only 24% of reports (co-medication and co-morbidity); signs of stimulated reporting. |
| SIG-0002 | Semaglutide – Optic ischaemic neuropathy (NAION) | Potential signal | 3 of 3 rules, increasing reporting, on the EMA DME list, suspect in 100% of reports, not in the US label version searched. The EMA concluded in 2025 that NAION is a very rare side effect of semaglutide, and in November 2026 the FDA required a class-wide GLP-1 label update. |
| SIG-0003 | Atorvastatin – Blood cholesterol increased | Refuted | The condition being treated: confounding by indication (the reported indication is the event itself). |

The full log, with frozen evidence and rationales, ships with the app (`data/signal_log_seed.json`).

## Run it locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
python -m streamlit run app.py
```

openFDA requires a free API key for the count queries used here. Get one at
<https://open.fda.gov/apis/authentication/> and set it as the environment variable `OPENFDA_API_KEY`
(on Windows: `setx OPENFDA_API_KEY "your-key"`, then reopen the terminal).

## Data sources

- US FDA Adverse Event Reporting System (FAERS) via the openFDA drug adverse event API.
- FDA product labels via the openFDA drug label API.
- EMA Designated Medical Event list, EMA/326038/2020 (62 Preferred Terms).

## Limitations

1. Spontaneous reports have no exposure denominator, give no incidence and cannot establish causality.
2. Reporting biases: under-reporting, stimulated (notoriety) reporting, the Weber effect, and changes over time.
3. Confounding by indication and by co-medication; the drug is counted in any role (suspect, concomitant or interacting).
4. Masking by strongly associated drug–event pairs in the background.
5. openFDA does not de-duplicate reports, and this version does not flag possible duplicates.
6. Drug matching uses the harmonised generic name, which many reports lack, so counts are underestimates; combination products containing the drug are included.
7. Analysis at MedDRA Preferred Term level only, so related terms are split.
8. Screening many pairs produces chance findings; only the drug's most frequently reported events are screened.
9. The label check is text matching on one US label version: it can miss synonyms, match unrelated text, and lag behind regulatory decisions.
10. The priority score is exploratory, with documented but unvalidated weights.
11. Missing case data are common and shown as "not reported".
12. Research prototype for education and portfolio use; not a validated or regulatory-compliant system.

## Project structure

```
app.py                  Streamlit app (Detection, Triage, Case review, Signal log, Method, About)
src/                    config, openFDA client, statistics, detection, trend, label check,
                        priority score, case review, signal log, DME list, count check
data/                   EMA DME list and version, signal log seed
tests/                  pytest suite and fixtures
validation/             independent Excel recalculation
```

## Built with

Python, Streamlit, pandas, Plotly, Requests, SQLite and pytest. The code was written with AI
assistance (Claude); the workflow design, choice of methods and examples, validation and review
decisions were made by the developers.

## Developed by

**Vaibhav Kattimani** and **Vishal Patil**

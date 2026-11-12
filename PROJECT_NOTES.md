# PROJECT_NOTES: DRISHTI-lite

Update this file at the end of every phase and re-upload it to the Claude Project.

## Locked documents
- DRISHTI-lite_Spec_v2.md, now v2.1 (source of truth; change log at the end)
- data/ema_dme_list.csv + ema_dme_list_VERSION.txt (EMA/326038/2020, 62 PTs)

## Current phase
**Phase 2: Clinical assessment.** 5-day plan (12–16 Nov 2026), then the CDM package:
- Day 1: label check + priority score (BUILT) · Day 2: case review (BUILT) · Day 3: signal log (BUILT)
- Day 4: my two documented examples + limitations/About in my own words · Day 5: README, deploy, screenshots
- Cut (spec cut order): possible-duplicate screen, demo video

## Status
### Phase 1: Scientific MVP
- [x] Project built to spec §7 folder layout (pipeline.py → detection.py)
- [x] Extraction record saved with every analysis (data/extractions/EXT-*.json)
- [x] IC + IC025; ROR rule; rules-met display
- [x] Zero-cell "not computable" handling + small-numbers warning (a < 5)
- [x] 2×2 detail panel with plain-language explanation
- [x] Trend (complete quarters only) + increasing/decreasing reporting rule
- [x] DME safety-net panel
- [x] First live run against openFDA (atorvastatin: 252,398 drug reports, 93 of 100 pairs meet ≥ 1 rule)
- [x] New design, credits (Vaibhav Kattimani and Vishal Patil), tagline, blue rules-met scale, About page, footer
- [x] Review fixes: PRR zero-cell rule, rule breakdown panel, non-independence note, drug names matched, count check, trend labels
- [x] Atorvastatin – RHABDOMYOLYSIS shows disproportionate reporting (3 of 3, PRR 4.76)
- [x] validation/reference_check.xlsx (3 real pairs, values entered by me; Pair 1 PRR checked by calculator)
- [ ] pytest passes on my laptop (96 tests)
- [ ] Count check run on atorvastatin and saved
- [ ] Rewrite the About page in my own words
- [x] GATE 1 passed (reference check), once the two items above are ticked

### Phase 2: Clinical assessment
- [x] Label check with passage, section, label set ID and date (Triage screen; US-spelling variant; "Open in Triage" button)
- [x] DME match
- [x] Exploratory priority score with breakdown (Triage screen)
- [x] Case review (50 default, up to 100), roles, de/rechallenge (dechallenge derived), co-reported suspects, indications, confounding hint, report browser, raw JSON viewer (built Day 2)
- [x] Gate 2: label check on 4 test pairs (2 Labelled, 2 Not found), noted below
- [x] Gate 2: one score breakdown added up by hand (Rhabdomyolysis 7, Myalgia 5)
- [ ] Gate 2: two reports checked by hand against the raw openFDA JSON
- [ ] Gate 2: explain one pair from the evidence on screen
- [ ] GATE 2 passed

### Phase 3: Portfolio
- [x] Signal log (SQLite, append-only decisions enforced by the database, evidence frozen at entry and attached to each decision, CSV + JSON export, seed file for deployment) + "Add to signal log" buttons on Detection, Triage and Case review
- [x] Method & limitations page (draft exists)
- [ ] Limitations rewritten in my own words
- [x] README (written from what the app does), DEPLOY.md, version 1.0.0
- [ ] Push to GitHub, deploy on Streamlit Cloud, add live link to README
- [ ] Screenshots, LinkedIn post
- [x] One potential-signal and two refuted examples documented (SIG-0001 T2DM refuted, SIG-0002 semaglutide–NAION potential signal, SIG-0003 blood cholesterol increased refuted); seed saved as data/signal_log_seed.json
- [ ] GATE 3 passed

## Decisions made
- Stack: Python 3.12, Streamlit, Pandas, Plotly, Requests, SQLite, pytest. No login, no AI, no DOCX export.
- Signal rules: PRR (Evans), ROR (lower CI > 1, a ≥ 3), IC (IC025 > 0, Norén 2013).
- Zero cells (spec v2.1): PRR needs a, c > 0 (still computed when b or d = 0); ROR needs all four cells > 0; no continuity correction; IC always computed.
- Yates χ² uses max(|ad − bc| − N/2, 0), so a pair with no association gives χ² = 0 (MAX() in Excel too).
- Trend: 8 most recent complete quarters, judged against openFDA meta.last_updated; empty quarters count as 0;
  labels describe reporting volume (Increasing / Decreasing reporting, No substantial change).
- Results sorted by rules met, then IC025.
- Cache can mix openFDA data releases: the app warns and offers "Ignore cache"; use a clean run for any validation.
- openFDA requires an API key for these count queries (OPENFDA_API_KEY).
- Combination products containing the drug are included; the names matched are shown and recorded.
- Terms openFDA cannot search for (e.g. EWING^S SARCOMA) are skipped with a reason; the screen still completes.
- Label: most recent single-ingredient label by effective_time (combination labels only if nothing else);
  US spelling of the PT also tried (MedDRA uses British spelling); label set ID and date saved in the extraction record.
- Priority score: "Label unavailable" gets 0 points with "check manually"; seriousness and fatal counts use the screen's filters.
- Demo drugs: atorvastatin, ciprofloxacin, montelukast, semaglutide, isotretinoin.

## Open questions / bugs
- Explain the 93/100 result using the rule breakdown panel (write it up for the README).
- Blood cholesterol increased: likely confounding by indication; do not call it refuted until case review and label check.

## Label check test pairs (Gate 2)
Label: ATORVASTATIN CALCIUM, effective 2026-11-06, set ID 4e06b20d-cc5d-46eb-991b-5972248de3af
- [x] Atorvastatin – Rhabdomyolysis: Labelled, Warnings and Precautions ("Myopathy and Rhabdomyolysis"). Score 7 (Higher) = 0+2+2+1+2+0, added up by hand.
- [x] Atorvastatin – Myalgia: Labelled, Adverse Reactions ("myalgia (0.7%), diarrhea (0.5%) ..."). Score 5 (Medium) = 0+0+2+1+2+0.
- [x] Atorvastatin – Type 2 diabetes mellitus: Not found in searched label text. Score 7. Synonym miss: the label warns of increases in HbA1c and fasting serum glucose (Warnings and Precautions), so effectively labelled. 99% serious, decreasing reporting: check reporter type (litigation-driven reporting?) in case review.
- [x] Atorvastatin – Blood cholesterol increased: Not found in searched label text. Score 7. The condition being treated, not an adverse reaction: likely confounding by indication / lack of effect. Candidate REFUTED example.
- Lesson: the score ranks both as Higher, like rhabdomyolysis; only the reviewer can tell a synonym miss from an indication. That is why the score is exploratory.

## Case review findings (11 Nov 2026, 50 most recent reports each)
- Blood cholesterol increased (3,221 reports): confounding warning shown; the reported indication is "Blood cholesterol increased" itself. Atorvastatin suspect in 22%. Supports REFUTED (confounding by indication / lack of effect).
- Type 2 diabetes mellitus (11,286 reports): atorvastatin suspect in only 24% (concomitant in most), 96% serious, lawyers among reporters, decreasing reporting. Disproportionality likely driven by co-medication / co-morbidity (statins are common in diabetic patients) and possibly litigation-stimulated reporting; the label already warns of raised HbA1c/glucose.

## Hand-check notes
- 11 Nov 2026: 3 pairs recomputed in Excel from raw counts (validation/reference_check.xlsx), all match the app to 2 dp:
  Atorvastatin–Rhabdomyolysis (EXT-20261111-101843), Atorvastatin–Death (EXT-20261111-101843; χ² 631.70 but PRR 0.76, so correctly no rule met),
  Atorvastatin child 0-17–Photosensitivity reaction, a=3 (EXT-20261111-112336; 3 of 3 rules but PRR CI 6.29–59.64 and no reports in the last 8 quarters).
  PRR for pair 1 checked by calculator.

# PROJECT_NOTES: DRISHTI-lite

Update this file at the end of every phase and re-upload it to the Claude Project.

## Locked documents
- DRISHTI-lite_Spec_v2.md (source of truth)
- data/ema_dme_list.csv + ema_dme_list_VERSION.txt (EMA/326038/2020, 62 PTs)

## Current phase
**Phase 1: Scientific MVP** (planned 23–29 Oct 2026)

## Status
### Phase 1: Scientific MVP
- [ ] Project restructured to spec §7 folder layout (reuse signals.py, openfda_client.py, pipeline.py → detection.py)
- [ ] Extraction record saved with every analysis
- [ ] IC + IC025 added; ROR rule; rules-met display
- [ ] Zero-cell "not computable" handling + small-numbers warning (a < 5)
- [ ] 2×2 detail panel with plain-language explanation
- [ ] Trend (complete quarters only) + rising/falling rule
- [ ] DME safety-net panel
- [ ] Tests: normal, a=0, b/c/d=0, a=1–4, PRR=1
- [ ] validation/reference_check.xlsx (3 real pairs, built by me)
- [ ] GATE 1 passed

### Phase 2: Clinical assessment
- [ ] Case review (50 default, up to 100), roles, de/rechallenge, possible duplicates, confounding hint
- [ ] Label check with passage and label version
- [ ] DME match + exploratory priority score with breakdown
- [ ] GATE 2 passed

### Phase 3: Portfolio
- [ ] Signal log (SQLite, history, CSV export)
- [ ] Method & limitations page
- [ ] Optional: EU context line (EMA worksharing list Rev. 15)
- [ ] README, screenshots, deploy, demo video
- [ ] One potential-signal and one refuted example documented
- [ ] GATE 3 passed

## Decisions made
- Stack: Python 3.12, Streamlit, Pandas, Plotly, Requests, SQLite, pytest. No login, no AI, no DOCX export.
- Signal rules: PRR (Evans), ROR (lower CI > 1, a ≥ 3), IC (IC025 > 0, Norén 2013).
- Zero cells: PRR/ROR not computable, no continuity correction.
- Demo drugs: atorvastatin, ciprofloxacin, montelukast, semaglutide, isotretinoin.

## Open questions / bugs
- (none yet)

## Hand-check notes
- (record your manual PRR/ROR/IC calculation for one pair here)

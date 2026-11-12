"""DRISHTI-lite: FAERS disproportionality screening, triage and case review.

Research prototype. Outputs are hypothesis-generating and do not establish causality.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from src import config
from src.detection import DetectionResult, run_detection
from src.dme import load_dme
from src.openfda_client import AGE_GROUPS, OUTCOMES, SEXES, Filters, OpenFDAClient
from src.signals import Thresholds, explain
from src.trend import parse_data_date, quarterly_trend
from src.verification import verify_counts
from src.label_check import (LABEL_NOTE, LABELLED, NOT_FOUND, POSSIBLY, UNAVAILABLE,
                             check_label, fetch_label)
from src.priority import SCORE_NOTE, fetch_seriousness, score
from src.case_review import NR, fetch_reports, parse_report, public_rows, summarise
from src.signal_log import (DECISIONS, MONITORING, POTENTIAL, REFUTED, UNDER_REVIEW, SignalLog,
                            extraction_snapshot, statistics_snapshot)

LOGO = "assets/logo.svg"
HAS_LOGO = Path(LOGO).exists()
TAGLINE = "FAERS screening, triage and case review"
st.set_page_config(page_title=f"DRISHTI-lite: {TAGLINE}", page_icon=LOGO if HAS_LOGO else None, layout="wide")
if HAS_LOGO:
    st.logo(LOGO, size="large")

# Rules-met scale: one calm blue, light for 0 rules, darkest for 3 (same everywhere).
# Deliberately not red/amber: meeting rules means disproportionate reporting, not danger.
SCALE = {0: "#D3DCE5", 1: "#9DBAD6", 2: "#5A86B3", 3: "#1F4E79"}       # fills (plots)
SCALE_TEXT = {0: "#8A96A3", 1: "#5F87AE", 2: "#2F6496", 3: "#173B5E"}  # text, readable on white
INK, MUTED, BLUE = "#18273A", "#52606D", "#1F4E79"
FONT = "Public Sans, Segoe UI, Arial, sans-serif"

CAUSALITY_NOTE = ("Rules met reflects predefined statistical criteria, not evidence of causality. "
                  "All three rules are calculated from the same 2×2 table, so they are not "
                  "independent confirmations: 3 of 3 is not three separate pieces of evidence. "
                  "PRR/ROR (frequentist) and IC (Bayesian) are different measures and are not "
                  "interchangeable.")
DISPROPORTIONALITY_NOTE = ("These results show disproportionate reporting, not incidence, relative "
                           "risk or proof that the drug caused the event.")

st.html("""<style>
.block-container {padding-top: 2.2rem; max-width: 1380px;}
.dl-drug {font-size: 2.1rem; font-weight: 700; color: #18273A; margin: 0; line-height: 1.15;}
.dl-meta {color: #52606D; font-size: 0.9rem; margin: 0.25rem 0 1rem 0;}
.dl-tagline {color: #52606D; font-size: 1.2rem; margin: 0.2rem 0 1.4rem 0;}
.dl-dots {font-size: 1.35rem; letter-spacing: 0.12em; line-height: 1;}
.dl-two {border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums;}
.dl-two th, .dl-two td {border: 1px solid #D3DAE2; padding: 0.45rem 0.7rem; text-align: right;}
.dl-two th {background: #E9EEF3; font-weight: 600; color: #18273A;}
.dl-two th:first-child, .dl-two td:first-child {text-align: left;}
.dl-two td.cell {background: #FFFFFF; font-weight: 600;}
.dl-two .lbl {color: #52606D; font-weight: 400; font-size: 0.8rem; margin-right: 0.35rem;}
</style>""")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def dots(n: int) -> str:
    return "●" * n + "○" * (3 - n)


def dots_html(n: int) -> str:
    return f'<span class="dl-dots" style="color:{SCALE_TEXT[n]}">{dots(n)}</span>'


def fmt_ci(value, low, high, note) -> str:
    if isinstance(note, str) and note:
        return note
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.2f} ({low:.2f}–{high:.2f})"


def compact(n: int) -> str:
    """21,054,159 -> '21.05 M' so tiles don't cut the number off (exact value in the tooltip)."""
    return f"{n / 1e6:.2f} M" if n >= 1_000_000 else f"{n:,}"


def fmt_num(x, digits=2) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.{digits}f}"


def display_table(t: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "Rules met": [f"{dots(n)}  {n} of 3" for n in t["Rules met"]],
        "Event (MedDRA PT)": t["Reaction (PT)"].str.capitalize(),
        "a": t["a"].astype("Int64"),
        "PRR (95% CI)": [fmt_ci(*r) for r in t[["PRR", "PRR low", "PRR high", "PRR note"]].itertuples(index=False)],
        "ROR (95% CI)": [fmt_ci(*r) for r in t[["ROR", "ROR low", "ROR high", "ROR note"]].itertuples(index=False)],
        "IC (IC025)": [f"{fmt_num(i)} ({fmt_num(l)})" for i, l in zip(t["IC"], t["IC025"])],
        "χ²": [fmt_num(x, 1) for x in t["Chi-square"]],
        "PRR rule": t["PRR rule"].map({True: "✓", False: "✗"}),
        "ROR rule": t["ROR rule"].map({True: "✓", False: "✗"}),
        "IC rule": t["IC rule"].map({True: "✓", False: "✗"}),
        "Flags": [", ".join(f for f, on in (("a < 5", s), ("EMA DME", d)) if on)
                  for s, d in zip(t["Small numbers"], t["DME"])],
    })
    if t["Error"].notna().any():
        out["Error"] = t["Error"].fillna("")
    return out


def styled(df: pd.DataFrame, rules: pd.Series):
    """Colour the rules-met column on the signal scale."""
    colours = [SCALE_TEXT[n] for n in rules]

    def colour_rules(col):
        return [f"color: {c}; font-weight: 600" for c in colours]

    def colour_ticks(col):
        return [f"color: {BLUE}; font-weight: 700" if v == "✓" else "color: #9AA5B1" for v in col]

    return (df.style
            .apply(colour_rules, subset=["Rules met"])
            .apply(colour_ticks, subset=["PRR rule", "ROR rule", "IC rule"]))


def style_fig(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=40),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
                      font=dict(family=FONT, color=INK, size=13), showlegend=False)
    fig.update_xaxes(gridcolor="#E4E9EE", zeroline=False)
    fig.update_yaxes(gridcolor="#E4E9EE", zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# Sidebar (Detection settings)
# ---------------------------------------------------------------------------

def detection_sidebar() -> dict:
    sb = st.sidebar
    choice = sb.selectbox("Drug", list(config.DRUGS) + ["Other (type a generic name)"])
    if choice.startswith("Other"):
        generic = sb.text_input("Generic name, as in openFDA", placeholder="e.g. METFORMIN")
    else:
        generic = config.DRUGS[choice]
    clicked = sb.button("Run analysis", type="primary", width="stretch")

    with sb.expander("Filters"):
        st.caption("Applied to the drug and to the background database alike.")
        serious = st.checkbox("Serious reports only")
        outcome = st.selectbox("Seriousness outcome", ["Any"] + list(OUTCOMES))
        sex = st.selectbox("Sex", ["Any"] + list(SEXES))
        age = st.selectbox("Age group", ["Any"] + list(AGE_GROUPS))
        years = ["Any"] + list(range(2004, date.today().year + 1))
        c1, c2 = st.columns(2)
        y_from = c1.selectbox("From", years)
        y_to = c2.selectbox("To", years)

    with sb.expander("Screening and rule thresholds"):
        top_n = st.number_input("Events analysed", 10, config.TOP_N_MAX,
                                config.TOP_N_REACTIONS, step=10)
        prr_min = st.number_input("PRR at least", 1.0, 10.0, config.PRR_MIN, 0.5)
        cases_min = st.number_input("Reports (a) at least", 1, 20, config.CASES_MIN)
        chi2_min = st.number_input("χ² at least", 0.0, 20.0, config.CHI2_MIN, 0.5)
        ror_low = st.number_input("ROR lower 95% CI above", 0.5, 5.0, config.ROR_LOWER_MIN, 0.1)
        ic025_min = st.number_input("IC025 above", -2.0, 3.0, config.IC025_MIN, 0.1)
        st.caption("The values used are saved in the extraction record.")

    with sb.expander("Data"):
        refresh = st.checkbox("Ignore cache and fetch fresh data",
                              help="Use if the extraction record reports mixed openFDA data versions.")

    filters = Filters(
        serious_only=serious,
        outcome=None if outcome == "Any" else outcome,
        sex=None if sex == "Any" else sex,
        age_group=None if age == "Any" else age,
        year_from=None if y_from == "Any" else int(y_from),
        year_to=None if y_to == "Any" else int(y_to),
    )
    th = Thresholds(prr_min, int(cases_min), chi2_min, ror_low, ic025_min)
    return {"generic": (generic or "").strip().upper(), "filters": filters, "thresholds": th,
            "top_n": int(top_n), "refresh": refresh, "clicked": clicked}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@st.cache_resource
def dme_list():
    return load_dme()


def run(settings: dict) -> None:
    f = settings["filters"]
    if not settings["generic"]:
        st.warning("Type a generic name in the sidebar first.")
        return
    if f.year_from and f.year_to and f.year_from > f.year_to:
        st.warning("The 'From' year is after the 'To' year. Fix the year filter and run again.")
        return
    client = OpenFDAClient(force_refresh=settings["refresh"])
    try:
        with st.spinner(f"Querying openFDA for {settings['generic'].capitalize()}. "
                        "The first run takes a minute or two; later runs use the cache."):
            res = run_detection(client, settings["generic"], f, settings["thresholds"],
                                dme_list(), settings["top_n"])
    except requests.RequestException as exc:
        st.error(f"The analysis stopped: {exc}")
        return
    except RuntimeError as exc:
        st.error(str(exc))
        return
    st.session_state["record_path"] = str(res.record.save())
    st.session_state["result"] = res
    st.session_state["trends"] = {}
    st.session_state.pop("selected_pt", None)


def empty_state() -> None:
    st.html(f'<p class="dl-drug">DRISHTI-lite</p><p class="dl-tagline">{TAGLINE}</p>')
    st.subheader("Detection")
    st.markdown(
        "Screens FDA adverse event reports (FAERS, via openFDA) for drug–event pairs that are "
        "reported more often than expected. Choose a drug in the sidebar, then select "
        "**Run analysis**.")
    st.markdown("Each pair is checked against three predefined rules:")
    st.markdown(
        "| Rule | Met when | Source |\n|---|---|---|\n"
        "| PRR | PRR ≥ 2, at least 3 reports, χ² ≥ 4 | Evans et al. 2001 |\n"
        "| ROR | Lower 95% CI of ROR above 1, at least 3 reports | Published FAERS practice |\n"
        "| IC | IC025 above 0 | WHO-UMC practice |")
    st.markdown("Results appear with this scale: " + " &nbsp; ".join(
        f"{dots_html(n)} {n}" for n in range(4)), unsafe_allow_html=True)
    st.caption("Research prototype. Results generate hypotheses and do not establish causality.")


def two_by_two_html(t, drug: str, event: str) -> str:
    def cell(label, n):
        return f'<td class="cell"><span class="lbl">{label}</span>{n:,}</td>'
    return f"""
<table class="dl-two">
<tr><th></th><th>{event.capitalize()}</th><th>All other events</th><th>Total</th></tr>
<tr><th>{drug.capitalize()}</th>{cell("a", t.a)}{cell("b", t.b)}<td>{t.drug_total:,}</td></tr>
<tr><th>All other drugs</th>{cell("c", t.c)}{cell("d", t.d)}<td>{t.other_total:,}</td></tr>
<tr><th>Total</th><td>{t.event_total:,}</td><td>{t.non_event_total:,}</td><td>{t.n:,}</td></tr>
</table>"""


@st.cache_resource
def signal_log() -> SignalLog:
    log = SignalLog()
    seed = Path(config.SIGNAL_LOG_SEED)
    if log.is_empty() and seed.exists():          # hosted storage is temporary: start from seed
        log.import_json(seed.read_text(encoding="utf-8"))
    return log


def add_to_log(res: DetectionResult, pt: str) -> None:
    row = res.table[res.table["Reaction (PT)"] == pt].iloc[0]
    snap = {"statistics": statistics_snapshot(res.results[pt]),
            "extraction": extraction_snapshot(res.record),
            "dme": bool(row["DME"]), "filters": filters_text(res.filters)}
    sid, created = signal_log().add_signal(res.generic_name, pt, snap)
    st.session_state["log_selected"] = sid
    if created:
        st.toast(f"{sid} added to the signal log (Under review).", icon=":material/check:")
    else:
        st.toast(f"Already in the signal log as {sid}.", icon=":material/info:")


def detail_panel(res: DetectionResult, pt: str) -> None:
    row = res.table[res.table["Reaction (PT)"] == pt].iloc[0]
    with st.container(border=True):
        h1, h2, h3 = st.columns([2.4, 1, 1])
        h1.markdown(f"#### {pt.capitalize()}")
        if pd.isna(row["Error"]):
            if h2.button("Open in Triage", icon=":material/rule:", key=f"to_triage_{pt}",
                         width="stretch"):
                st.session_state["triage_pt"] = pt
                st.switch_page(TRIAGE_PAGE)
            if h3.button("Add to signal log", icon=":material/playlist_add:", key=f"to_log_{pt}",
                         width="stretch"):
                add_to_log(res, pt)
        if pd.notna(row["Error"]):
            st.error(row["Error"])
            return
        r = res.results[pt]
        t = r.table
        th = res.thresholds.as_dict()

        left, right = st.columns([5, 4], gap="large")
        with left:
            st.markdown("**2×2 table** (numbers of reports)")
            st.html(two_by_two_html(t, res.generic_name, pt))
            st.write(explain(t, pt))
            if r.small_numbers:
                st.warning(f"Small numbers: only {t.a} report(s) with this drug and event. "
                           "Estimates are unstable; read the intervals, not the point values.")
            if row["DME"]:
                st.info("On the EMA Designated Medical Event list. Serious is not the same as "
                        "DME; many serious events are not on the list.")
        with right:
            st.markdown(f"{dots_html(r.rules.count)} &nbsp; **Rules met: {r.rules.label}**",
                        unsafe_allow_html=True)
            for ok, name, text in [(r.rules.prr, "PRR", th["PRR rule"]),
                                   (r.rules.ror, "ROR", th["ROR rule"]),
                                   (r.rules.ic, "IC", th["IC rule"])]:
                badge = f":blue-badge[✓ {name} rule met]" if ok else f":gray-badge[✗ {name} rule not met]"
                st.markdown(f"{badge} &nbsp; <small>{text.replace('chi2', 'χ²')}</small>",
                            unsafe_allow_html=True)
            st.markdown(" ")
            m = pd.DataFrame({"Estimate": [
                fmt_ci(r.prr.value, r.prr.lower, r.prr.upper, r.prr.note),
                fmt_ci(r.ror.value, r.ror.lower, r.ror.upper, r.ror.note),
                fmt_num(r.chi2), f"{fmt_num(r.ic)} (IC025 {fmt_num(r.ic025)})"]},
                index=["PRR (95% CI)", "ROR (95% CI)", "χ² (Yates)", "IC"])
            st.table(m)
            st.caption(CAUSALITY_NOTE)

        st.markdown("**Quarterly trend** (FDA receipt date, 8 most recent complete quarters)")
        trends = st.session_state.setdefault("trends", {})
        if pt not in trends:
            try:
                data_date = parse_data_date(
                    res.record.openfda_last_updated.replace("MIXED: ", "")[:10])
                trends[pt] = quarterly_trend(OpenFDAClient(), res.generic_name, pt,
                                             res.filters, data_date)
            except requests.RequestException as exc:
                st.error(f"The trend could not be fetched: {exc}")
                return
        df, tr = trends[pt]
        c1, c2 = st.columns([3, 1], gap="large")
        fig = go.Figure(go.Bar(
            x=df["Quarter"], y=df["Reports"],
            marker_color=["#9FB3C8"] * 4 + [BLUE] * 4,
            hovertemplate="%{x}: %{y} reports<extra></extra>"))
        c1.plotly_chart(style_fig(fig, 240), width="stretch")
        with c2.container(border=True):
            st.caption("Reporting trend")
            st.markdown(f"**{tr.status}**")
        c2.write(f"Last 4 quarters: **{tr.recent}**  \nPrevious 4: **{tr.previous}**  \n"
                 f"Ratio: **{tr.ratio_text}**")
        st.caption("Increasing reporting: ratio ≥ 1.5 and at least 3 recent reports. Decreasing "
                   "reporting: ratio ≤ 0.67. Fewer than 6 reports in 8 quarters: insufficient data. "
                   "This describes reporting volume, not risk: changes often reflect stimulated "
                   "reporting, publicity, label changes or changes in use."
                   + (" Your year filter also applies here." if res.filters.year_from
                      or res.filters.year_to else ""))


def forest_plot(t: pd.DataFrame, measure: str, max_rows: int = 40) -> go.Figure:
    d = t[t[measure].notna()].head(max_rows).iloc[::-1]
    fig = go.Figure(go.Scatter(
        x=d[measure], y=d["Reaction (PT)"].str.capitalize(), mode="markers",
        marker=dict(color=d["Rules met"].map(SCALE), size=9, symbol="square",
                    line=dict(color=INK, width=0.5)),
        error_x=dict(type="data", symmetric=False, color="#7A8794",
                     array=d[f"{measure} high"] - d[measure],
                     arrayminus=d[measure] - d[f"{measure} low"], thickness=1.3, width=3),
        customdata=d[["a", "Rules met"]],
        hovertemplate=(f"%{{y}}<br>{measure} %{{x:.2f}}<br>a = %{{customdata[0]}}"
                       "<br>rules met %{customdata[1]} of 3<extra></extra>"),
    ))
    fig.add_vline(x=1, line_dash="dash", line_color=MUTED)
    fig.update_xaxes(type="log", title=f"{measure} with 95% CI (log scale)")
    return style_fig(fig, max(320, 22 * len(d) + 80))


def filters_text(f: Filters) -> str:
    parts = []
    if f.serious_only:
        parts.append("serious only")
    for v in (f.outcome, f.sex, f.age_group):
        if v:
            parts.append(v.lower())
    if f.year_from or f.year_to:
        parts.append(f"{f.year_from or 2004}–{f.year_to or 'present'}")
    return ", ".join(parts) if parts else "none"


def rule_panel(b: dict) -> None:
    """How the three rules behave across this screen (reviewer question: why so many?)."""
    if not b or not b.get("screened"):
        return
    n = b["screened"]
    flagged = n - b["met_0"]
    with st.expander(f"How the rules behave in this screen: {flagged} of {n} pairs meet at "
                     "least one rule"):
        c1, c2 = st.columns(2)
        c1.markdown("**Pairs meeting each rule**")
        c1.table(pd.DataFrame({"Pairs": [b["prr"], b["ror"], b["ic"]]},
                              index=["PRR rule", "ROR rule", "IC rule"]))
        c2.markdown("**Pairs by number of rules met**")
        c2.table(pd.DataFrame({"Pairs": [b["met_3"], b["met_2"], b["met_1"], b["met_0"]]},
                              index=["3 of 3", "2 of 3", "1 of 3", "0 of 3"]))
        st.write(f"IC rule only: {b['ic_only']}. Flagged pairs with fewer than 5 reports: "
                 f"{b['flagged_small_numbers']}.")
        st.caption("Why the share can be high: the events screened are the drug's most frequently "
                   "reported ones, not a random sample; with millions of background reports the "
                   "intervals are very narrow, so small differences pass the rules; the three "
                   "rules share one 2×2 table and tend to agree; and terms for the treated "
                   "condition or related diseases (confounding by indication) often appear. A "
                   "rule being met starts an assessment; it does not end one.")


def results_view(res: DetectionResult) -> None:
    rec, tot = res.record, res.totals
    st.html(f'<p class="dl-drug">{res.generic_name.capitalize()}</p>'
            f'<p class="dl-meta">openFDA data as of {rec.openfda_last_updated}. '
            f'Filters: {filters_text(res.filters)}. Extraction {rec.extraction_id}. '
            'Sidebar changes apply when you run the analysis again.</p>')
    if rec.data_provenance.get("mixed_data_versions"):
        st.warning("Cached answers come from different openFDA data releases. Open Data in the "
                   "sidebar, tick 'Ignore cache' and run again.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Drug reports matched", compact(tot["drug_reports"]), border=True,
              help=f"Exactly {tot['drug_reports']:,} reports")
    c2.metric("Database reports", compact(tot["all_reports"]), border=True,
              help=f"Exactly {tot['all_reports']:,} reports")
    c3.metric("Events analysed", tot["reactions_analysed"], border=True)
    c4.metric("Pairs meeting ≥ 1 rule", tot["pairs_meeting_any_rule"], border=True)
    n_var, n_combo = len(res.name_variants), tot.get("combination_names_matched", 0)
    st.caption("Drug matched on the harmonised generic name, in any role (suspect, concomitant or "
               "interacting). Many reports lack this field, so counts are underestimates. "
               f"{n_var} name variant(s) matched, including {n_combo} combination product(s).")
    if res.name_variants:
        with st.expander("Drug names matched"):
            st.write("A phrase match includes salts and combination products that contain the "
                     "drug. Report counts per name; a report can list more than one.")
            st.dataframe(pd.DataFrame({"Generic name in openFDA": list(res.name_variants),
                                       "Reports": list(res.name_variants.values())}),
                         hide_index=True, width="stretch")
    st.info(DISPROPORTIONALITY_NOTE, icon=":material/info:")

    if res.table.empty:
        st.warning(f"No reports found for '{res.generic_name}'. Check the spelling of the generic "
                   "name or loosen the filters.")
        return

    tabs = st.tabs(["Screening results", "Forest plot", "Most reported events",
                    "EMA DME safety net", "Extraction record"])

    with tabs[0]:
        st.caption(f"About {tot['reactions_analysed']} events were screened, so some pairs will "
                   "meet rules by chance alone. Select a row to see its 2×2 table and trend.")
        rule_panel(rec.rule_breakdown)
        if tot["pairs_with_errors"]:
            st.warning(f"{tot['pairs_with_errors']} pair(s) could not be analysed (for example a "
                       "term openFDA cannot search for, or inconsistent counts). They are listed "
                       "with the reason in the Error column; the rest of the screen is complete.")
        c1, c2 = st.columns([2, 1])
        query = c1.text_input("Find an event", placeholder="e.g. rhabdo",
                              label_visibility="collapsed")
        only_rules = c2.toggle("Only pairs meeting ≥ 1 rule")
        t = res.table
        if only_rules:
            t = t[t["Rules met"] > 0]
        if query:
            t = t[t["Reaction (PT)"].str.contains(query.strip(), case=False, regex=False)]
        t = t.reset_index(drop=True)
        if t.empty:
            st.info("No events match. Clear the search or switch off the toggle.")
            return

        event = st.dataframe(
            styled(display_table(t), t["Rules met"]), hide_index=True, width="stretch",
            height=min(420, 38 + 35 * len(t)), on_select="rerun", selection_mode="single-row",
            key=f"results_table_{only_rules}_{query.strip().lower()}",
            column_config={
                "Rules met": st.column_config.TextColumn(width=92),
                "Event (MedDRA PT)": st.column_config.TextColumn(width=210),
                "a": st.column_config.NumberColumn("a", width=58,
                                                   help="Reports with drug and event"),
                "PRR (95% CI)": st.column_config.TextColumn(width=150),
                "ROR (95% CI)": st.column_config.TextColumn(width=150),
                "IC (IC025)": st.column_config.TextColumn(width=96),
                "χ²": st.column_config.TextColumn(width=70),
                "PRR rule": st.column_config.TextColumn("PRR", width=46, help="PRR rule met"),
                "ROR rule": st.column_config.TextColumn("ROR", width=46, help="ROR rule met"),
                "IC rule": st.column_config.TextColumn("IC", width=40, help="IC rule met"),
                "Flags": st.column_config.TextColumn(width=110),
            })
        rows = event.selection.rows if event and event.selection else []
        if rows and rows[0] < len(t):
            st.session_state["selected_pt"] = t.iloc[rows[0]]["Reaction (PT)"]
        pt = st.session_state.get("selected_pt")
        if pt not in set(t["Reaction (PT)"]):
            pt = t.iloc[0]["Reaction (PT)"]
        detail_panel(res, pt)

    with tabs[1]:
        measure = st.segmented_control("Measure", ["PRR", "ROR"], default="PRR")
        st.caption("First 40 computable pairs in table order. Colour shows rules met on the "
                   "signal scale. Dashed line: 1, no disproportion.")
        st.plotly_chart(forest_plot(res.table, measure or "PRR"), width="stretch")

    with tabs[2]:
        top = res.table.dropna(subset=["a"]).nlargest(20, "a").iloc[::-1]
        fig = go.Figure(go.Bar(x=top["a"], y=top["Reaction (PT)"].str.capitalize(),
                               orientation="h", marker_color=top["Rules met"].map(SCALE),
                               hovertemplate="%{y}: %{x:,} reports<extra></extra>"))
        fig.update_xaxes(title="Reports with the drug (a)")
        st.plotly_chart(style_fig(fig, 560), width="stretch")
        st.caption("Frequency is not disproportionality: common events are often common for all "
                   "drugs. Bar colour shows rules met.")

    with tabs[3]:
        st.write(f"Events among those analysed that are on the {rec.dme_list_version}. Shown "
                 "regardless of the statistics, because the list is meant as a safety net.")
        dme_rows = res.table[res.table["DME"]].reset_index(drop=True)
        if dme_rows.empty:
            st.info("None of the analysed events are on the DME list.")
        else:
            cols = ["Rules met", "Event (MedDRA PT)", "a", "PRR (95% CI)", "IC (IC025)", "Flags"]
            st.dataframe(styled(display_table(dme_rows), dme_rows["Rules met"])
                         .hide([c for c in display_table(dme_rows).columns if c not in cols],
                               axis="columns"),
                         hide_index=True, width="stretch")

    with tabs[4]:
        st.markdown("**Check that the counts are report counts**")
        st.write("Re-fetches a and a+c for a common, a middle and a rare event by a direct search "
                 "for matching reports, and compares them with the values used in the screen.")
        if st.button("Run count check"):
            try:
                with st.spinner("Running the count check…"):
                    checks = verify_counts(OpenFDAClient(), res.generic_name, res.filters,
                                           res.table)
            except requests.RequestException as exc:
                st.error(f"The count check stopped: {exc}")
                checks = None
            if checks is not None:
                rec.count_checks = checks
                st.session_state["record_path"] = str(rec.save())
        if rec.count_checks:
            df = pd.DataFrame(rec.count_checks)
            df["event"] = df["event"].str.capitalize()
            df["match"] = df["match"].map({True: "✓ match", False: "✗ differs"})
            st.dataframe(df, hide_index=True, width="stretch")
            if all(c["match"] for c in rec.count_checks):
                st.success("Both ways give the same numbers, so the 2×2 cells are report counts. "
                           "Saved in the extraction record.")
            else:
                st.error("At least one count differs. Do not use this screen until the cause is "
                         "found; check whether the openFDA data were updated between queries.")
        st.divider()
        st.write("Everything needed to trace this result back to what openFDA returned.")
        st.json(rec.summary(), expanded=1)
        st.download_button("Download full record (JSON, includes every query URL)",
                           json.dumps(rec.to_dict(), indent=2),
                           file_name=f"{rec.extraction_id}.json", mime="application/json")
        st.caption(f"Also saved to {st.session_state.get('record_path')}")


def detection_page() -> None:
    settings = detection_sidebar()
    if settings["clicked"]:
        run(settings)
    res: DetectionResult | None = st.session_state.get("result")
    if res is None:
        empty_state()
    else:
        results_view(res)


# ---------------------------------------------------------------------------
# Other screens
# ---------------------------------------------------------------------------

def _highlight(passage: str, status: str, matched: str | None) -> str:
    """Escape markdown and bold the matched phrase (or each matched word)."""
    import re as _re
    text = _re.sub(r"([\\`*_{}\[\]<>#|$~])", r"\\\1", passage)
    if not matched:
        return text
    parts = [matched] if status == LABELLED else matched.split(" + ")
    for part in parts:
        pat = _re.compile(r"\b" + r"[\s\-]+".join(_re.escape(w) for w in part.split()) + r"\b",
                          _re.IGNORECASE)
        text = pat.sub(lambda m: f"**{m.group(0)}**", text)
    return text


def run_triage(res: DetectionResult, pt: str) -> dict:
    labels = st.session_state.setdefault("labels", {})
    if res.generic_name not in labels:
        labels[res.generic_name] = fetch_label(OpenFDAClient(), res.generic_name)
    label, note = labels[res.generic_name]
    lab = check_label(label, pt, note)

    row = res.table[res.table["Reaction (PT)"] == pt].iloc[0]
    seriousness = fetch_seriousness(OpenFDAClient(), res.generic_name, pt, res.filters)

    trends = st.session_state.setdefault("trends", {})
    if pt not in trends:
        data_date = parse_data_date(res.record.openfda_last_updated.replace("MIXED: ", "")[:10])
        trends[pt] = quarterly_trend(OpenFDAClient(), res.generic_name, pt, res.filters, data_date)
    tr = trends[pt][1]

    sc = score(lab.status, bool(row["DME"]), seriousness, int(row["Rules met"]), tr.status)

    # Label version goes into the extraction record (spec §3)
    rec = res.record
    rec.label_set_id, rec.label_effective_date = lab.set_id, lab.effective_date
    st.session_state["record_path"] = str(rec.save())
    return {"label": lab, "seriousness": seriousness, "trend": tr, "score": sc,
            "rules_met": int(row["Rules met"]), "dme": bool(row["DME"])}


def triage_page() -> None:
    st.title("Triage")
    st.caption("Label check, EMA DME match and an exploratory prioritisation score for one pair "
               "at a time. The score orders pairs for review; it is not a measure of risk.")
    res: DetectionResult | None = st.session_state.get("result")
    if res is None or res.table.empty:
        st.info("Run an analysis on the Detection screen first, then come back here.")
        return

    ok = res.table[res.table["Error"].isna()]
    options = ok["Reaction (PT)"].tolist()
    rules = dict(zip(ok["Reaction (PT)"], ok["Rules met"]))
    wanted = st.session_state.get("triage_pt")
    idx = options.index(wanted) if wanted in options else 0
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    pt = c1.selectbox(f"Pair from the {res.generic_name.capitalize()} screen", options, index=idx,
                      format_func=lambda x: f"{x.capitalize()}  ({rules[x]} of 3 rules)")
    st.session_state["triage_pt"] = pt
    store = st.session_state.setdefault("triage", {})
    key = (res.record.extraction_id, pt)
    if c2.button("Run triage", type="primary", width="stretch"):
        try:
            with st.spinner("Fetching the label and report counts…"):
                store[key] = run_triage(res, pt)
        except requests.RequestException as exc:
            st.error(f"Triage stopped: {exc}")
            return
    t = store.get(key)
    if t is None:
        st.info("Select **Run triage** to check the label and build the score for this pair.")
        return

    lab, sc, ser = t["label"], t["score"], t["seriousness"]
    h1, h2, h3 = st.columns([2.2, 1, 1], vertical_alignment="bottom")
    h1.markdown(f"### {res.generic_name.capitalize()} – {pt.capitalize()}")
    if h2.button("Open in Case review", icon=":material/description:", width="stretch"):
        st.switch_page(CASE_PAGE)
    if h3.button("Add to signal log", icon=":material/playlist_add:", width="stretch"):
        add_to_log(res, pt)

    left, right = st.columns([1, 2], gap="large", vertical_alignment="center")
    with left:
        with st.container(border=True):
            st.caption("Exploratory priority score")
            st.markdown(f"<span style='font-size:2.4rem;font-weight:700;color:{INK}'>{sc.total}</span>"
                        f"<span style='color:{MUTED}'> of 10</span> &nbsp; "
                        f"**{sc.band}**", unsafe_allow_html=True)
            st.caption("Higher ≥ 7 · Medium 4–6 · Lower ≤ 3")
    with right:
        st.write(SCORE_NOTE + " Each factor below shows its points, the evidence and why it "
                 "counts, so the total can be checked by hand.")
    st.dataframe(pd.DataFrame({
            "Factor": [f.name for f in sc.factors],
            "Points": [f"{f.points} of {f.max_points}" for f in sc.factors],
            "Evidence": [f.evidence for f in sc.factors],
            "Why it counts": [f.rationale for f in sc.factors],
        }), hide_index=True, width="stretch",
            column_config={"Factor": st.column_config.TextColumn(width=130),
                           "Points": st.column_config.TextColumn(width=70),
                           "Evidence": st.column_config.TextColumn(width=280),
                           "Why it counts": st.column_config.TextColumn(width="large")})

    st.markdown("#### Label check")
    with st.container(border=True):
        badge = {LABELLED: ":blue-badge[Labelled]", POSSIBLY: ":orange-badge[Possibly labelled]",
                 NOT_FOUND: ":gray-badge[Not found in searched label text]",
                 UNAVAILABLE: ":gray-badge[Label unavailable]"}[lab.status]
        st.markdown(badge + (f" &nbsp; in **{lab.section}**" if lab.section else ""))
        if lab.passage:
            st.markdown("> " + _highlight(lab.passage, lab.status, lab.matched_term))
        if lab.status == POSSIBLY:
            st.warning("All significant words appear in one sentence, but not as the exact term. "
                       "The reviewer must confirm whether this passage describes the event.")
        if lab.status == NOT_FOUND:
            st.write("The term was not found in the searched sections. This does not mean the event "
                     "is new: the label may use a synonym or a broader term. Read the label.")
        if lab.status == UNAVAILABLE:
            st.warning("No label returned by openFDA for this drug: check the label manually.")
        if lab.spelling_note:
            st.caption(lab.spelling_note)
        meta = []
        if lab.product:
            meta.append(f"Product: {lab.product}")
        if lab.effective_date:
            meta.append(f"Label effective {lab.effective_date}")
        if lab.set_id:
            meta.append(f"Set ID {lab.set_id}")
        if lab.sections_searched:
            meta.append("Sections searched: " + ", ".join(lab.sections_searched))
        if meta:
            st.caption(". ".join(meta) + ".")
        if lab.label_note:
            st.caption(lab.label_note)
        st.caption(LABEL_NOTE)

    st.markdown("#### EMA Designated Medical Event list")
    st.write(("**On the list.** " if t["dme"] else "**Not on the list.** ")
             + f"({res.record.dme_list_version}). Serious is not the same as DME; many serious "
               "events are not on the list.")

    st.markdown("#### Reports for this pair")
    share = ser.serious_share
    st.write(f"{ser.reports:,} reports with the same filters as the screen; "
             f"{ser.serious:,} serious ({'—' if share is None else f'{share:.0%}'}); "
             f"{ser.fatal:,} with a fatal outcome. Fatal outcome is a report-level flag and does "
             "not mean the event or the drug caused the death.")


def _pair_picker(res: DetectionResult, label: str):
    ok = res.table[res.table["Error"].isna()]
    options = ok["Reaction (PT)"].tolist()
    rules = dict(zip(ok["Reaction (PT)"], ok["Rules met"]))
    wanted = st.session_state.get("triage_pt")
    idx = options.index(wanted) if wanted in options else 0
    pt = st.selectbox(label, options, index=idx,
                      format_func=lambda x: f"{x.capitalize()}  ({rules[x]} of 3 rules)")
    st.session_state["triage_pt"] = pt
    return pt


def _count_table(counts: dict[str, int], n: int, name: str, top: int | None = None) -> pd.DataFrame:
    items = list(counts.items())[:top] if top else list(counts.items())
    return pd.DataFrame({name: [k for k, _ in items], "Reports": [v for _, v in items],
                         "%": [f"{100 * v / n:.0f}%" if n else "—" for _, v in items]})


def _ct(counts: dict[str, int], n: int, name: str, top: int | None = None) -> pd.DataFrame:
    """Count table for st.table (static, so numbers always show, also when printed)."""
    return _count_table(counts, n, name, top).set_index(name)


def case_review_page() -> None:
    st.title("Case review")
    st.caption("Individual reports for one pair, as reported. Missing fields are shown as "
               "'not reported' and never counted as 'no'.")
    res: DetectionResult | None = st.session_state.get("result")
    if res is None or res.table.empty:
        st.info("Run an analysis on the Detection screen first, then come back here.")
        return

    c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    with c1:
        pt = _pair_picker(res, f"Pair from the {res.generic_name.capitalize()} screen")
    n_req = c2.number_input("Reports to retrieve", 10, 100, 50, step=10,
                            help="Most recent first, by FDA receipt date. Default 50, up to 100.")
    store = st.session_state.setdefault("cases", {})
    key = (res.record.extraction_id, pt, int(n_req))
    if c3.button("Load reports", type="primary", width="stretch"):
        try:
            with st.spinner("Fetching individual reports…"):
                raw, total = fetch_reports(OpenFDAClient(), res.generic_name, pt, res.filters, int(n_req))
        except requests.RequestException as exc:
            st.error(f"Case review stopped: {exc}")
            return
        rows = [parse_report(r, res.generic_name, pt) for r in raw]
        store[key] = {"raw": raw, "rows": rows, "summary": summarise(rows, total, pt)}
    data = store.get(key)
    if data is None:
        st.info("Select **Load reports** to retrieve the individual reports for this pair.")
        return

    rows, sm, raw = data["rows"], data["summary"], data["raw"]
    n = sm.retrieved
    h1, h2, h3 = st.columns([2.2, 1, 1], vertical_alignment="bottom")
    h1.markdown(f"### {res.generic_name.capitalize()} – {pt.capitalize()}")
    if h2.button("Add to signal log", icon=":material/playlist_add:", width="stretch",
                 key="case_add_log"):
        add_to_log(res, pt)
    if h3.button("Open signal log", icon=":material/history_edu:", width="stretch"):
        sid = signal_log().find(res.generic_name, pt)
        if sid:
            st.session_state["log_selected"] = sid
        st.switch_page(LOG_PAGE)
    st.write(f"**{n:,} retrieved of {sm.total:,} total** reports, most recent first (FDA receipt "
             f"date), with the same filters as the screen ({filters_text(res.filters)}).")
    if n == 0:
        st.warning("No individual reports were returned for this pair.")
        return

    if sm.confounding:
        st.warning(f"**Possible confounding by indication.** The event resembles an indication "
                   f"reported for {res.generic_name.lower()} in these reports: "
                   f"**{sm.confounding.capitalize()}**. The event may reflect the condition being "
                   "treated (or lack of effect) rather than an adverse reaction. Check the cases.",
                   icon=":material/warning:")

    roles = sm.counts["Drug role"]
    fatal = sm.counts["Seriousness criteria"].get("Death", 0)
    serious = sm.counts["Serious"].get("Yes", 0)
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Median age", "—" if sm.age_median is None else f"{sm.age_median:g} y", border=True,
              help=(f"Range {sm.age_min:g}–{sm.age_max:g} years; " if sm.age_median is not None else "")
                   + f"age not reported in {sm.age_missing_pct:.0f}% of reports")
    t2.metric("Drug as suspect", f"{100 * roles.get('Suspect', 0) / n:.0f}%", border=True,
              help="Share of retrieved reports where the drug is a suspect (not only concomitant)")
    t3.metric("Serious", f"{100 * serious / n:.0f}%", border=True)
    t4.metric("Death as seriousness", f"{fatal:,}", border=True,
              help="Report-level flag; not necessarily caused by the event or the drug")
    st.caption(f"Age: median {sm.age_median if sm.age_median is not None else '—'} years"
               + (f", range {sm.age_min:g}–{sm.age_max:g}" if sm.age_median is not None else "")
               + f"; not reported in {sm.age_missing_pct:.0f}% of reports.")

    tabs = st.tabs(["Who and where", "Seriousness and outcome", "Drug role and challenge",
                    "Other drugs and indications", "Report browser"])
    with tabs[0]:
        a, b, c = st.columns(3)
        a.table(_ct(sm.counts["Sex"], n, "Sex"))
        b.table(_ct(sm.counts["Reporter"], n, "Reporter"))
        c.table(_ct(sm.counts["Country"], n, "Country", top=8))
        st.caption("Reporter type matters: consumer and lawyer reports often lack clinical detail.")
    with tabs[1]:
        a, b = st.columns(2)
        a.table(_ct(sm.counts["Seriousness criteria"], n, "Seriousness criterion"))
        b.table(_ct(sm.counts["Event outcome"], n, "Outcome of this event"))
        st.caption("A report can meet several seriousness criteria, so these can add up to more than "
                   "100%.")
    with tabs[2]:
        a, b, c = st.columns(3)
        a.table(_ct(roles, n, "Drug role"))
        b.table(_ct(sm.counts["Dechallenge"], n, "Dechallenge"))
        c.table(_ct(sm.counts["Rechallenge"], n, "Rechallenge"))
        st.caption("Role: the strongest role of the drug in each report (suspect > interacting > "
                   "concomitant); the statistics count the drug in any role. Dechallenge is derived "
                   "from two reported fields: drug withdrawn or dose reduced, and the event outcome "
                   "(recovered/recovering = positive, not recovered = negative). Rechallenge is as "
                   "reported. 'Not reported' is never counted as negative.")
    with tabs[3]:
        a, b = st.columns(2)
        a.markdown("**Co-reported suspect drugs** (top 10)")
        a.table(pd.DataFrame(sm.co_suspects, columns=["Drug", "Reports"]).set_index("Drug")
                if sm.co_suspects else pd.DataFrame({"Drug": ["none reported"]}).set_index("Drug"))
        b.markdown(f"**Indications for {res.generic_name.lower()}** (top 10)")
        b.table(pd.DataFrame(sm.indications, columns=["Indication", "Reports"]).set_index("Indication")
                if sm.indications else pd.DataFrame({"Indication": ["not reported"]}).set_index("Indication"))
        st.caption("Other suspect drugs can explain the event (confounding by co-medication). An "
                   "indication that resembles the event suggests confounding by indication.")
    with tabs[4]:
        st.dataframe(pd.DataFrame(public_rows(rows)), hide_index=True, width="stretch", height=420,
                     column_config={"Age (years)": st.column_config.NumberColumn(format="%g")})
        st.markdown("**Raw openFDA record** (for checking fields by hand, Gate 2)")
        ids = [r["Report ID"] for r in rows]
        rc1, rc2 = st.columns([2, 1], vertical_alignment="bottom")
        rid = rc1.selectbox("Report ID", ids)
        show_of = rc2.checkbox("Show openFDA product codes",
                               help="The 'openfda' block lists every product code and manufacturer "
                                    "for the drug; hidden by default to keep the record readable.")
        rec_raw = raw[ids.index(rid)]
        if not show_of:
            import copy as _copy
            rec_raw = _copy.deepcopy(rec_raw)
            for d in rec_raw.get("patient", {}).get("drug", []) or []:
                if "openfda" in d:
                    d["openfda"] = "(hidden: tick 'Show openFDA product codes')"
        st.json(rec_raw, expanded=2)
        st.caption("Compare a few fields with the table row above, e.g. patientsex 1 = male, "
                   "2 = female; drugcharacterization 1 = suspect, 2 = concomitant; reactionoutcome "
                   "1 = recovered … 5 = fatal. The code tables are on the Method page.")


def evidence_for(drug: str, event: str) -> dict:
    """Triage and case-review evidence from this session for the pair, if any."""
    res: DetectionResult | None = st.session_state.get("result")
    ev: dict = {}
    if res is None or res.generic_name != drug:
        return ev
    ext = res.record.extraction_id
    t = st.session_state.get("triage", {}).get((ext, event))
    if t:
        ev["label"] = t["label"].to_dict()
        ev["score"] = t["score"].to_dict()
        ev["seriousness"] = {"reports": t["seriousness"].reports, "serious": t["seriousness"].serious,
                             "fatal": t["seriousness"].fatal}
        ev["trend"] = t["trend"].status
    cases = [v for k, v in st.session_state.get("cases", {}).items() if k[0] == ext and k[1] == event]
    if cases:
        sm = cases[-1]["summary"]
        n = sm.retrieved or 1
        ev["case_review"] = {
            "retrieved": sm.retrieved, "total": sm.total, "age_median": sm.age_median,
            "age_missing_pct": sm.age_missing_pct,
            "suspect_pct": round(100 * sm.counts["Drug role"].get("Suspect", 0) / n),
            "serious_pct": round(100 * sm.counts["Serious"].get("Yes", 0) / n),
            "death_flags": sm.counts["Seriousness criteria"].get("Death", 0),
            "reporters": sm.counts["Reporter"], "dechallenge": sm.counts["Dechallenge"],
            "rechallenge": sm.counts["Rechallenge"], "co_suspects": sm.co_suspects[:5],
            "indications": sm.indications[:5], "confounding": sm.confounding,
        }
    return ev


def _stats_line(stv: dict) -> str:
    def est(v, lo, hi, note):
        return note if note else f"{v:.2f} ({lo:.2f}–{hi:.2f})"
    return (f"a = {stv['a']:,}, b = {stv['b']:,}, c = {stv['c']:,}, d = {stv['d']:,}. "
            f"PRR {est(stv['prr'], stv['prr_lower'], stv['prr_upper'], stv['prr_note'])}; "
            f"ROR {est(stv['ror'], stv['ror_lower'], stv['ror_upper'], stv['ror_note'])}; "
            f"χ² {stv['chi2']:.2f}; IC {stv['ic']:.2f} (IC025 {stv['ic025']:.2f}). "
            f"Rules met {stv['rules_met']} of 3"
            + (" (small numbers)." if stv.get("small_numbers") else "."))


def signal_log_page() -> None:
    st.title("Signal log")
    st.caption("One entry per drug–event pair, with the evidence frozen when it was added. "
               "Decisions are appended with a rationale; earlier decisions are kept and cannot be "
               "edited.")
    log = signal_log()
    entries = log.entries()
    if not entries:
        st.info("The log is empty. On Detection or Triage, select **Add to signal log** for a pair.")
        return

    df = pd.DataFrame(entries)
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1], vertical_alignment="bottom")
    statuses = c1.multiselect("Status", [UNDER_REVIEW] + DECISIONS)
    drugs = c2.multiselect("Drug", sorted(df["Drug"].unique()))
    c3.download_button("CSV export", log.export_csv(), file_name="drishti_signal_log.csv",
                       mime="text/csv", width="stretch", icon=":material/download:",
                       help="The full log, one row per decision.")
    c4.download_button("JSON", log.export_json(), file_name="signal_log_seed.json",
                       mime="application/json", width="stretch",
                       help="Full log with evidence. Save as data/signal_log_seed.json to ship it "
                            "with a deployment.")
    view = df
    if statuses:
        view = view[view["Status"].isin(statuses)]
    if drugs:
        view = view[view["Drug"].isin(drugs)]
    shown = view.assign(**{"Drug": view["Drug"].str.capitalize(),
                           "Event (PT)": view["Event (PT)"].str.capitalize()})
    st.dataframe(shown, hide_index=True, width="stretch",
                 column_config={"Event (PT)": st.column_config.TextColumn(width="medium"),
                                "Status": st.column_config.TextColumn(width="medium")})

    ids = view["Signal ID"].tolist()
    if not ids:
        st.info("No entries match the filters.")
        return
    want = st.session_state.get("log_selected")
    sid = st.selectbox("Entry", ids, index=ids.index(want) if want in ids else 0,
                       format_func=lambda x: f"{x}: {df.set_index('Signal ID').loc[x, 'Drug'].capitalize()}"
                                             f" – {df.set_index('Signal ID').loc[x, 'Event (PT)'].capitalize()}")
    st.session_state["log_selected"] = sid
    e = log.get(sid)
    snap, hist = e["snapshot"], log.history(sid)
    stv, ex = snap["statistics"], snap["extraction"]

    st.markdown(f"### {sid}: {e['drug'].capitalize()} – {e['event'].capitalize()}")
    st.markdown(f"Status: **{log.status(sid)}** · detected {e['detection_date']} · "
                f"openFDA data {ex.get('openfda_last_updated')} · extraction {ex.get('extraction_id')}")
    with st.expander("Evidence frozen when the entry was added"):
        st.write(_stats_line(stv))
        st.write(f"Filters: {snap.get('filters', 'none')}. EMA DME list: "
                 f"{'on the list' if snap.get('dme') else 'not on the list'} "
                 f"({ex.get('dme_list_version')}). App {ex.get('app_version')}.")
        st.json(ex.get("query_parameters", {}), expanded=False)

    st.markdown("#### History")
    if hist:
        st.dataframe(pd.DataFrame([{"Date": h["decision_date"].replace("T", " ")[:16] + " UTC",
                                    "Decision": h["decision"], "Reviewer": h["reviewer"],
                                    "Rationale": h["rationale"]} for h in hist]),
                     hide_index=True, width="stretch",
                     column_config={"Rationale": st.column_config.TextColumn(width="large")})
        for h in hist:
            with st.expander(f"Evidence attached to the {h['decision_date'][:10]} decision "
                             f"({h['decision'].split(' (')[0]})"):
                st.json(h["evidence"] or {"note": "no triage or case review evidence attached"},
                        expanded=1)
    else:
        st.write("No decisions yet: the entry is **Under review**.")

    st.markdown("#### Record a decision")
    ev = evidence_for(e["drug"], e["event"])
    have = [name for name, k in (("triage (label, score)", "label"), ("case review", "case_review"))
            if k in ev]
    if have:
        st.success("Evidence from this session will be attached: " + " and ".join(have) + ".")
    else:
        st.info("No triage or case review from this session for this pair. Run them first (with the "
                "same drug on Detection) so the evidence is saved with the decision.")
    decision = st.radio("Decision", DECISIONS, index=None)
    rationale = st.text_area("Rationale (required, at least 50 characters)", height=140,
                             placeholder="Why: the statistics, label, cases (timing, dechallenge, "
                                         "co-medication, indication), data quality and limitations.")
    st.caption(f"{len(rationale.strip())} characters")
    reviewer = st.text_input("Reviewer", value=st.session_state.get("reviewer", ""))
    if "[" in rationale and "]" in rationale:
        st.warning("The rationale contains square brackets. Check that no placeholder such as "
                   "[x.xx] is left unfilled.")
    st.markdown(f"Saving to **{sid}: {e['drug'].capitalize()} – {e['event'].capitalize()}**")
    checked = st.checkbox(f"I have checked this decision is for {sid} ({e['drug'].capitalize()} – "
                          f"{e['event'].capitalize()}) and the rationale is about this pair. Saved "
                          "decisions cannot be edited or deleted.", key=f"confirm_{sid}")
    if st.button("Save decision", type="primary", icon=":material/save:", disabled=not checked):
        try:
            log.add_decision(sid, decision or "", rationale, reviewer, ev)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state["reviewer"] = reviewer
            st.toast(f"Decision saved for {sid}.", icon=":material/check:")
            st.rerun()


def about_page() -> None:
    st.html(f'<p class="dl-drug">About DRISHTI-lite</p><p class="dl-tagline">{TAGLINE}</p>')
    st.markdown(f"""
DRISHTI-lite is a research prototype written in Python. It screens public FDA adverse event
reports (FAERS, through the openFDA API) for drug–event pairs that are reported more often than
expected, and supports the next steps a reviewer would take: triage, case review and a documented
decision with a written rationale.

*Drishti* means *sight* in Sanskrit. The aim is to help a reviewer see patterns in safety reports
without mistaking them for proof.

#### Why we built it
To practise the aggregate side of pharmacovigilance: turning spontaneous reports into a
disproportionality screen, then judging each result with the label, the individual cases and the
known limits of the data, and writing down why.

#### What it does now
- **Detection:** PRR, ROR (with 95% confidence intervals), Yates χ² and the information component
  (IC with IC025) for a drug's most frequently reported events, checked against three predefined
  rules. Every pair shows its full 2×2 table.
- **Checks on the data:** small-number warnings, a quarterly reporting trend, the EMA Designated
  Medical Event list as a safety net, a list of drug names matched, and a count check that confirms
  the numbers are report counts.
- **Traceability:** every analysis saves an extraction record with the openFDA data date, the
  query settings and every query sent.

#### Planned
- **Triage:** label check against the current FDA label, DME match and an exploratory priority score.
- **Case review:** individual reports, drug roles, dechallenge and rechallenge as reported, and
  possible duplicates.
- **Signal log:** decisions (potential signal, refuted or monitoring) with rationale and history.

#### Data
- US FDA Adverse Event Reporting System (FAERS), via the openFDA drug adverse event API.
- Events as MedDRA Preferred Terms, as supplied by openFDA.
- EMA Designated Medical Event list (EMA/326038/2020).

#### Approach
The workflow is informed by selected principles of EMA Good Pharmacovigilance Practices (GVP),
Module IX on signal management. Formulas, thresholds and limitations are on the
**Method and limitations** page.

#### Intended use
For education, research and portfolio use only. Results show disproportionate reporting, not
incidence, risk or causation. DRISHTI-lite is not a validated or regulatory-compliant system and
must not be used for clinical or regulatory decisions.

#### Built with
Python, Streamlit, pandas, Plotly, Requests, SQLite and pytest.

#### Developed by
**Vaibhav Kattimani** and **Vishal Patil**

Version {config.APP_VERSION}.
""")


def method_page() -> None:
    st.title("Method and limitations")
    st.markdown(r"""
#### 2×2 table
Numbers of reports, with the same filters for drug and background.

|  | Event | All other events | Total |
|---|---|---|---|
| Drug | a | b | a+b |
| All other drugs | c | d | c+d |
| Total | a+c | b+d | N |

b = (a+b) − a, c = (a+c) − a, d = N − (a+b) − (a+c) + a. A negative cell stops the calculation for that pair.

#### Measures

| Measure | Formula | Interval |
|---|---|---|
| PRR | [a/(a+b)] / [c/(c+d)] | exp(ln PRR ± 1.96·SE), SE = √(1/a − 1/(a+b) + 1/c − 1/(c+d)) |
| ROR | (a·d) / (b·c) | exp(ln ROR ± 1.96·SE), SE = √(1/a + 1/b + 1/c + 1/d) |
| χ² | N·max(\|ad − bc\| − N/2, 0)² / [(a+b)(c+d)(a+c)(b+d)], Yates, 1 df | — |
| IC | log₂[(a + 0.5)/(E + 0.5)], E = (a+b)(a+c)/N | IC025 ≈ IC − 3.3(a+0.5)^−½ − 2(a+0.5)^−³⁄₂ |

IC: Norén GN, Hopstadius J, Bate A. Shrinkage observed-to-expected ratios for robust and transparent
large-scale pattern discovery. *Stat Methods Med Res* 2013;22(1):57–69.

#### Drug matching
Phrase match on the harmonised generic name (`patient.drug.openfda.generic_name`), with the drug in
any role. A phrase match also matches salts and combination products that contain the drug; they are
included, and the names matched are listed with each screen and in the extraction record.

#### Zero cells and small numbers
No continuity correction is applied. PRR needs a > 0 and c > 0, so it is still computed when b or d
is 0. ROR needs all four cells above 0. Otherwise the measure is shown as "not computable" with the
cell named. IC is always computed. Fewer than 5 reports (a < 5) triggers a small-numbers warning.

#### Count check
openFDA count queries return numbers of reports. For each screen, a common, a middle and a rare
event can be re-checked by a direct search for matching reports; both ways must agree.

#### Predefined rules
Defaults, adjustable in the sidebar: PRR ≥ 2 and a ≥ 3 and χ² ≥ 4 (Evans et al. 2001); lower 95% CI
of ROR > 1 and a ≥ 3; IC025 > 0 (WHO-UMC practice). Shown as "Rules met: n of 3". The three
rules are calculated from the same 2×2 table, so they are not independent confirmations.

#### Label check (Triage)
The most recent single-ingredient FDA label for the drug (openFDA drug/label, by effective date) is
searched in this order: Boxed Warning, Warnings and Precautions, Warnings, Precautions, Adverse
Reactions. **Labelled**: the exact PT phrase is found (case-insensitive, whole words). **Possibly
labelled**: all significant words of the PT appear in one sentence; the reviewer must confirm.
**Not found in searched label text**: neither. **Label unavailable**: no label returned; check
manually. FAERS uses MedDRA British spelling, so a US spelling (e.g. diarrhoea → diarrhea) is also
tried and reported. Text matching on one US label may miss synonyms or match unrelated text, and
"not found" does not mean "new".

#### Exploratory prioritisation score (Triage)
Not found in label +2 · possibly labelled +1 · on EMA DME list +2 · at least one report with a fatal
outcome +2 · more than 50% of reports serious +1 · rules met 3 of 3 +2 or 2 of 3 +1 · increasing
reporting +1. Maximum 10: Higher ≥ 7, Medium 4–6, Lower ≤ 3. The weights are a documented design
choice, not a validated model; the score orders pairs for review and is not a measure of risk.

#### Case review: openFDA fields used
| Field | Codes |
|---|---|
| patient.patientsex | 0 unknown, 1 male, 2 female |
| patient.patientonsetage + patientonsetageunit | 800 decade, 801 year, 802 month, 803 week, 804 day, 805 hour |
| primarysource.qualification | 1 physician, 2 pharmacist, 3 other health professional, 4 lawyer, 5 consumer |
| occurcountry (else primarysource.reportercountry) | country code |
| serious; seriousnessdeath, …lifethreatening, …hospitalization, …disabling, …congenitalanomali, …other | 1 yes, 2 no (serious) / 1 = criterion met |
| patient.reaction.reactionoutcome | 1 recovered, 2 recovering, 3 not recovered, 4 recovered with sequelae, 5 fatal, 6 unknown |
| patient.drug.drugcharacterization | 1 suspect, 2 concomitant, 3 interacting |
| patient.drug.actiondrug | 1 withdrawn, 2 dose reduced, 3 dose increased, 4 not changed, 5 unknown, 6 not applicable |
| patient.drug.drugrecurreadministration | 1 reaction recurred (positive rechallenge), 2 did not recur (negative), 3 unknown |
| patient.drug.drugindication | MedDRA term as reported |

Dechallenge is derived (no field of its own): drug withdrawn or dose reduced plus event recovered or
recovering = positive; plus not recovered = negative; anything else = not reported. A possible-
confounding note appears when the event resembles one of the drug's top indications (shared word stem,
e.g. *blood cholesterol increased* and *hypercholesterolaemia*). Possible duplicates are not flagged in
this version; openFDA does not de-duplicate.

#### Trend
Reports per calendar quarter by FDA receipt date, over the 8 most recent complete quarters (judged
against openFDA's data date). Increasing reporting: last 4 ≥ 1.5 × previous 4 and at least 3 reports
in the last 4. Decreasing reporting: ratio ≤ 0.67. Otherwise no substantial change. Fewer than 6
reports: insufficient data. The labels describe reporting volume, not risk.
""")
    st.markdown("#### Limitations")
    st.info("Draft. Rewrite these in your own words before Phase 3 (spec §10).")
    st.markdown("""
1. Spontaneous reports have no exposure denominator, give no incidence and cannot establish causality.
2. Reporting biases: under-reporting, stimulated (notoriety) reporting, Weber effect, changes over time.
3. Confounding by indication and by co-medication; the drug is counted in any role.
4. Masking by strongly associated drug–event pairs in the background.
5. openFDA does not de-duplicate reports.
6. Drug matching uses the harmonised generic name, which many reports lack, so counts are
   underestimates; combination products containing the drug are included.
7. Analysis at MedDRA PT level only, so related terms are split.
8. Screening many pairs produces chance findings; only the drug's most frequently reported events
   are screened, not every MedDRA PT.
9. Label check (Phase 2) is text matching on one US label version.
10. The prioritisation score (Phase 2) is exploratory, with unvalidated weights.
11. Missing case data are common and shown as "not reported".
12. Research prototype for education and portfolio use; not a validated or regulatory-compliant system.
""")


TRIAGE_PAGE = st.Page(triage_page, title="Triage", icon=":material/rule:")
CASE_PAGE = st.Page(case_review_page, title="Case review", icon=":material/description:")
LOG_PAGE = st.Page(signal_log_page, title="Signal log", icon=":material/history_edu:")
nav = st.navigation({
    "Workflow": [
        st.Page(detection_page, title="Detection", icon=":material/query_stats:", default=True),
        TRIAGE_PAGE,
        CASE_PAGE,
        LOG_PAGE,
    ],
    "Reference": [
        st.Page(method_page, title="Method and limitations", icon=":material/functions:"),
        st.Page(about_page, title="About", icon=":material/info:"),
    ],
})
nav.run()

st.sidebar.divider()
st.sidebar.caption(
    "Developed by **Vaibhav Kattimani** and **Vishal Patil**  \n"
    f"Version {config.APP_VERSION}  \n"
    "Research prototype. Not for clinical decision-making."
)

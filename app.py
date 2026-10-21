"""Travel.pk | Competitor Package Price Benchmark  (Streamlit dashboard).

Run locally:   streamlit run app.py
All numbers come from benchmark.py and the CSV files in ./data.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import benchmark as bm

st.set_page_config(
    page_title="Travel.pk | Competitor Package Price Benchmark",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVY = "#0B1F3A"
TEAL = "#0E9AA7"
SLATE = "#475569"
LIGHT = "#F1F5F9"

st.markdown(
    f"""
    <style>
    .block-container {{ padding-top: 1.6rem; max-width: 1280px; }}
    h1, h2, h3 {{ color: {NAVY}; letter-spacing: -0.01em; }}
    .hero {{ background: {NAVY}; color: #fff; padding: 1.4rem 1.6rem; border-radius: 10px; margin-bottom: 1rem; }}
    .hero h1 {{ color: #fff; margin: 0 0 .25rem 0; font-size: 1.7rem; }}
    .hero p {{ margin: 0; color: #CBD5E1; font-size: .95rem; }}
    .hero .meta {{ margin-top: .6rem; font-size: .8rem; color: #7DD3DB; }}
    .kpi {{ background: #fff; border: 1px solid #E2E8F0; border-top: 4px solid {TEAL};
            border-radius: 8px; padding: .9rem 1rem; height: 100%; }}
    .kpi .v {{ font-size: 2rem; font-weight: 700; color: {NAVY}; line-height: 1.1; }}
    .kpi .l {{ font-size: .8rem; color: {SLATE}; margin-top: .2rem; }}
    .kpi.warn {{ border-top-color: #B45309; }}
    .pill {{ display:inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }}
    .pill.ok {{ background: #D1FAE5; color: #065F46; }}
    .pill.warn {{ background: #FEF3C7; color: #92400E; }}
    .pill.bad {{ background: #E2E8F0; color: #334155; }}
    .card {{ background: {LIGHT}; border-radius: 8px; padding: 1rem 1.1rem; }}
    .card h4 {{ margin: 0 0 .4rem 0; color: {NAVY}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_all():
    packages, offers, quotes = bm.load_data()
    return packages, offers, quotes


try:
    packages, offers, quotes = load_all()
except bm.DataValidationError as exc:
    st.error(f"The research dataset could not be loaded: {exc}")
    st.stop()
except Exception as exc:  # defensive: never show a raw traceback to a reviewer
    st.error(f"Unexpected error while loading data: {exc}")
    st.stop()

# Optional session-only Travel.pk quotes uploaded by the user.
with st.sidebar:
    st.markdown("### Filters")
    st.caption("Filters apply to the tables and charts on the main tabs.")

session_quotes = quotes
quotes_note = ""
with st.sidebar.expander("Add Travel.pk quotes (session only)"):
    st.caption(
        "Upload a CSV with the columns of `data/travelpk_quotes.csv`. Verdicts are then calculated only "
        "where a verified, comparable competitor price exists. Nothing is saved."
    )
    uploaded = st.file_uploader("Quotes CSV", type=["csv"], key="quotes_upload")
    if uploaded is not None:
        try:
            raw = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
            missing = [c for c in bm.QUOTE_COLUMNS if c not in raw.columns]
            if missing:
                raise bm.DataValidationError(f"missing columns: {missing}")
            session_quotes = bm.validate_quotes(raw[bm.QUOTE_COLUMNS], set(packages["travelpk_id"]))
            quotes_note = f"Using {len(session_quotes)} uploaded Travel.pk quote(s) for this session only."
        except Exception as exc:
            st.error(f"Quotes file rejected: {exc}")
            session_quotes = quotes

comparison = bm.build_comparison(packages, offers, session_quotes)
summary = bm.summarize(packages, offers, comparison)

# Destination group for offers: linked Travel.pk destination, else offer destination.
dest_map = packages.set_index("travelpk_id")["destination"].to_dict()
offers_view = offers.copy()
offers_view["Destination group"] = [
    dest_map.get(tid) or dest for tid, dest in zip(offers_view["travelpk_id"], offers_view["destination"])
]

with st.sidebar:
    all_dest = sorted(set(offers_view["Destination group"]) | set(comparison["Destination"]))
    sel_dest = st.multiselect("Destination", all_dest)
    all_comp = sorted(offers["competitor"].unique())
    sel_comp = st.multiselect("Competitor", all_comp)
    sel_ev = st.multiselect("Evidence status", list(bm.ALL_EVIDENCE_STATUSES))
    sel_verdict = st.multiselect("Price verdict", sorted(comparison["Price Verdict"].unique()))
    search = st.text_input("Search text", placeholder="e.g. Skardu, Sastaticket")


def apply_offer_filters(df: pd.DataFrame) -> pd.DataFrame:
    out = df
    if sel_dest:
        out = out[out["Destination group"].isin(sel_dest)]
    if sel_comp:
        out = out[out["competitor"].isin(sel_comp)]
    if sel_ev:
        out = out[out["evidence_status"].isin(sel_ev)]
    if search:
        mask = out.astype(str).apply(lambda c: c.str.contains(search, case=False, regex=False)).any(axis=1)
        out = out[mask]
    return out


def apply_comparison_filters(df: pd.DataFrame) -> pd.DataFrame:
    out = df
    if sel_dest:
        out = out[out["Destination"].isin(sel_dest)]
    if sel_comp:
        out = out[out["Competitor"].isin(sel_comp)]
    if sel_ev:
        out = out[out["Evidence Status"].isin(sel_ev)]
    if sel_verdict:
        out = out[out["Price Verdict"].isin(sel_verdict)]
    if search:
        mask = out.astype(str).apply(lambda c: c.str.contains(search, case=False, regex=False)).any(axis=1)
        out = out[mask]
    return out


def pill(status: str) -> str:
    if status in bm.VERIFIED_STATUSES:
        cls = "ok"
    elif status in ("Unconfirmed basis", "Excerpt only"):
        cls = "warn"
    else:
        cls = "bad"
    return f'<span class="pill {cls}">{status}</span>'


# --------------------------------------------------------------------------- #
# Header + KPIs
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <div class="hero">
      <h1>Travel.pk | Competitor Package Price Benchmark</h1>
      <p>Public competitor package prices benchmarked against Travel.pk's package inventory, with evidence status for every figure.</p>
      <div class="meta">Research date: {bm.RESEARCH_DATE} &nbsp;|&nbsp; Prepared for TechAbout management review</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if quotes_note:
    st.info(quotes_note)

if summary["quotes_supplied"] == 0:
    st.warning(
        "**Travel.pk shows \"Tailored quote\" for all 12 packages and publishes no fixed price.** "
        "A \"cheaper or costlier\" verdict therefore cannot be determined from public information. "
        "This dashboard shows competitor prices and evidence quality only; it does not imply a Travel.pk price. "
        "Only the Hunza detail page was individually inspected."
    )

k1, k2, k3, k4 = st.columns(4)
for col, value, label, warn in (
    (k1, summary["packages_reviewed"], "Travel.pk packages reviewed", False),
    (k2, summary["competitor_offers"], "Competitor offers researched", False),
    (k3, summary["verified_competitor_prices"], "Verified competitor prices", False),
    (k4, summary["travelpk_prices_public"], "Travel.pk prices publicly available", True),
):
    col.markdown(
        f'<div class="kpi {"warn" if warn else ""}"><div class="v">{value}</div><div class="l">{label}</div></div>',
        unsafe_allow_html=True,
    )
st.caption(
    f"Verified = competitor price read from an opened page ({summary['verified_inconsistent']} of the "
    f"{summary['verified_competitor_prices']} show an inconsistency on the page itself). "
    f"{summary['unconfirmed_basis']} offer has an unconfirmed price basis and {summary['excerpt_only']} were seen only in search excerpts; "
    "neither group is counted as verified."
)

tabs = st.tabs([
    "Overview", "Package inventory", "Competitor benchmark", "Package detail",
    "Findings & recommendations", "Methodology & sources", "Downloads",
])

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
with tabs[0]:
    st.subheader("Competitor displayed prices")
    include_unverified = st.checkbox(
        "Include unverified prices (excerpt-only and unconfirmed basis)", value=False,
        help="Off by default. Unverified prices are drawn in a different colour when included.",
    )
    chart_df = apply_offer_filters(offers_view)
    chart_df = chart_df[(chart_df["currency"] == "PKR") & chart_df["price_amount"].notna()]
    if not include_unverified:
        chart_df = chart_df[chart_df["evidence_status"].isin(bm.VERIFIED_STATUSES)]
    chart_df = chart_df[chart_df["price_basis"].str.contains("Per person", case=False)]

    if chart_df.empty:
        st.info("No offers match the current filters and chart settings.")
    else:
        chart_df = chart_df.copy()
        chart_df["Offer"] = chart_df["competitor"] + ": " + chart_df["offer_name"].str.slice(0, 55)
        chart_df = chart_df.sort_values("price_amount")
        fig = px.bar(
            chart_df, x="price_amount", y="Offer", orientation="h", color="evidence_status",
            color_discrete_map={
                "Verified": TEAL, "Verified (inconsistent on page)": "#5EC4CC",
                "Unconfirmed basis": "#D97706", "Excerpt only": "#94A3B8",
            },
            hover_data={"price_amount": ":,.0f", "price_basis": True, "duration_text": True,
                        "flights_included": True, "Offer": False},
            labels={"price_amount": "Displayed price (PKR, per person)", "evidence_status": "Evidence status"},
        )
        fig.update_layout(
            height=max(320, 34 * len(chart_df) + 120), margin=dict(l=10, r=10, t=30, b=10),
            plot_bgcolor="#fff", legend_title_text="", yaxis_title="",
            font=dict(color=NAVY),
        )
        fig.update_xaxes(tickformat=",", gridcolor="#E2E8F0")
        st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Per-person PKR prices only. Travel.pk is intentionally not plotted because it has no public price. "
        "Offers differ in duration, hotel tier and flight inclusion (see Competitor benchmark), so bars are not like-for-like. "
        "USD and per-couple prices are excluded rather than converted."
    )

    st.subheader("Evidence quality of competitor offers")
    ev_counts = (
        apply_offer_filters(offers_view)["evidence_status"].value_counts()
        .reindex(list(bm.ALL_EVIDENCE_STATUSES), fill_value=0).reset_index()
    )
    ev_counts.columns = ["Evidence status", "Offers"]
    fig2 = px.bar(ev_counts, x="Evidence status", y="Offers", text="Offers", color_discrete_sequence=[NAVY])
    fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="#fff")
    fig2.update_yaxes(gridcolor="#E2E8F0")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Price verdicts")
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Travel.pk cheaper", summary["cheaper"])
    v2.metric("Travel.pk costlier", summary["costlier"])
    v3.metric("Same price", summary["same"])
    v4.metric("Cannot determine", summary["cannot_determine"])

# --------------------------------------------------------------------------- #
# Package inventory
# --------------------------------------------------------------------------- #
with tabs[1]:
    st.subheader("Travel.pk package inventory")
    inv = packages.copy()
    if sel_dest:
        inv = inv[inv["destination"].isin(sel_dest)]
    if search:
        inv = inv[inv.astype(str).apply(lambda c: c.str.contains(search, case=False, regex=False)).any(axis=1)]
    inv_show = inv.assign(price=bm.NOT_PUBLIC)[[
        "travelpk_id", "package_name", "destination", "category", "typical_duration",
        "listed_components", "pricing_status", "price", "detail_page_inspected", "detail_url",
    ]].rename(columns={
        "travelpk_id": "ID", "package_name": "Package", "destination": "Destination", "category": "Category",
        "typical_duration": "Sample duration", "listed_components": "Components listed",
        "pricing_status": "Pricing shown", "price": "Travel.pk price",
        "detail_page_inspected": "Detail page inspected", "detail_url": "Travel.pk page",
    })
    if inv_show.empty:
        st.info("No packages match the current filters.")
    else:
        st.dataframe(
            inv_show, use_container_width=True, hide_index=True,
            column_config={"Travel.pk page": st.column_config.LinkColumn("Travel.pk page")},
        )
    st.caption(
        "Source: travel.pk/packages, checked 21 October 2026. Detail pages were not inspected individually except Hunza."
    )

# --------------------------------------------------------------------------- #
# Competitor benchmark
# --------------------------------------------------------------------------- #
with tabs[2]:
    st.subheader("Package comparison (one primary competitor offer per Travel.pk package)")
    comp_f = apply_comparison_filters(comparison)

    def _fmt(v, kind):
        if pd.isna(v):
            return "Not calculated"
        return f"{v:,.0f}" if kind == "abs" else f"{v:+.1f}%"

    comp_show = comp_f.assign(**{
        "Absolute Price Difference": comp_f["Absolute Price Difference"].map(lambda v: _fmt(v, "abs")),
        "Percentage Difference": comp_f["Percentage Difference"].map(lambda v: _fmt(v, "pct")),
    })[[
        "No.", "Travel.pk Package", "Destination", "Duration (Travel.pk sample)", "Travel.pk Price", "Competitor",
        "Competitor Package", "Competitor Price", "Competitor Price Basis", "Absolute Price Difference",
        "Percentage Difference", "Price Verdict", "Evidence Status", "Comparability", "Travel.pk Source",
        "Competitor Source", "Price Checked Date",
    ]]
    if comp_show.empty:
        st.info("No rows match the current filters.")
    else:
        st.dataframe(
            comp_show, use_container_width=True, hide_index=True,
            column_config={
                "Travel.pk Source": st.column_config.LinkColumn("Travel.pk Source"),
                "Competitor Source": st.column_config.LinkColumn("Competitor Source"),
            },
        )
    st.caption(
        "\"Not publicly available\" means Travel.pk displays no price; it is never treated as zero. "
        "Competitor figures are displayed prices, not quotes for identical trips."
    )

    st.subheader("All competitor offers researched")
    off_f = apply_offer_filters(offers_view)
    off_show = off_f[[
        "offer_id", "travelpk_id", "competitor", "offer_name", "Destination group", "duration_text", "price_amount",
        "currency", "price_basis", "price_tier", "flights_included", "inclusions", "exclusions", "evidence_status",
        "comparability", "source_type", "source_url", "date_checked", "notes",
    ]].rename(columns={
        "offer_id": "Offer", "travelpk_id": "Linked Travel.pk ID", "competitor": "Competitor",
        "offer_name": "Offer name", "duration_text": "Duration", "price_amount": "Price", "currency": "Currency",
        "price_basis": "Price basis", "price_tier": "Tier / note", "flights_included": "Flights included",
        "inclusions": "Inclusions", "exclusions": "Exclusions", "evidence_status": "Evidence status",
        "comparability": "Comparability", "source_type": "Source type", "source_url": "Source",
        "date_checked": "Date checked", "notes": "Notes",
    })
    if off_show.empty:
        st.info("No offers match the current filters.")
    else:
        st.dataframe(
            off_show, use_container_width=True, hide_index=True,
            column_config={
                "Source": st.column_config.LinkColumn("Source"),
                "Price": st.column_config.NumberColumn("Price", format="%d"),
            },
        )

# --------------------------------------------------------------------------- #
# Package detail
# --------------------------------------------------------------------------- #
with tabs[3]:
    st.subheader("Package detail")
    names = comparison["Travel.pk Package"].tolist()
    choice = st.selectbox("Select a Travel.pk package", names)
    crow = comparison[comparison["Travel.pk Package"] == choice].iloc[0]
    prow = packages[packages["package_name"] == choice].iloc[0]
    pkg_offers = offers[offers["travelpk_id"] == prow["travelpk_id"]]

    left, right = st.columns(2)
    with left:
        st.markdown(
            f"""<div class="card"><h4>Travel.pk</h4>
            <b>{prow['package_name']}</b><br>
            Destination: {prow['destination']}<br>
            Sample duration: {prow['typical_duration']}<br>
            Components listed: {prow['listed_components']}<br>
            Pricing shown: <b>{prow['pricing_status']}</b><br>
            Price: <b>{crow['Travel.pk Price']}</b><br>
            Detail page inspected: {prow['detail_page_inspected']}<br>
            Checked: {prow['date_checked']}</div>""",
            unsafe_allow_html=True,
        )
        st.markdown(f"[Open Travel.pk page]({prow['detail_url']})")
        st.caption(prow["notes"])
    with right:
        if crow["Competitor"] == "None found":
            st.markdown(
                '<div class="card"><h4>Competitor</h4>No comparable competitor offer was found in this research.</div>',
                unsafe_allow_html=True,
            )
        else:
            o = pkg_offers[pkg_offers["is_primary"]].iloc[0]
            st.markdown(
                f"""<div class="card"><h4>Primary competitor offer</h4>
                <b>{o['competitor']}</b>: {o['offer_name']}<br>
                Price: <b>{bm.fmt_money(o['price_amount'], o['currency'])}</b> ({o['price_basis']})<br>
                Tier / note: {o['price_tier']}<br>
                Duration: {o['duration_text']}<br>
                Flights included: {o['flights_included']}<br>
                Inclusions: {o['inclusions']}<br>
                Exclusions: {o['exclusions']}<br>
                Evidence: {pill(o['evidence_status'])} &nbsp; Comparability: <b>{o['comparability']}</b><br>
                Source type: {o['source_type']}<br>
                Checked: {o['date_checked']}</div>""",
                unsafe_allow_html=True,
            )
            st.markdown(f"[Open competitor source]({o['source_url']})")
            st.caption(o["notes"])

    st.markdown("#### Price comparison result")
    if crow["Price Verdict"] == bm.CANNOT_DETERMINE:
        st.warning(f"**Cannot determine.** {crow['Verdict Note']}")
    else:
        st.success(
            f"**{crow['Price Verdict']}.** Difference: {crow['Absolute Price Difference']:+,.0f} "
            f"({crow['Percentage Difference']:+.1f}%). {crow['Verdict Note']}"
        )

    others = pkg_offers[~pkg_offers["is_primary"]]
    if not others.empty:
        st.markdown("#### Other competitor offers researched for this package")
        st.dataframe(
            others[["offer_id", "competitor", "offer_name", "duration_text", "price_amount", "currency",
                    "price_basis", "evidence_status", "source_url"]].rename(columns={
                "offer_id": "Offer", "competitor": "Competitor", "offer_name": "Offer name",
                "duration_text": "Duration", "price_amount": "Price", "currency": "Currency",
                "price_basis": "Price basis", "evidence_status": "Evidence status", "source_url": "Source"}),
            use_container_width=True, hide_index=True,
            column_config={"Source": st.column_config.LinkColumn("Source")},
        )

# --------------------------------------------------------------------------- #
# Findings & recommendations
# --------------------------------------------------------------------------- #
with tabs[4]:
    st.subheader("Findings")
    dom = offers[(offers["evidence_status"].isin(bm.VERIFIED_STATUSES)) & (offers["currency"] == "PKR")]
    st.markdown(
        f"""
- **Travel.pk publishes no fixed package price.** All {summary['packages_reviewed']} packages show "Tailored quote"; the Hunza detail page
  describes itself as a sample itinerary, not a live or pre-priced offer.
- **A cheaper/costlier conclusion is not possible yet.** {summary['travelpk_prices_public']} Travel.pk prices are public, so
  {summary['cannot_determine']} of {summary['packages_reviewed']} verdicts are "Cannot determine" and no price differences are calculated.
- **{summary['verified_competitor_prices']} competitor prices were read from opened pages** (all Sastaticket); {summary['packages_with_verified_primary']} Travel.pk
  packages have a verified primary competitor price: Skardu, Swat, Dubai, Turkey and Maldives.
- **Even verified prices are not like-for-like.** Sastaticket's Dubai package excludes flights; Maldives and Turkey cards do not state flight inclusion;
  prices are "starting from", per person on double sharing.
- **Apricot Tours Hunza (PKR 85,000)** remains unconfirmed: the page does not state per-person vs per-group basis, occupancy, hotel tier or dates, and the
  figure is not a conversion of the US$1,290 price shown beside it.
- **Coverage gaps:** no comparable competitor offer was found for Naran & Kaghan; Fairy Meadows has only a USD, 14-day reference listing; Bookme could not be verified.
"""
    )
    st.subheader("Recommendations for obtaining comparable prices")
    st.markdown(
        """
1. **Obtain internal Travel.pk quotes** under one specification (dates, travellers, double-sharing rooms, hotel star category, flight inclusion, meals) and add them via
   `data/travelpk_quotes.csv` (or upload them in the sidebar to preview). Verdicts will then be calculated automatically.
2. **Match competitor specifications** by requesting or opening itemised competitor quotes for the same dates and hotel tier, starting with Sastaticket's Skardu, Swat, Dubai, Turkey and Maldives packages.
3. **Open competitor detail pages not yet inspected** (Sastaticket Thailand, Malaysia, Azerbaijan; Apricot Tours itinerary tables).
4. **Confirm Apricot Tours' Hunza price basis** with the operator before using it.
5. **Add competitors with public prices** for Naran & Kaghan and Fairy Meadows.
6. **Consider publishing "from" prices with a stated basis** on Travel.pk package pages so future benchmarking can use public data.
7. **Recheck before any pricing decision;** these prices are dynamic and dated 21 October 2026.
"""
    )
    st.caption("Findings describe the researched sample only and do not represent the whole Pakistani travel market.")

# --------------------------------------------------------------------------- #
# Methodology & sources
# --------------------------------------------------------------------------- #
with tabs[5]:
    st.subheader("Methodology and limitations")
    st.markdown(
        f"""
- **Scope:** all 12 packages on Travel.pk's package index (checked {bm.RESEARCH_DATE}). Only the Hunza detail page was opened.
- **Competitors:** Sastaticket and Apricot Tours package pages; TourRadar listings as USD reference only. Bookme was searched but no comparable package pricing could be verified.
- **Evidence status:** *Verified* = price read on an opened competitor page. *Verified (inconsistent on page)* = same, but the page shows conflicting figures.
  *Unconfirmed basis* = price shown but its basis is unclear. *Excerpt only* = seen in a search-result excerpt; page not opened.
- **Calculation:** Absolute difference = Travel.pk − competitor. Percentage = difference ÷ competitor × 100. Within ±{bm.SAME_PRICE_TOLERANCE_PCT:g}% is "Same price".
- **Verdict gate:** a verdict is produced only if a valid Travel.pk quote exists, the competitor price is verified, currency and price basis match, and comparability is Medium or High. Otherwise: "Cannot determine".
- **Currency:** no conversion was applied. USD prices stay in USD and are excluded from PKR charts.
- **Limitations:** prices are dynamic, "starting from" or subject to availability; durations, hotel tiers and flight inclusion differ between offers; no quotes were requested from any company.
- **Excluded sources:** a template-style site on a lovable.app domain and Indian-market itineraries (Pickyourtrail) were excluded as unverifiable or outside the Pakistani market.
"""
    )
    st.subheader("Source register")
    src = (
        offers.groupby(["competitor", "source_url", "source_type", "date_checked"])["offer_id"]
        .apply(lambda s: ", ".join(s)).reset_index()
        .rename(columns={"competitor": "Source", "source_url": "URL", "source_type": "Evidence",
                         "date_checked": "Date checked", "offer_id": "Offers supported"})
    )
    travel_src = pd.DataFrame([
        {"Source": "Travel.pk", "URL": "https://travel.pk/packages/", "Evidence": "Index page (opened)",
         "Date checked": "2026-10-21", "Offers supported": "All 12 Travel.pk packages"},
        {"Source": "Travel.pk", "URL": "https://travel.pk/packages/hunza/", "Evidence": "Detail page (opened)",
         "Date checked": "2026-10-21", "Offers supported": "Hunza sample scope; no fixed price"},
    ])
    st.dataframe(
        pd.concat([travel_src, src], ignore_index=True), use_container_width=True, hide_index=True,
        column_config={"URL": st.column_config.LinkColumn("URL")},
    )

# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #
with tabs[6]:
    st.subheader("Downloads")
    st.caption("Downloads contain the complete, unfiltered datasets shown in the dashboard.")
    verified_offers = offers[offers["evidence_status"].isin(bm.VERIFIED_STATUSES)]
    findings_df = pd.DataFrame(
        [{"Metric": k.replace("_", " ").capitalize(), "Value": ", ".join(v) if isinstance(v, list) else v}
         for k, v in summary.items()]
    )
    report_md = bm.build_report_markdown(packages, offers, comparison)

    c1, c2, c3 = st.columns(3)
    c1.download_button("Package comparison (CSV)", comparison.to_csv(index=False).encode("utf-8"),
                       "package_comparison.csv", "text/csv")
    c2.download_button("Verified competitor prices (CSV)", verified_offers.to_csv(index=False).encode("utf-8"),
                       "verified_competitor_prices.csv", "text/csv")
    c3.download_button("All competitor offers (CSV)", offers.to_csv(index=False).encode("utf-8"),
                       "competitor_offers.csv", "text/csv")
    c4, c5, c6 = st.columns(3)
    c4.download_button("Travel.pk inventory (CSV)", packages.to_csv(index=False).encode("utf-8"),
                       "travelpk_packages.csv", "text/csv")
    c5.download_button("Findings summary (CSV)", findings_df.to_csv(index=False).encode("utf-8"),
                       "findings_summary.csv", "text/csv")
    c6.download_button("Full report (Markdown)", report_md.encode("utf-8"), "REPORT.md", "text/markdown")
    with st.expander("Preview report"):
        st.markdown(report_md)

st.markdown("---")
st.caption(
    f"Research date {bm.RESEARCH_DATE}. Prices are as displayed on the cited pages and may have changed. "
    "This benchmark reflects the researched sample only."
)

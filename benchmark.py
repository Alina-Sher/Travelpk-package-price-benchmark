"""Core logic for the Travel.pk Competitor Package Price Benchmark.

This module has no Streamlit or Plotly dependency so that it can be tested
and reused by the dashboard (app.py), the report generator
(build_dataset.py) and the unit tests.

Key rule: a price verdict (cheaper / costlier / same) is produced ONLY when a
valid Travel.pk quote exists AND a verified, like-for-like competitor price
exists. Missing prices are never treated as zero.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
PACKAGES_CSV = DATA_DIR / "travelpk_packages.csv"
OFFERS_CSV = DATA_DIR / "competitor_offers.csv"
QUOTES_CSV = DATA_DIR / "travelpk_quotes.csv"
COMPARISON_CSV = DATA_DIR / "package_comparison.csv"

RESEARCH_DATE = "21 October 2026"

NOT_PUBLIC = "Not publicly available"
NOT_VERIFIED = "Not verified"
CANNOT_DETERMINE = "Cannot determine"

# Evidence statuses that count as a "verified competitor price".
VERIFIED_STATUSES = ("Verified", "Verified (inconsistent on page)")
ALL_EVIDENCE_STATUSES = VERIFIED_STATUSES + ("Unconfirmed basis", "Excerpt only")

# Comparability levels for which a verdict may be issued (with a valid quote).
VERDICT_ELIGIBLE_COMPARABILITY = ("High", "Medium")

# Prices within this percentage of each other are reported as "Same price".
SAME_PRICE_TOLERANCE_PCT = 1.0

PACKAGE_COLUMNS = [
    "travelpk_id", "package_name", "destination", "category", "typical_duration",
    "listed_components", "pricing_status", "price_pkr", "source_url", "detail_url",
    "detail_page_inspected", "date_checked", "notes",
]
OFFER_COLUMNS = [
    "offer_id", "travelpk_id", "is_primary", "competitor", "offer_name", "destination",
    "duration_text", "nights", "price_amount", "currency", "price_basis", "price_tier",
    "flights_included", "inclusions", "exclusions", "source_url", "source_type",
    "evidence_status", "comparability", "date_checked", "notes",
]
QUOTE_COLUMNS = [
    "travelpk_id", "quote_price", "currency", "price_basis", "travellers",
    "hotel_standard", "travel_dates", "inclusions", "quote_reference", "quote_date",
]


class DataValidationError(ValueError):
    """Raised when a dataset is missing columns or contains invalid values."""


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not Path(path).exists():
        raise DataValidationError(f"Dataset file not found: {path}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise DataValidationError(f"{Path(path).name} is missing columns: {missing}")
    return df[columns].copy()


def _to_number(series: pd.Series) -> pd.Series:
    """Blank -> NaN (never zero); non-numeric text raises."""
    cleaned = series.astype(str).str.strip().replace("", pd.NA)
    return pd.to_numeric(cleaned, errors="raise")


def validate_packages(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df["travelpk_id"].duplicated().any():
        raise DataValidationError("Duplicate travelpk_id values in packages dataset.")
    for col in ("travelpk_id", "package_name", "destination", "pricing_status", "source_url"):
        if (df[col].astype(str).str.strip() == "").any():
            raise DataValidationError(f"Packages: blank value in required column '{col}'.")
    df["price_pkr"] = _to_number(df["price_pkr"])
    if (df["price_pkr"].dropna() <= 0).any():
        raise DataValidationError("Packages: price_pkr must be greater than zero when present.")
    bad = ~df["detail_page_inspected"].isin(["Yes", "No"])
    if bad.any():
        raise DataValidationError("Packages: detail_page_inspected must be 'Yes' or 'No'.")
    return df


def validate_offers(df: pd.DataFrame, valid_package_ids: set[str] | None = None) -> pd.DataFrame:
    df = df.copy()
    if df["offer_id"].duplicated().any():
        raise DataValidationError("Duplicate offer_id values in competitor offers dataset.")
    for col in ("offer_id", "competitor", "offer_name", "source_url", "evidence_status",
                "comparability", "date_checked", "currency"):
        if (df[col].astype(str).str.strip() == "").any():
            raise DataValidationError(f"Offers: blank value in required column '{col}'.")
    unknown = set(df["evidence_status"]) - set(ALL_EVIDENCE_STATUSES)
    if unknown:
        raise DataValidationError(f"Offers: unknown evidence_status values: {sorted(unknown)}")
    if not df["source_url"].str.startswith(("http://", "https://")).all():
        raise DataValidationError("Offers: every source_url must be an absolute http(s) URL.")
    if not df["source_url"].str.contains(r"https?://[^/]+/.+", regex=True).all():
        raise DataValidationError("Offers: source_url must point to a specific page, not a bare homepage.")
    df["price_amount"] = _to_number(df["price_amount"])
    if (df["price_amount"].dropna() <= 0).any():
        raise DataValidationError("Offers: price_amount must be greater than zero when present.")
    df["nights"] = _to_number(df["nights"])
    df["is_primary"] = df["is_primary"].str.strip().str.lower().map({"true": True, "false": False})
    if df["is_primary"].isna().any():
        raise DataValidationError("Offers: is_primary must be True or False.")
    if valid_package_ids is not None:
        linked = df.loc[df["travelpk_id"].str.strip() != "", "travelpk_id"]
        orphan = set(linked) - set(valid_package_ids)
        if orphan:
            raise DataValidationError(f"Offers reference unknown travelpk_id values: {sorted(orphan)}")
    # At most one primary offer per Travel.pk package.
    primaries = df[df["is_primary"] & (df["travelpk_id"].str.strip() != "")]
    if primaries["travelpk_id"].duplicated().any():
        raise DataValidationError("More than one primary offer for a Travel.pk package.")
    # A verified status requires a price.
    if (df["evidence_status"].isin(VERIFIED_STATUSES) & df["price_amount"].isna()).any():
        raise DataValidationError("A 'Verified' offer must have a price_amount.")
    return df


def validate_quotes(df: pd.DataFrame, valid_package_ids: set[str] | None = None) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df["quote_price"] = pd.Series(dtype="float64")
        return df
    df["quote_price"] = _to_number(df["quote_price"])
    if df["quote_price"].isna().any() or (df["quote_price"] <= 0).any():
        raise DataValidationError("Quotes: quote_price must be a number greater than zero.")
    for col in ("travelpk_id", "currency", "price_basis", "quote_date"):
        if (df[col].astype(str).str.strip() == "").any():
            raise DataValidationError(f"Quotes: blank value in required column '{col}'.")
    if df["travelpk_id"].duplicated().any():
        raise DataValidationError("Quotes: only one quote per travelpk_id is supported.")
    if valid_package_ids is not None:
        orphan = set(df["travelpk_id"]) - set(valid_package_ids)
        if orphan:
            raise DataValidationError(f"Quotes reference unknown travelpk_id values: {sorted(orphan)}")
    return df


def load_data(
    packages_csv: Path = PACKAGES_CSV,
    offers_csv: Path = OFFERS_CSV,
    quotes_csv: Path = QUOTES_CSV,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    packages = validate_packages(_read(packages_csv, PACKAGE_COLUMNS))
    ids = set(packages["travelpk_id"])
    offers = validate_offers(_read(offers_csv, OFFER_COLUMNS), ids)
    quotes = validate_quotes(_read(quotes_csv, QUOTE_COLUMNS), ids)
    return packages, offers, quotes


# --------------------------------------------------------------------------- #
# Comparison logic
# --------------------------------------------------------------------------- #
def is_verified(evidence_status: str) -> bool:
    return evidence_status in VERIFIED_STATUSES


def calculate_difference(travelpk_price: float | None, competitor_price: float | None):
    """Return (absolute_difference, percentage_difference) or (None, None).

    Absolute = Travel.pk - competitor. Percentage = abs / competitor * 100.
    Missing or non-positive inputs return (None, None); nothing is ever
    coerced to zero.
    """
    if travelpk_price is None or competitor_price is None:
        return None, None
    if pd.isna(travelpk_price) or pd.isna(competitor_price):
        return None, None
    if travelpk_price <= 0 or competitor_price <= 0:
        return None, None
    diff = float(travelpk_price) - float(competitor_price)
    pct = diff / float(competitor_price) * 100.0
    return diff, pct


def classify(diff: float, pct: float, tolerance_pct: float = SAME_PRICE_TOLERANCE_PCT) -> str:
    if abs(pct) <= tolerance_pct:
        return "Same price"
    return "Travel.pk cheaper" if diff < 0 else "Travel.pk costlier"


def _verdict_for(pkg_row, offer_row, quote_row) -> tuple[str, str, float | None, float | None]:
    """Return (verdict, explanation, abs_diff, pct_diff)."""
    if offer_row is None:
        return CANNOT_DETERMINE, "No comparable competitor offer was found.", None, None
    if quote_row is None:
        return (
            CANNOT_DETERMINE,
            "Travel.pk displays 'Tailored quote' with no public price, and no internal quote has been supplied.",
            None, None,
        )
    if not is_verified(offer_row["evidence_status"]):
        return CANNOT_DETERMINE, "Competitor price is not verified.", None, None
    if offer_row["comparability"] not in VERDICT_ELIGIBLE_COMPARABILITY:
        return CANNOT_DETERMINE, f"Comparability rated '{offer_row['comparability']}'.", None, None
    if str(quote_row["currency"]).strip().upper() != str(offer_row["currency"]).strip().upper():
        return CANNOT_DETERMINE, "Currencies differ and no dated exchange rate was applied.", None, None
    if str(quote_row["price_basis"]).strip().lower() != str(offer_row["price_basis"]).strip().lower():
        return CANNOT_DETERMINE, "Price bases differ (e.g. per person vs per couple); not normalised.", None, None
    diff, pct = calculate_difference(quote_row["quote_price"], offer_row["price_amount"])
    if diff is None:
        return CANNOT_DETERMINE, "Invalid price data.", None, None
    return classify(diff, pct), "Verified competitor price compared with a valid Travel.pk quote.", diff, pct


def build_comparison(
    packages: pd.DataFrame, offers: pd.DataFrame, quotes: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per Travel.pk package, paired with its primary competitor offer."""
    quotes = quotes if quotes is not None else pd.DataFrame(columns=QUOTE_COLUMNS)
    quote_by_id = {r["travelpk_id"]: r for _, r in quotes.iterrows()}
    primary = {
        r["travelpk_id"]: r
        for _, r in offers[offers["is_primary"] & (offers["travelpk_id"].str.strip() != "")].iterrows()
    }
    count_by_id = offers[offers["travelpk_id"].str.strip() != ""].groupby("travelpk_id").size().to_dict()

    rows = []
    for no, (_, pkg) in enumerate(packages.iterrows(), start=1):
        offer = primary.get(pkg["travelpk_id"])
        quote = quote_by_id.get(pkg["travelpk_id"])
        verdict, why, diff, pct = _verdict_for(pkg, offer, quote)

        if quote is not None:
            tp_price = float(quote["quote_price"])
            tp_display = f"{quote['currency']} {tp_price:,.0f} (internal quote)"
        else:
            tp_price = float("nan")
            tp_display = NOT_PUBLIC

        if offer is not None:
            comp_price = offer["price_amount"]
            if pd.isna(comp_price):
                comp_display = NOT_VERIFIED
            else:
                comp_display = f"{offer['currency']} {comp_price:,.0f}"
        else:
            comp_price = float("nan")
            comp_display = NOT_VERIFIED

        rows.append({
            "No.": no,
            "travelpk_id": pkg["travelpk_id"],
            "Travel.pk Package": pkg["package_name"],
            "Destination": pkg["destination"],
            "Category": pkg["category"],
            "Duration (Travel.pk sample)": pkg["typical_duration"],
            "Travel.pk Price Status": pkg["pricing_status"],
            "Travel.pk Price": tp_display,
            "travelpk_price_value": tp_price,
            "Competitor": offer["competitor"] if offer is not None else "None found",
            "Competitor Package": offer["offer_name"] if offer is not None else "No comparable offer found",
            "Competitor Duration": offer["duration_text"] if offer is not None else "",
            "Competitor Price": comp_display,
            "competitor_price_value": comp_price,
            "Competitor Currency": offer["currency"] if offer is not None else "",
            "Competitor Price Basis": offer["price_basis"] if offer is not None else "",
            "Absolute Price Difference": diff if diff is not None else float("nan"),
            "Percentage Difference": pct if pct is not None else float("nan"),
            "Price Verdict": verdict,
            "Verdict Note": why,
            "Evidence Status": offer["evidence_status"] if offer is not None else "No offer found",
            "Comparability": offer["comparability"] if offer is not None else "None",
            "Offers Researched": int(count_by_id.get(pkg["travelpk_id"], 0)),
            "Travel.pk Source": pkg["detail_url"],
            "Competitor Source": offer["source_url"] if offer is not None else "",
            "Price Checked Date": pkg["date_checked"],
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Summary metrics (single source for dashboard + report)
# --------------------------------------------------------------------------- #
def summarize(packages: pd.DataFrame, offers: pd.DataFrame, comparison: pd.DataFrame) -> dict:
    verified_mask = offers["evidence_status"].isin(VERIFIED_STATUSES)
    return {
        "packages_reviewed": int(len(packages)),
        "detail_pages_inspected": int((packages["detail_page_inspected"] == "Yes").sum()),
        "travelpk_prices_public": int(packages["price_pkr"].notna().sum()),
        "competitor_offers": int(len(offers)),
        "competitor_names": sorted(offers["competitor"].unique().tolist()),
        "verified_competitor_prices": int(verified_mask.sum()),
        "verified_inconsistent": int((offers["evidence_status"] == "Verified (inconsistent on page)").sum()),
        "unconfirmed_basis": int((offers["evidence_status"] == "Unconfirmed basis").sum()),
        "excerpt_only": int((offers["evidence_status"] == "Excerpt only").sum()),
        "packages_with_verified_primary": int(
            comparison["Evidence Status"].isin(VERIFIED_STATUSES).sum()
        ),
        "packages_without_primary": int((comparison["Competitor"] == "None found").sum()),
        "cheaper": int((comparison["Price Verdict"] == "Travel.pk cheaper").sum()),
        "costlier": int((comparison["Price Verdict"] == "Travel.pk costlier").sum()),
        "same": int((comparison["Price Verdict"] == "Same price").sum()),
        "cannot_determine": int((comparison["Price Verdict"] == CANNOT_DETERMINE).sum()),
        "quotes_supplied": int(comparison["travelpk_price_value"].notna().sum()),
    }


def fmt_money(amount, currency: str) -> str:
    if amount is None or pd.isna(amount):
        return NOT_VERIFIED
    return f"{currency} {float(amount):,.0f}"


# --------------------------------------------------------------------------- #
# Report generation (Markdown) - generated from the same data as the dashboard
# --------------------------------------------------------------------------- #
def _md_link(text: str, url: str) -> str:
    return f"[{text}]({url})" if url else text


def build_report_markdown(
    packages: pd.DataFrame, offers: pd.DataFrame, comparison: pd.DataFrame
) -> str:
    s = summarize(packages, offers, comparison)
    L: list[str] = []
    add = L.append

    add("# Travel.pk | Competitor Package Price Benchmark")
    add(f"*Research date: {RESEARCH_DATE}. Prepared for TechAbout management review.*\n")

    # 1. Executive summary
    add("## 1. Executive summary\n")
    add(
        f"Travel.pk's package index lists **{s['packages_reviewed']} packages**, and every one is shown as "
        f"**\"Tailored quote\"** with no public price. Only {s['detail_pages_inspected']} detail page (Hunza) was "
        "individually inspected; it confirms the page is a sample itinerary, \"not a live or pre-priced offer\". "
        f"**{s['travelpk_prices_public']} Travel.pk prices are publicly available**, so a genuine "
        "\"cheaper or costlier\" verdict **cannot be determined** for any package from public information."
    )
    add(
        f"\nThe research recorded **{s['competitor_offers']} competitor offers** across "
        f"{', '.join(s['competitor_names'])}. Of these, **{s['verified_competitor_prices']}** carry a competitor price read "
        f"directly from an opened page ({s['verified_inconsistent']} of them contain an inconsistency on the page itself); "
        f"{s['unconfirmed_basis']} is an unconfirmed-basis price and {s['excerpt_only']} were seen only in search-result excerpts "
        "and are not counted as verified."
    )
    add(
        f"\n| Metric | Count |\n|---|---|\n"
        f"| Travel.pk packages reviewed | {s['packages_reviewed']} |\n"
        f"| Travel.pk prices publicly available | {s['travelpk_prices_public']} |\n"
        f"| Competitor offers researched | {s['competitor_offers']} |\n"
        f"| Verified competitor prices | {s['verified_competitor_prices']} |\n"
        f"| Travel.pk packages with a verified primary competitor price | {s['packages_with_verified_primary']} |\n"
        f"| Travel.pk packages with no competitor offer found | {s['packages_without_primary']} |\n"
        f"| Verdict: Travel.pk cheaper / costlier / same | {s['cheaper']} / {s['costlier']} / {s['same']} |\n"
        f"| Verdict: cannot determine | {s['cannot_determine']} |\n"
    )
    add(
        "These findings describe the researched sample only; they do not represent the whole Pakistani travel market."
    )

    # 2. Inventory
    add("\n## 2. Travel.pk package inventory\n")
    add("| ID | Package | Destination | Sample duration | Components listed | Pricing shown | Detail page inspected |")
    add("|---|---|---|---|---|---|---|")
    for _, p in packages.iterrows():
        add(
            f"| {p['travelpk_id']} | {_md_link(p['package_name'], p['detail_url'])} | {p['destination']} | "
            f"{p['typical_duration']} | {p['listed_components']} | {p['pricing_status']} | {p['detail_page_inspected']} |"
        )
    add(f"\nSource: {_md_link('travel.pk/packages', 'https://travel.pk/packages/')}, checked {RESEARCH_DATE}.")

    # 3. Competitor benchmark
    add("\n## 3. Competitor package price benchmark\n")
    add("All displayed competitor prices, with evidence status. *Verified* = read from an opened page. "
        "*Excerpt only* and *Unconfirmed basis* are **not** verified.\n")
    add("| Offer | Competitor | Offer name | Linked Travel.pk package | Duration | Price | Basis | Evidence status | Comparability |")
    add("|---|---|---|---|---|---|---|---|---|")
    for _, o in offers.iterrows():
        link = o["travelpk_id"] if o["travelpk_id"] else "None"
        add(
            f"| {o['offer_id']} | {o['competitor']} | {_md_link(o['offer_name'], o['source_url'])} | {link} | "
            f"{o['duration_text']} | {fmt_money(o['price_amount'], o['currency'])} | {o['price_basis']} | "
            f"{o['evidence_status']} | {o['comparability']} |"
        )

    # 4. Public pricing availability
    add("\n## 4. Public pricing availability findings\n")
    add("- **Travel.pk:** all 12 packages show \"Tailored quote\"; the Hunza detail page states there is no fixed price and that it is "
        "a sample planning route rather than a live offer. Price comparison therefore depends on internal quotes.")
    add("- **Sastaticket:** publishes \"starting from\" prices per person on double-sharing for many packages, mostly without "
        "stating flight inclusion on the card.")
    add("- **Apricot Tours:** publishes PKR and USD prices; the basis of the PKR figure for Hunza is not stated (see section 5).")
    add("- **Bookme:** no comparable package pricing was found in the research; it is recorded as not verified, not as absent.")
    add("- **No competitor offer found** for: " + (
        ", ".join(comparison.loc[comparison["Competitor"] == "None found", "Travel.pk Package"]) or "none") + ".")

    # 5. Comparability
    add("\n## 5. Price comparability and evidence status\n")
    add("| Travel.pk package | Primary competitor offer | Competitor price | Evidence status | Comparability | Price verdict |")
    add("|---|---|---|---|---|---|")
    for _, r in comparison.iterrows():
        add(
            f"| {r['Travel.pk Package']} | {r['Competitor']}: {r['Competitor Package']} | {r['Competitor Price']} | "
            f"{r['Evidence Status']} | {r['Comparability']} | {r['Price Verdict']} |"
        )
    add("\n**Apricot Tours Hunza price (rechecked).** The detail page lists PKR 85,000 and US$1,290 (US$1,390 in other seasons). "
        "PKR 85,000 is identical across four seasonal rows and is not a conversion of the USD figure. The page separates inclusions "
        "for foreign and for Pakistani travellers but does not say whether PKR 85,000 is per person or per group, nor the room occupancy, "
        "hotel category or dates it applies to. It is therefore recorded as *Unconfirmed basis* and is not used as a confirmed price.")
    add("\n**Key scope differences.** Dubai (Sastaticket) excludes flights and visa while Travel.pk lists a flight component; "
        "Maldives and several international listings do not state flight inclusion; durations of Thailand, Malaysia and Azerbaijan "
        "teasers are shorter than Travel.pk's samples; TourRadar listings are in USD and cover 13–14 day itineraries.")

    # 6. Method
    add("\n## 6. Research methodology and limitations\n")
    add("- Travel.pk's package index and the Hunza detail page were opened and read. The other 11 detail pages were **not** individually inspected.")
    add("- Competitor pages were located by web search and opened where noted in the \"Source type\" column of the dataset. "
        "Items marked *Search excerpt (page not opened)* were taken from search-result excerpts only.")
    add("- No price was estimated, interpolated or converted. USD prices are shown in USD; no exchange rate was applied.")
    add("- A verdict is produced only when a valid Travel.pk quote exists, the competitor price is verified, currency and price basis "
        "match, and comparability is Medium or High. Differences within ±1% are reported as \"Same price\". "
        "Absolute difference = Travel.pk − competitor; percentage = difference ÷ competitor × 100.")
    add("- Competitor prices are dynamic, \"starting from\" or subject to availability and may have changed after the research date.")
    add("- Bookme could not be verified; TourRadar listings were seen only as excerpts and the operator was not captured.")
    add("- A search result for a site presenting itself as 'Best Tour Operator 2024' on a lovable.app domain, and Indian-market "
        "(Pickyourtrail) itineraries, were excluded as unverifiable or outside the Pakistani market.")

    # 7. Recommendations
    add("\n## 7. Recommendations for obtaining comparable prices\n")
    add("1. **Obtain internal Travel.pk quotes** for each package under one specification: dates, number of travellers, double-sharing rooms, "
        "hotel star category, flight inclusion, meals. Enter them in `data/travelpk_quotes.csv`; the dashboard and report then compute verdicts automatically.")
    add("2. **Match competitor specifications to those quotes**: request or open itemised competitor quotes for the same dates and hotel tier, "
        "starting with Sastaticket (Skardu, Swat, Dubai, Turkey, Maldives) where verified prices exist.")
    add("3. **Open the competitor detail pages** not yet inspected (Sastaticket Thailand, Malaysia and Azerbaijan; Apricot Tours Skardu/Hunza/Gilgit-Baltistan tables).")
    add("4. **Confirm the Apricot Tours Hunza basis** (per person or per group, occupancy, hotel tier, dates) directly with the operator before using PKR 85,000.")
    add("5. **Add competitors with public package pricing** for Naran & Kaghan and Fairy Meadows, where no comparable offer was found.")
    add("6. **Consider publishing 'from' prices** with stated basis on Travel.pk package pages, which would make future benchmarking possible from public data.")
    add("7. **Recheck seasonally** and within days of any pricing decision, since prices are dynamic.")

    # 8. Sources
    add("\n## 8. Source register\n")
    add("| Source | URL | Used for | Date checked | Evidence note |")
    add("|---|---|---|---|---|")
    add(f"| Travel.pk packages index | https://travel.pk/packages/ | All 12 packages; 'Tailored quote' status | {RESEARCH_DATE} | Page opened |")
    add(f"| Travel.pk Hunza detail | https://travel.pk/packages/hunza/ | Hunza sample scope, no fixed price | {RESEARCH_DATE} | Page opened |")
    seen = set()
    for _, o in offers.iterrows():
        if o["source_url"] in seen:
            continue
        seen.add(o["source_url"])
        used = ", ".join(offers.loc[offers["source_url"] == o["source_url"], "offer_id"])
        add(f"| {o['competitor']} | {o['source_url']} | {used} | {o['date_checked']} | {o['source_type']} |")
    add("\n*Where an offer's notes mention a detail-page link that was not opened, that link is listed in the dataset notes only.*")
    return "\n".join(L) + "\n"

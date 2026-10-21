"""Tests for benchmark.py. Run from the project root:

    python -m unittest discover -s tests -v

Synthetic quotes used below exist ONLY inside these tests to exercise the
verdict logic; they are never written to the data files.
"""
import math
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import benchmark as bm  # noqa: E402


class TestDatasets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packages, cls.offers, cls.quotes = bm.load_data()
        cls.comparison = bm.build_comparison(cls.packages, cls.offers, cls.quotes)

    def test_twelve_travelpk_packages(self):
        self.assertEqual(len(self.packages), 12)
        self.assertEqual(self.packages["travelpk_id"].nunique(), 12)

    def test_all_travelpk_prices_missing_not_zero(self):
        self.assertTrue(self.packages["price_pkr"].isna().all())
        self.assertTrue((self.packages["pricing_status"] == "Tailored quote").all())

    def test_only_hunza_detail_page_inspected(self):
        inspected = self.packages.loc[self.packages["detail_page_inspected"] == "Yes", "package_name"]
        self.assertEqual(list(inspected), ["Hunza Valley Tour Package"])

    def test_default_comparison_has_no_verdicts_or_differences(self):
        self.assertTrue((self.comparison["Price Verdict"] == bm.CANNOT_DETERMINE).all())
        self.assertTrue(self.comparison["Absolute Price Difference"].isna().all())
        self.assertTrue(self.comparison["Percentage Difference"].isna().all())
        self.assertTrue((self.comparison["Travel.pk Price"] == bm.NOT_PUBLIC).all())

    def test_comparison_has_one_row_per_package(self):
        self.assertEqual(len(self.comparison), 12)
        self.assertEqual(self.comparison["travelpk_id"].nunique(), 12)

    def test_unconfirmed_apricot_hunza_price_not_verified(self):
        row = self.offers[self.offers["offer_id"] == "CO01"].iloc[0]
        self.assertEqual(row["price_amount"], 85000)
        self.assertEqual(row["evidence_status"], "Unconfirmed basis")
        self.assertFalse(bm.is_verified(row["evidence_status"]))

    def test_excerpt_only_offers_are_not_verified(self):
        excerpts = self.offers[self.offers["evidence_status"] == "Excerpt only"]
        self.assertGreater(len(excerpts), 0)
        self.assertFalse(excerpts["evidence_status"].map(bm.is_verified).any())

    def test_summary_counts_match_data(self):
        s = bm.summarize(self.packages, self.offers, self.comparison)
        self.assertEqual(s["packages_reviewed"], 12)
        self.assertEqual(s["travelpk_prices_public"], 0)
        self.assertEqual(s["competitor_offers"], len(self.offers))
        verified = self.offers["evidence_status"].isin(bm.VERIFIED_STATUSES).sum()
        self.assertEqual(s["verified_competitor_prices"], verified)
        self.assertEqual(s["cheaper"] + s["costlier"] + s["same"], 0)
        self.assertEqual(s["cannot_determine"], 12)

    def test_saved_comparison_csv_matches_regeneration(self):
        saved = pd.read_csv(bm.COMPARISON_CSV)
        self.assertEqual(len(saved), len(self.comparison))
        self.assertEqual(list(saved["Travel.pk Package"]), list(self.comparison["Travel.pk Package"]))
        self.assertEqual(list(saved["Price Verdict"]), list(self.comparison["Price Verdict"]))

    def test_report_agrees_with_summary(self):
        report = bm.build_report_markdown(self.packages, self.offers, self.comparison)
        s = bm.summarize(self.packages, self.offers, self.comparison)
        self.assertIn(f"**{s['packages_reviewed']} packages**", report)
        self.assertIn(f"**{s['competitor_offers']} competitor offers**", report)
        self.assertIn("Tailored quote", report)
        self.assertIn("cannot be determined", report)

    def test_dashboard_static_claims_match_data(self):
        """app.py's findings text names these facts explicitly; fail if the data drifts."""
        verified = self.offers[self.offers["evidence_status"].isin(bm.VERIFIED_STATUSES)]
        self.assertEqual(set(verified["competitor"]), {"Sastaticket"})
        verified_primary = self.comparison[self.comparison["Evidence Status"].isin(bm.VERIFIED_STATUSES)]
        self.assertEqual(
            set(verified_primary["Destination"]),
            {"Skardu", "Swat", "Dubai", "Turkey", "Maldives"},
        )
        self.assertEqual(list(self.comparison.loc[self.comparison["Competitor"] == "None found", "Destination"]),
                         ["Naran & Kaghan"])

    def test_all_source_urls_are_specific_pages(self):
        for url in self.offers["source_url"]:
            self.assertRegex(url, r"^https?://[^/]+/.+")
        for url in self.packages["detail_url"]:
            self.assertTrue(url.startswith("https://travel.pk/packages/"))


class TestCalculations(unittest.TestCase):
    def test_difference_and_percentage(self):
        diff, pct = bm.calculate_difference(90000, 100000)
        self.assertEqual(diff, -10000)
        self.assertAlmostEqual(pct, -10.0)
        diff, pct = bm.calculate_difference(125000, 100000)
        self.assertEqual(diff, 25000)
        self.assertAlmostEqual(pct, 25.0)

    def test_missing_or_invalid_prices_return_none(self):
        for a, b in [(None, 100), (100, None), (float("nan"), 100), (100, float("nan")), (0, 100), (100, 0), (-5, 100)]:
            self.assertEqual(bm.calculate_difference(a, b), (None, None))

    def test_classification_and_tolerance(self):
        self.assertEqual(bm.classify(-10000, -10.0), "Travel.pk cheaper")
        self.assertEqual(bm.classify(25000, 25.0), "Travel.pk costlier")
        self.assertEqual(bm.classify(500, 0.5), "Same price")
        self.assertEqual(bm.classify(0, 0.0), "Same price")


class TestVerdictLogic(unittest.TestCase):
    """Synthetic quotes (test-only) to prove verdict rules."""

    @classmethod
    def setUpClass(cls):
        cls.packages, cls.offers, _ = bm.load_data()

    def _quote(self, tid, price, currency="PKR", basis="Per person, double sharing"):
        return pd.DataFrame([{
            "travelpk_id": tid, "quote_price": float(price), "currency": currency, "price_basis": basis,
            "travellers": "2", "hotel_standard": "", "travel_dates": "", "inclusions": "",
            "quote_reference": "TEST", "quote_date": "2026-10-21",
        }])

    def _row(self, comparison, tid):
        return comparison[comparison["travelpk_id"] == tid].iloc[0]

    def test_verified_comparable_quote_gives_verdict(self):
        # TP04 Swat primary offer: Sastaticket PKR 97,000, Verified, Medium, per person double sharing
        for price, expected in [(90000, "Travel.pk cheaper"), (110000, "Travel.pk costlier"), (97000, "Same price")]:
            comp = bm.build_comparison(self.packages, self.offers, self._quote("TP04", price))
            row = self._row(comp, "TP04")
            self.assertEqual(row["Price Verdict"], expected)
            self.assertAlmostEqual(row["Absolute Price Difference"], price - 97000)
            self.assertAlmostEqual(row["Percentage Difference"], (price - 97000) / 97000 * 100)

    def test_unverified_competitor_price_blocks_verdict(self):
        # TP09 Thailand primary offer is 'Excerpt only'
        comp = bm.build_comparison(self.packages, self.offers, self._quote("TP09", 100000))
        row = self._row(comp, "TP09")
        self.assertEqual(row["Price Verdict"], bm.CANNOT_DETERMINE)
        self.assertTrue(math.isnan(row["Absolute Price Difference"]))

    def test_low_comparability_blocks_verdict(self):
        # TP07 Dubai primary offer is Verified but comparability Low (flights excluded)
        comp = bm.build_comparison(self.packages, self.offers, self._quote("TP07", 100000))
        self.assertEqual(self._row(comp, "TP07")["Price Verdict"], bm.CANNOT_DETERMINE)

    def test_currency_mismatch_blocks_verdict(self):
        comp = bm.build_comparison(self.packages, self.offers, self._quote("TP04", 400, currency="USD"))
        self.assertEqual(self._row(comp, "TP04")["Price Verdict"], bm.CANNOT_DETERMINE)

    def test_basis_mismatch_blocks_verdict(self):
        comp = bm.build_comparison(self.packages, self.offers, self._quote("TP04", 90000, basis="Per couple"))
        self.assertEqual(self._row(comp, "TP04")["Price Verdict"], bm.CANNOT_DETERMINE)

    def test_package_without_offer_cannot_be_determined(self):
        comp = bm.build_comparison(self.packages, self.offers, self._quote("TP03", 50000))
        row = self._row(comp, "TP03")
        self.assertEqual(row["Competitor"], "None found")
        self.assertEqual(row["Price Verdict"], bm.CANNOT_DETERMINE)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.packages, self.offers, _ = bm.load_data()

    def test_missing_column_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.csv"
            p.write_text("travelpk_id,package_name\nTP01,x\n", encoding="utf-8")
            with self.assertRaises(bm.DataValidationError):
                bm._read(p, bm.PACKAGE_COLUMNS)

    def test_zero_price_rejected(self):
        raw = self.offers.copy()
        raw["price_amount"] = raw["price_amount"].astype(object)
        raw["is_primary"] = raw["is_primary"].map({True: "True", False: "False"})
        raw["nights"] = ""
        raw.loc[0, "price_amount"] = "0"
        with self.assertRaises(bm.DataValidationError):
            bm.validate_offers(raw.fillna("").astype(str))

    def test_bare_homepage_url_rejected(self):
        raw = self.offers.copy()
        raw["price_amount"] = raw["price_amount"].fillna("").astype(str)
        raw["nights"] = ""
        raw["is_primary"] = raw["is_primary"].map({True: "True", False: "False"})
        raw.loc[0, "source_url"] = "https://www.apricottours.pk"
        with self.assertRaises(bm.DataValidationError):
            bm.validate_offers(raw.astype(str))

    def test_unknown_package_reference_rejected(self):
        raw = self.offers.copy()
        raw["price_amount"] = raw["price_amount"].fillna("").astype(str)
        raw["nights"] = ""
        raw["is_primary"] = raw["is_primary"].map({True: "True", False: "False"})
        raw.loc[0, "travelpk_id"] = "TP99"
        with self.assertRaises(bm.DataValidationError):
            bm.validate_offers(raw.astype(str), set(self.packages["travelpk_id"]))

    def test_empty_quotes_file_is_valid(self):
        empty = pd.DataFrame(columns=bm.QUOTE_COLUMNS)
        self.assertTrue(bm.validate_quotes(empty).empty)


if __name__ == "__main__":
    unittest.main()

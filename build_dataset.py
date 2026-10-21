"""Rebuild derived files from the source CSVs.

Run from the project root:   python build_dataset.py

Reads   data/travelpk_packages.csv, data/competitor_offers.csv, data/travelpk_quotes.csv
Writes  data/package_comparison.csv  and  REPORT.md
"""
from benchmark import (
    COMPARISON_CSV, DATA_DIR, build_comparison, build_report_markdown, load_data, summarize,
)


def main() -> None:
    packages, offers, quotes = load_data()
    comparison = build_comparison(packages, offers, quotes)
    comparison.to_csv(COMPARISON_CSV, index=False)
    report = build_report_markdown(packages, offers, comparison)
    (DATA_DIR.parent / "REPORT.md").write_text(report, encoding="utf-8")
    s = summarize(packages, offers, comparison)
    print(f"Wrote {COMPARISON_CSV.name} ({len(comparison)} rows) and REPORT.md")
    for key, value in s.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()

import argparse
import os
import sys
from typing import Dict
import pandas as pd

from .scraper import UniversalScraper
from .crawler import WebCrawler
from .dataset import DatasetExporter


def parse_field_mapping(fields_str: str) -> Dict[str, str]:
    """Parse comma-separated field mappings: title=h2,price=.price,link=a@href"""
    mapping = {}
    parts = fields_str.split(",")
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            mapping[k.strip()] = v.strip()
    return mapping


def main():
    parser = argparse.ArgumentParser(
        prog="omniscrape",
        description="OmniScrape - Universal Intelligent Web Scraper & Dataset Builder. Converts any website into clean CSV datasets.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Target URL to scrape, or path to a .txt file containing URLs (one per line).",
    )
    parser.add_argument(
        "-o", "--output",
        default="dataset.csv",
        help="Output CSV file path (default: dataset.csv).",
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["auto", "cards", "tables", "json_ld", "article", "selectors"],
        default="auto",
        help="Scraping mode: auto (smart detector), cards (product/card items), tables (HTML tables), json_ld (schema.org), article (NLP text), selectors (custom CSS).",
    )
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=1,
        help="Number of pagination pages to crawl (default: 1).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Polite delay between requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--item",
        help="Container CSS selector for 'selectors' mode (e.g. '.product-card').",
    )
    parser.add_argument(
        "--fields",
        help="Fields mapping for 'selectors' mode (e.g. 'title=h3,price=.price,link=a@href').",
    )
    parser.add_argument(
        "--proxy",
        help="HTTP/HTTPS proxy URL (e.g. 'http://proxy.example.com:8080').",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json", "jsonl"],
        default="csv",
        help="Output format: csv, json, or jsonl (default: csv).",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable automatic record deduplication.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the interactive Web UI dashboard on localhost.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the Web UI (default: 8080).",
    )

    args = parser.parse_args()

    if args.web:
        from .web_server import run_server
        run_server(port=args.port)
        return

    if not args.target:
        parser.print_help()
        print("\nTip: Run with --web to launch the interactive browser interface, or pass a URL to scrape.")
        sys.exit(1)

    print("=" * 65)
    print(" 🚀 OmniScrape - Universal Dataset Builder")
    print("=" * 65)

    scraper = UniversalScraper(delay=args.delay, proxy=args.proxy)
    crawler = WebCrawler(scraper=scraper)
    exporter = DatasetExporter(deduplicate=not args.no_dedup)

    # Check if target is a file of URLs
    if os.path.isfile(args.target):
        with open(args.target, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"[*] Found {len(urls)} URLs in batch file: {args.target}")
        df = crawler.batch_scrape(urls, mode=args.mode, output_csv=args.output)
        print(f"\n[✓] Batch scraping complete! Saved to {args.output}")
        return

    # Single URL or Pagination
    url = args.target
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    fields_map = parse_field_mapping(args.fields) if args.fields else None

    if args.pages > 1:
        print(f"[*] Target: {url}")
        print(f"[*] Mode: {args.mode} | Crawl depth: {args.pages} pages")
        records = crawler.crawl_pagination(
            start_url=url,
            max_pages=args.pages,
            mode=args.mode,
            item_selector=args.item,
            fields=fields_map,
        )
    else:
        print(f"[*] Target: {url}")
        print(f"[*] Mode: {args.mode}")
        strategy, records = scraper.scrape(
            url=url,
            mode=args.mode,
            item_selector=args.item,
            fields=fields_map,
        )
        print(f"[*] Extraction strategy used: '{strategy}'")

    if not records:
        print("\n[!] No records could be extracted from this page.")
        sys.exit(1)

    print(f"[*] Raw records extracted: {len(records)}")

    # Export
    out_path = args.output
    if args.format == "csv":
        if not out_path.endswith(".csv"):
            out_path += ".csv"
        saved = exporter.save_csv(records, out_path, source_url=url)
    elif args.format == "json":
        if not out_path.endswith(".json"):
            out_path += ".json"
        saved = exporter.save_json(records, out_path, source_url=url, jsonl=False)
    else:
        if not out_path.endswith(".jsonl"):
            out_path += ".jsonl"
        saved = exporter.save_json(records, out_path, source_url=url, jsonl=True)

    df = exporter.to_dataframe(exporter.process_records(records, source_url=url))
    summary = exporter.dataset_summary(df)

    print("\n" + "=" * 65)
    print(" ✅ Dataset Successfully Created!")
    print("=" * 65)
    print(f"  • File saved to   : {saved}")
    print(f"  • Total Rows      : {summary['total_rows']}")
    print(f"  • Total Columns   : {summary['total_columns']}")
    print(f"  • Column Names    : {', '.join(summary['columns'][:8])}{'...' if len(summary['columns']) > 8 else ''}")
    print("=" * 65)

    print("\nPreview of First 3 Records:")
    pd.set_option("display.max_columns", 6)
    pd.set_option("display.width", 1000)
    print(df.head(3))
    print("\n")


if __name__ == "__main__":
    main()

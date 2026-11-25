import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import pandas as pd

from .scraper import UniversalScraper
from .dataset import DatasetExporter


class WebCrawler:
    """
    Crawls multiple pages or follows pagination to build comprehensive datasets.
    """

    NEXT_PAGE_TEXT_REGEX = re.compile(
        r"^(next|next\s*page|older|more|›|»|>|\d+)$",
        re.IGNORECASE,
    )

    def __init__(self, scraper: Optional[UniversalScraper] = None):
        self.scraper = scraper or UniversalScraper()

    def find_next_page(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Intelligently detects the next page URL via HTML signals or URL heuristics."""
        # 1. Rel='next' attribute
        rel_next = soup.find("a", rel=lambda r: r and "next" in r.lower()) or soup.find("link", rel=lambda r: r and "next" in r.lower())
        if rel_next and rel_next.get("href"):
            return urljoin(current_url, rel_next["href"])

        # 2. Text heuristics inside <a> tags
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip().lower()
            aria_label = (a.get("aria-label") or "").strip().lower()
            title = (a.get("title") or "").strip().lower()

            if any(self.NEXT_PAGE_TEXT_REGEX.match(t) for t in [text, aria_label, title]):
                href = a["href"].strip()
                if not href.startswith("javascript:") and not href.startswith("#"):
                    full_url = urljoin(current_url, href)
                    if full_url != current_url:
                        return full_url

        # 3. URL Query Parameter heuristic (?page=X or &p=X)
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        for param in ["page", "p", "pg", "page_num", "paged"]:
            if param in query and query[param][0].isdigit():
                next_val = int(query[param][0]) + 1
                query[param] = [str(next_val)]
                new_query = urlencode(query, doseq=True)
                new_parsed = parsed._replace(query=new_query)
                return urlunparse(new_parsed)

        return None

    def crawl_pagination(
        self,
        start_url: str,
        max_pages: int = 5,
        mode: str = "auto",
        item_selector: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Follow pagination links starting from start_url up to max_pages.
        """
        all_records: List[Dict[str, Any]] = []
        visited: Set[str] = set()
        current_url: Optional[str] = start_url
        page_num = 1

        while current_url and page_num <= max_pages:
            if current_url in visited:
                break
            visited.add(current_url)

            print(f"[*] Crawling page {page_num}/{max_pages}: {current_url}")
            try:
                html = self.scraper.fetch(current_url)
                extractor = self.scraper.scrape.__globals__["SmartExtractor"](base_url=current_url)
                soup = extractor.parse_soup(html)

                strategy, records = self.scraper.scrape(
                    url=current_url,
                    mode=mode,
                    item_selector=item_selector,
                    fields=fields,
                )
                print(f"    -> Extracted {len(records)} records using '{strategy}' strategy.")
                for r in records:
                    r["_crawled_page"] = page_num
                all_records.extend(records)

                # Find next URL
                current_url = self.find_next_page(soup, current_url)
                if not current_url:
                    print("    -> No next page link detected. Crawl complete.")
                    break

                page_num += 1
            except Exception as e:
                print(f"    [!] Error crawling {current_url}: {e}")
                break

        return all_records

    def batch_scrape(
        self,
        urls: List[str],
        mode: str = "auto",
        output_csv: Optional[str] = None,
    ) -> pd.DataFrame:
        """Scrape a list of URLs and aggregate all results into one unified dataset."""
        all_records: List[Dict[str, Any]] = []
        total = len(urls)

        for idx, url in enumerate(urls, 1):
            print(f"[*] [{idx}/{total}] Scraping: {url}")
            try:
                strategy, records = self.scraper.scrape(url, mode=mode)
                print(f"    -> {len(records)} records ({strategy})")
                all_records.extend(records)
            except Exception as e:
                print(f"    [!] Failed to scrape {url}: {e}")

        exporter = DatasetExporter()
        processed = exporter.process_records(all_records)
        df = exporter.to_dataframe(processed)

        if output_csv:
            exporter.save_csv(all_records, output_csv)
            print(f"[✓] Saved master dataset to: {output_csv}")

        return df

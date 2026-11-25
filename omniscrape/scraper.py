import random
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

from .extractor import SmartExtractor
from .dataset import DatasetExporter


class UniversalScraper:
    """
    Universal Web Scraper engineered to scrape any website reliably
    and convert the harvested data into clean, dataset-grade CSV files.
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    ]

    def __init__(
        self,
        delay: float = 1.0,
        timeout: int = 20,
        retries: int = 3,
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        self.delay = delay
        self.timeout = timeout
        self.proxy = proxy
        self.verify_ssl = verify_ssl
        self.session = requests.Session()

        # Configure retries with exponential backoff
        retry_strategy = Retry(
            total=retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        self.custom_headers = custom_headers or {}
        self.last_request_time = 0.0
        self.last_telemetry: Dict[str, Any] = {}

    def _get_headers(self) -> Dict[str, str]:
        """Generate realistic browser headers to prevent anti-bot blocks."""
        ua = random.choice(self.USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        headers.update(self.custom_headers)
        return headers

    def fetch(self, url: str) -> str:
        """Fetch HTML content from a URL with polite rate limiting."""
        # Rate limiting delay
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        headers = self._get_headers()
        try:
            t0 = time.time()
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            latency_ms = round((time.time() - t0) * 1000, 1)
            self.last_request_time = time.time()
            response.raise_for_status()

            # Ensure proper encoding
            if response.encoding is None or response.encoding == "ISO-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"

            html = response.text
            self.last_telemetry = {
                "status_code": response.status_code,
                "final_url": response.url,
                "latency_ms": latency_ms,
                "size_kb": round(len(response.content) / 1024, 1),
                "content_type": response.headers.get("Content-Type", "").split(";")[0],
            }
            return html
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch {url}: {e}")

    def scrape(
        self,
        url: str,
        mode: str = "auto",
        item_selector: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Scrape a given URL using the specified mode:
        - 'auto': Smart auto-detection (JSON-LD -> Cards -> Tables -> Article)
        - 'cards': Repeating structured item cards (products, listings)
        - 'json_ld': Schema.org structured data
        - 'tables': HTML tables
        - 'article': Long-form article text & metadata
        - 'links': All hyperlinks on the page
        - 'media': All images, videos, audio, and embeds
        - 'contacts': Emails, phone numbers, and social profiles
        - 'metadata': OpenGraph, Twitter, and HTML meta tags
        - 'selectors': Custom CSS selectors
        """
        html = self.fetch(url)
        extractor = SmartExtractor(base_url=self.last_telemetry.get("final_url") or url)
        soup = extractor.parse_soup(html)

        title_tag = soup.find("title")
        if title_tag and self.last_telemetry:
            self.last_telemetry["page_title"] = extractor.clean_text(title_tag.get_text())

        if mode == "auto":
            return extractor.extract_auto(html)
        elif mode == "cards":
            return "cards", extractor.extract_repeating_items(soup)
        elif mode == "json_ld":
            return "json_ld", extractor.extract_json_ld(soup)
        elif mode == "tables":
            tables = extractor.extract_tables(soup)
            if tables:
                best = max(tables, key=lambda t: len(t))
                return "tables", best
            return "tables", []
        elif mode == "article":
            return "article", [extractor.extract_article(soup)]
        elif mode == "links":
            return "links", extractor.extract_links(soup)
        elif mode == "media":
            return "media", extractor.extract_media(soup)
        elif mode == "contacts":
            return "contacts", extractor.extract_contacts(soup)
        elif mode == "metadata":
            meta = extractor.extract_metadata(soup)
            return "metadata", [meta] if meta else []
        elif mode == "selectors":
            if not item_selector or not fields:
                raise ValueError("Both 'item_selector' and 'fields' are required for 'selectors' mode.")
            return "selectors", extractor.extract_by_selectors(soup, item_selector, fields)
        else:
            raise ValueError(
                f"Unknown mode: {mode}. Choose from 'auto', 'cards', 'json_ld', 'tables', 'article', 'links', 'media', 'contacts', 'metadata', 'selectors'."
            )

    def scrape_to_dataframe(
        self,
        url: str,
        mode: str = "auto",
        item_selector: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None,
        deduplicate: bool = True,
    ) -> pd.DataFrame:
        """Scrape a URL and return a normalized pandas DataFrame."""
        strategy, records = self.scrape(
            url=url,
            mode=mode,
            item_selector=item_selector,
            fields=fields,
        )
        exporter = DatasetExporter(deduplicate=deduplicate)
        processed = exporter.process_records(records, source_url=url)
        return exporter.to_dataframe(processed)

    def scrape_to_csv(
        self,
        url: str,
        output_csv: str,
        mode: str = "auto",
        item_selector: Optional[str] = None,
        fields: Optional[Dict[str, str]] = None,
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        """
        Scrape a URL and save directly to an Excel-compatible CSV file.
        Returns metadata summary about the generated dataset.
        """
        strategy, records = self.scrape(
            url=url,
            mode=mode,
            item_selector=item_selector,
            fields=fields,
        )
        if not records:
            raise ValueError(f"No records could be extracted from {url} using mode '{mode}'.")

        exporter = DatasetExporter(deduplicate=deduplicate)
        saved_path = exporter.save_csv(records, output_csv, source_url=url)
        df = pd.read_csv(saved_path, encoding="utf-8-sig")
        summary = exporter.dataset_summary(df)
        summary["saved_path"] = saved_path
        summary["strategy_used"] = strategy
        return summary

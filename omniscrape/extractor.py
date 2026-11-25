import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag, Comment


class SmartExtractor:
    """
    Intelligent HTML content extractor capable of extracting:
    1. Repeating structured item cards (e-commerce products, search results, listing cards)
    2. Embedded JSON-LD schema.org structured data
    3. HTML tabular data (tables)
    4. Long-form article and publication content
    5. Custom CSS selector extraction
    """

    PRICE_REGEX = re.compile(
        r"(?:[\$\€\£\₹\¥]|USD|EUR|GBP|INR|Rs\.?)\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)|\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP|INR|₹|\$)\b",
        re.IGNORECASE,
    )
    RATING_REGEX = re.compile(
        r"\b([0-5](?:\.\d)?)\s*(?:/\s*5|stars?|\bout of 5\b)?\b",
        re.IGNORECASE,
    )
    DATE_REGEX = re.compile(
        r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
        re.IGNORECASE,
    )
    EMAIL_REGEX = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )
    PHONE_REGEX = re.compile(
        r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}"
    )
    SOCIAL_DOMAINS = (
        "linkedin.com",
        "twitter.com",
        "x.com",
        "github.com",
        "instagram.com",
        "youtube.com",
        "facebook.com",
        "tiktok.com",
    )

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    def parse_soup(self, html: str) -> BeautifulSoup:
        """Parse HTML string into a BeautifulSoup object."""
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            return BeautifulSoup(html, "html.parser")

    def clean_soup(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove comments and unwanted elements like script, style, iframe, etc."""
        cleaned = BeautifulSoup(str(soup), "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")
        for tag in cleaned(["script", "style", "noscript", "svg", "canvas", "header", "footer", "nav"]):
            # Preserve JSON-LD scripts
            if tag.name == "script" and tag.get("type") == "application/ld+json":
                continue
            tag.decompose()
        for comment in cleaned.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()
        return cleaned

    def clean_text(self, text: Optional[str]) -> str:
        """Normalize whitespace, remove excess newlines and trailing spaces."""
        if not text:
            return ""
        # Replace multiple whitespace/newlines with single space or clean line
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()

    def make_absolute_url(self, url: Optional[str], base: Optional[str] = None) -> str:
        """Convert relative URL to absolute URL."""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("javascript:") or url.startswith("mailto:") or url.startswith("#"):
            return ""
        target_base = base or self.base_url
        if target_base:
            return urljoin(target_base, url)
        return url

    # -------------------------------------------------------------------------
    # 1. JSON-LD Extraction (High fidelity structured data)
    # -------------------------------------------------------------------------
    def extract_json_ld(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract schema.org JSON-LD structured data from the page."""
        results: List[Dict[str, Any]] = []
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string or script.get_text() or "{}")
            except Exception:
                continue

            items_to_process = []
            if isinstance(data, list):
                items_to_process.extend(data)
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    items_to_process.extend(data["@graph"])
                else:
                    items_to_process.append(data)

            for item in items_to_process:
                if not isinstance(item, dict):
                    continue
                # Handle ItemList
                if item.get("@type") == "ItemList" and "itemListElement" in item:
                    elements = item.get("itemListElement", [])
                    for elem in elements:
                        if isinstance(elem, dict):
                            actual_item = elem.get("item", elem)
                            if isinstance(actual_item, dict):
                                results.append(self._flatten_json_ld(actual_item))
                elif item.get("@type") in [
                    "Product",
                    "Article",
                    "NewsArticle",
                    "BlogPosting",
                    "Recipe",
                    "JobPosting",
                    "Event",
                    "LocalBusiness",
                    "Organization",
                    "Book",
                    "Movie",
                ]:
                    results.append(self._flatten_json_ld(item))

        return results

    def _flatten_json_ld(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten and simplify common schema.org types into clean tabular fields."""
        record: Dict[str, Any] = {}
        record["schema_type"] = item.get("@type", "")
        record["name"] = item.get("name") or item.get("headline") or ""
        record["description"] = self.clean_text(item.get("description", ""))
        record["url"] = self.make_absolute_url(item.get("url") or item.get("@id"))

        # Image
        img = item.get("image")
        if isinstance(img, str):
            record["image_url"] = self.make_absolute_url(img)
        elif isinstance(img, list) and img and isinstance(img[0], str):
            record["image_url"] = self.make_absolute_url(img[0])
        elif isinstance(img, dict):
            record["image_url"] = self.make_absolute_url(img.get("url", ""))

        # Author / Brand / Publisher
        for key in ["brand", "author", "publisher"]:
            val = item.get(key)
            if isinstance(val, dict):
                record[key] = val.get("name", "")
            elif isinstance(val, str):
                record[key] = val

        # Offers / Price
        offers = item.get("offers")
        if isinstance(offers, dict):
            record["price"] = offers.get("price") or ""
            record["currency"] = offers.get("priceCurrency") or ""
            record["availability"] = offers.get("availability") or ""
        elif isinstance(offers, list) and offers and isinstance(offers[0], dict):
            record["price"] = offers[0].get("price") or ""
            record["currency"] = offers[0].get("priceCurrency") or ""

        # Rating
        rating = item.get("aggregateRating")
        if isinstance(rating, dict):
            record["rating"] = rating.get("ratingValue") or ""
            record["review_count"] = rating.get("reviewCount") or rating.get("ratingCount") or ""

        # Dates
        for date_field in ["datePublished", "dateModified", "startDate"]:
            if item.get(date_field):
                record[date_field] = item.get(date_field)

        # Retain any remaining simple string/numeric fields
        for k, v in item.items():
            if k not in record and not k.startswith("@") and isinstance(v, (str, int, float, bool)):
                record[k] = v

        return {k: v for k, v in record.items() if v != "" and v is not None}

    # -------------------------------------------------------------------------
    # 2. HTML Table Extraction
    # -------------------------------------------------------------------------
    def extract_tables(self, soup: BeautifulSoup) -> List[List[Dict[str, Any]]]:
        """Extract all HTML tables into lists of tabular dictionary rows."""
        extracted_tables: List[List[Dict[str, Any]]] = []
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if not rows or len(rows) < 2:
                continue

            headers: List[str] = []
            # Check for <th> in the first row or thead
            thead = table.find("thead")
            header_row = thead.find("tr") if thead else rows[0]
            header_cols = header_row.find_all(["th", "td"])

            for idx, col in enumerate(header_cols):
                h_text = self.clean_text(col.get_text())
                headers.append(h_text if h_text else f"column_{idx+1}")

            # Ensure headers are unique
            seen: Dict[str, int] = {}
            unique_headers: List[str] = []
            for h in headers:
                if h in seen:
                    seen[h] += 1
                    unique_headers.append(f"{h}_{seen[h]}")
                else:
                    seen[h] = 0
                    unique_headers.append(h)

            start_idx = 1 if (not thead and header_row == rows[0]) else 0
            body_rows = rows[start_idx:] if (not thead and header_row == rows[0]) else (
                table.find("tbody").find_all("tr") if table.find("tbody") else rows[1:]
            )

            table_data: List[Dict[str, Any]] = []
            for row in body_rows:
                cols = row.find_all(["td", "th"])
                if not cols:
                    continue
                row_dict: Dict[str, Any] = {}
                for idx, col in enumerate(cols):
                    col_name = unique_headers[idx] if idx < len(unique_headers) else f"column_{idx+1}"
                    # Capture link if present inside cell
                    link = col.find("a", href=True)
                    cell_text = self.clean_text(col.get_text())
                    row_dict[col_name] = cell_text
                    if link and link.get("href"):
                        row_dict[f"{col_name}_link"] = self.make_absolute_url(link["href"])

                if any(row_dict.values()):
                    table_data.append(row_dict)

            if len(table_data) >= 1:
                extracted_tables.append(table_data)

        return extracted_tables

    # -------------------------------------------------------------------------
    # 3. Intelligent Repeating Card / Item Detection
    # -------------------------------------------------------------------------
    def extract_repeating_items(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Automatically identifies clusters of repeating item cards (products,
        articles, rows, directory entries) by DOM structural pattern analysis.
        """
        # Find candidate container elements
        candidate_containers = []
        for parent in soup.find_all(["div", "ul", "ol", "section", "main", "article"]):
            # Ignore containers nested inside a table
            if parent.find_parent("table"):
                continue

            # Get direct children that are tags
            children = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
            if len(children) < 3 or len(children) > 300:
                continue

            # Group children by tag and class signature
            signatures: Dict[str, List[Tag]] = {}
            for child in children:
                tag_name = child.name
                classes = ".".join(sorted(child.get("class", [])))
                sig = f"{tag_name}.{classes}" if classes else tag_name
                signatures.setdefault(sig, []).append(child)

            for sig, items in signatures.items():
                if len(items) >= 3:
                    # Score items based on content richness (presence of text, links, headings)
                    score = 0
                    sample = items[:5]
                    has_links = sum(1 for item in sample if item.find("a", href=True))
                    has_headings = sum(1 for item in sample if item.find(["h1", "h2", "h3", "h4", "h5", "h6"]))
                    has_images = sum(1 for item in sample if item.find("img"))
                    avg_text_len = sum(len(item.get_text(strip=True)) for item in sample) / len(sample)

                    if avg_text_len > 15:  # meaningful content
                        score += len(items) * 2
                        score += has_links * 10
                        score += has_headings * 15
                        score += has_images * 8
                        candidate_containers.append((score, items))

        if not candidate_containers:
            return []

        # Sort candidate clusters by highest score
        candidate_containers.sort(key=lambda x: x[0], reverse=True)
        best_items = candidate_containers[0][1]

        # Extract fields from each item
        extracted_records = []
        for item in best_items:
            record = self._parse_single_card(item)
            if record and (record.get("title") or record.get("text") or record.get("link")):
                extracted_records.append(record)

        return extracted_records

    def _parse_single_card(self, item: Tag) -> Dict[str, Any]:
        """Extract structured fields from a single repeating card element."""
        record: Dict[str, Any] = {}

        # 1. Title / Heading
        heading = item.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            record["title"] = self.clean_text(heading.get_text())
        else:
            # Look for elements with class containing 'title' or 'name'
            title_elem = item.find(class_=re.compile(r"(title|name|header|product-name)", re.I))
            if title_elem:
                record["title"] = self.clean_text(title_elem.get_text())

        # 2. Link / URL
        primary_link = item.find("a", href=True)
        if primary_link and primary_link.get("href"):
            record["link"] = self.make_absolute_url(primary_link["href"])
            if "title" not in record or not record["title"]:
                link_text = self.clean_text(primary_link.get_text())
                if len(link_text) > 3:
                    record["title"] = link_text

        # 3. Price
        raw_text = item.get_text()
        price_elem = item.find(class_=re.compile(r"(price|cost|amount|current-price)", re.I))
        if price_elem:
            record["price"] = self.clean_text(price_elem.get_text())
        else:
            price_match = self.PRICE_REGEX.search(raw_text)
            if price_match:
                record["price"] = price_match.group(0).strip()

        # 4. Image
        img_elem = item.find("img")
        if img_elem:
            src = (
                img_elem.get("src")
                or img_elem.get("data-src")
                or img_elem.get("data-lazy-src")
                or img_elem.get("srcset", "").split(" ")[0]
            )
            if src:
                record["image_url"] = self.make_absolute_url(src)

        # 5. Rating / Reviews
        rating_elem = item.find(class_=re.compile(r"(rating|stars|score)", re.I))
        if rating_elem:
            record["rating"] = self.clean_text(rating_elem.get_text())
        else:
            rating_match = self.RATING_REGEX.search(raw_text)
            if rating_match:
                record["rating"] = rating_match.group(1)

        # 6. Description / Snippet
        desc_elem = item.find(class_=re.compile(r"(desc|summary|snippet|excerpt|detail)", re.I))
        if desc_elem and desc_elem != heading:
            record["description"] = self.clean_text(desc_elem.get_text())
        else:
            # Grab first paragraph that isn't the heading or price
            p = item.find("p")
            if p:
                p_text = self.clean_text(p.get_text())
                if p_text != record.get("title") and p_text != record.get("price"):
                    record["description"] = p_text

        # 7. Category / Tag / Badge
        badge_elem = item.find(class_=re.compile(r"(badge|tag|category|label|pill)", re.I))
        if badge_elem:
            record["category"] = self.clean_text(badge_elem.get_text())

        # 8. Date if detectable
        date_match = self.DATE_REGEX.search(raw_text)
        if date_match:
            record["date"] = date_match.group(0)

        # 9. Fallback full text if card has minimal structure
        full_text = self.clean_text(raw_text)
        if "title" not in record and full_text:
            record["text"] = full_text[:200]

        return {k: v for k, v in record.items() if v}

    # -------------------------------------------------------------------------
    # 4. Page Meta & Article Extraction
    # -------------------------------------------------------------------------
    def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract OpenGraph, Twitter, and standard HTML meta tags."""
        meta: Dict[str, Any] = {}

        # Title
        title_tag = soup.find("title")
        if title_tag:
            meta["meta_title"] = self.clean_text(title_tag.get_text())

        # Meta tags
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or ""
            content = tag.get("content") or ""
            if not name or not content:
                continue

            name = name.lower()
            if name in ["og:title", "twitter:title"]:
                meta.setdefault("og_title", self.clean_text(content))
            elif name in ["og:description", "description", "twitter:description"]:
                meta.setdefault("meta_description", self.clean_text(content))
            elif name in ["og:image", "twitter:image"]:
                meta.setdefault("og_image", self.make_absolute_url(content))
            elif name in ["keywords"]:
                meta["keywords"] = self.clean_text(content)
            elif name in ["author"]:
                meta["author"] = self.clean_text(content)
            elif name in ["article:published_time", "date"]:
                meta["published_time"] = content

        return meta

    def extract_article(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract full article text and metadata for NLP datasets."""
        article_data: Dict[str, Any] = self.extract_metadata(soup)

        # Headline
        h1 = soup.find("h1")
        if h1:
            article_data["headline"] = self.clean_text(h1.get_text())
        elif "meta_title" in article_data:
            article_data["headline"] = article_data["meta_title"]

        # Body paragraphs
        content_container = (
            soup.find("article")
            or soup.find("main")
            or soup.find(class_=re.compile(r"(content|article-body|post-content|entry-content)", re.I))
            or soup.body
        )

        if content_container:
            paras = [self.clean_text(p.get_text()) for p in content_container.find_all("p")]
            cleaned_paras = [p for p in paras if len(p) > 25]
            article_data["body_text"] = "\n\n".join(cleaned_paras)
            article_data["word_count"] = sum(len(p.split()) for p in cleaned_paras)

        return article_data

    # -------------------------------------------------------------------------
    # 5. Targeted CSS Selector Extraction
    # -------------------------------------------------------------------------
    def extract_by_selectors(
        self,
        soup: BeautifulSoup,
        item_selector: str,
        fields: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        Extract items by specific CSS selectors.
        fields format: {"field_name": "css_selector[@attribute]"}
        e.g. {"title": "h2", "link": "a@href", "img": "img@src"}
        """
        items = soup.select(item_selector)
        records: List[Dict[str, Any]] = []

        for item in items:
            row: Dict[str, Any] = {}
            for field_name, selector_expr in fields.items():
                attr = None
                sel = selector_expr
                if "@" in selector_expr:
                    sel, attr = selector_expr.split("@", 1)

                target = item.select_one(sel) if sel else item
                if target:
                    if attr:
                        val = target.get(attr, "")
                        if attr in ["href", "src"]:
                            val = self.make_absolute_url(val)
                        row[field_name] = self.clean_text(str(val))
                    else:
                        row[field_name] = self.clean_text(target.get_text())
                else:
                    row[field_name] = ""

            if any(row.values()):
                records.append(row)

        return records

    # -------------------------------------------------------------------------
    # 6. Automatic Intelligent Master Extraction
    # -------------------------------------------------------------------------
    def extract_auto(self, html: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Master auto-extractor: Determines the optimal extraction strategy
        (JSON-LD -> Structured Items -> Tables -> Article) and returns
        (strategy_name, list_of_records).
        """
        soup = self.parse_soup(html)

        # 1. Try JSON-LD schema (Structured data)
        json_ld_records = self.extract_json_ld(soup)
        if len(json_ld_records) >= 2:
            return "json_ld", json_ld_records

        # 2. Try Repeating Card Items
        card_records = self.extract_repeating_items(soup)
        if len(card_records) >= 2:
            return "cards", card_records

        # 3. Try HTML Tables
        tables = self.extract_tables(soup)
        if tables:
            best_table = max(tables, key=lambda t: len(t))
            if len(best_table) >= 2:
                return "tables", best_table

        # 4. If single JSON-LD record exists
        if len(json_ld_records) == 1:
            return "json_ld_single", json_ld_records

        # 5. Fallback to Article / Page Content
        article = self.extract_article(soup)
        if article.get("body_text") or article.get("headline"):
            return "article", [article]

        # 6. Last resort: Extract metadata
        meta = self.extract_metadata(soup)
        return "metadata", [meta] if meta else []

    # -------------------------------------------------------------------------
    # 7. Pro Intelligence Extractors (Links, Media, Contacts & Socials)
    # -------------------------------------------------------------------------
    def extract_links(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all hyperlinks with anchor text, domain, and internal/external flag."""
        base_host = urlparse(self.base_url).netloc.lower() if self.base_url else ""
        seen = set()
        records: List[Dict[str, Any]] = []

        for a in soup.find_all("a", href=True):
            abs_url = self.make_absolute_url(a.get("href"))
            if not abs_url or abs_url in seen:
                continue
            seen.add(abs_url)

            parsed = urlparse(abs_url)
            domain = parsed.netloc.lower()
            is_external = bool(base_host and domain and domain != base_host)
            rel_attr = a.get("rel")
            rel_str = " ".join(rel_attr) if isinstance(rel_attr, list) else (rel_attr or "")

            section = "body"
            if a.find_parent("nav"):
                section = "nav"
            elif a.find_parent("header"):
                section = "header"
            elif a.find_parent("footer"):
                section = "footer"

            records.append(
                {
                    "text": self.clean_text(a.get_text()) or "[no text]",
                    "url": abs_url,
                    "domain": domain,
                    "is_external": is_external,
                    "section": section,
                    "rel": rel_str,
                }
            )
        return records

    def extract_media(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all images, videos, audio, and embedded media elements."""
        seen = set()
        records: List[Dict[str, Any]] = []

        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or (img.get("srcset", "").split(" ")[0] if img.get("srcset") else "")
            )
            abs_url = self.make_absolute_url(src)
            if not abs_url or abs_url in seen:
                continue
            seen.add(abs_url)
            records.append(
                {
                    "media_type": "image",
                    "url": abs_url,
                    "alt": self.clean_text(img.get("alt")),
                    "width": img.get("width") or "",
                    "height": img.get("height") or "",
                }
            )

        for tag_name, mtype in [("video", "video"), ("audio", "audio"), ("iframe", "embed")]:
            for el in soup.find_all(tag_name):
                src = el.get("src") or ""
                if not src:
                    source_tag = el.find("source", src=True)
                    src = source_tag.get("src") if source_tag else ""
                abs_url = self.make_absolute_url(src)
                if not abs_url or abs_url in seen:
                    continue
                seen.add(abs_url)
                records.append(
                    {
                        "media_type": mtype,
                        "url": abs_url,
                        "alt": self.clean_text(el.get("title") or el.get("aria-label")),
                        "width": el.get("width") or "",
                        "height": el.get("height") or "",
                    }
                )
        return records

    def extract_contacts(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract emails, phone numbers, and social media profile links."""
        records: List[Dict[str, Any]] = []
        seen = set()

        def _add(ctype: str, value: str, source: str) -> None:
            key = f"{ctype}:{value.lower()}"
            if key not in seen:
                seen.add(key)
                records.append({"type": ctype, "value": value, "source": source})

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                _add("email", href[7:].split("?")[0].strip(), "mailto_link")
            elif low.startswith("tel:"):
                _add("phone", href[4:].strip(), "tel_link")
            else:
                abs_url = self.make_absolute_url(href)
                domain = urlparse(abs_url).netloc.lower()
                for soc in self.SOCIAL_DOMAINS:
                    if soc in domain:
                        _add(f"social_{soc.split('.')[0]}", abs_url, "anchor")
                        break

        page_text = soup.get_text(" ")
        for email in self.EMAIL_REGEX.findall(page_text):
            if not email.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
                _add("email", email, "page_text")

        return records

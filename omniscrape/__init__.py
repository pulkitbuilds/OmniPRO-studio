"""
OmniScrape - Universal Intelligent Web Scraper & Dataset Builder
Extracts structured datasets from any website into clean, ML-ready CSV files.
"""

from .scraper import UniversalScraper
from .extractor import SmartExtractor
from .dataset import DatasetExporter
from .crawler import WebCrawler

__version__ = "1.0.0"
__all__ = ["UniversalScraper", "SmartExtractor", "DatasetExporter", "WebCrawler"]

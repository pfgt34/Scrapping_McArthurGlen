"""Configuration values and sample mall profiles."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dataclasses import dataclass

from .models import MallProfile

BASE_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"

USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

CAPTCHA_MARKERS = (
    "captcha",
    "verify you are human",
    "cloudflare",
    "access denied",
    "attention required",
)

DEFAULT_BRAND_ALIASES = {
    "zara france": "Zara",
    "zara": "Zara",
    "h and m": "H&M",
    "h&m": "H&M",
    "hm": "H&M",
    "c and a": "C&A",
    "c&a": "C&A",
    "uniqlo france": "UNIQLO",
    "decathlon france": "Decathlon",
    "sephora france": "Sephora",
}


@dataclass(frozen=True, slots=True)
class ScraperRuntimeConfig:
    """Runtime parameters for crawling and persistence."""

    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.5
    headless: bool = True
    max_pages: int = 25
    save_raw_html: bool = True
    use_proxy: bool = False


def ensure_directories() -> None:
    """Create the expected project directories if they are missing."""

    for path in (DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, CONFIG_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(log_name: str = "scraper") -> logging.Logger:
    """Configure a rotating logger for the scraping pipeline.

    Args:
        log_name: Name of the logger to configure.

    Returns:
        Configured logger instance.
    """

    ensure_directories()
    logger = logging.getLogger(log_name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / f"{log_name}.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


WESTFIELD_LIKE_PROFILE = MallProfile(
    mall_id="westfield-demo",
    mall_name="Westfield Demo Center",
    start_url="https://www.westfield.com/",
    store_card_css=".store-card, .retailer-card, li[data-store-name], li[data-merchant]",
    store_name_css=".store-card__title, .retailer-card__title, h3, h2, .title",
    store_url_css="a[href]",
    next_page_css='a[rel="next"], .pagination__next a, a[aria-label*="Next"]',
    requires_javascript=True,
    store_card_xpath="//div[contains(@class, 'store-card') or contains(@class, 'retailer-card')]",
    store_name_xpath=".//*[self::h3 or self::h2 or contains(@class, 'title')]",
    store_url_xpath=".//a[@href]",
    brand_aliases=DEFAULT_BRAND_ALIASES,
)

"""Domain models used by the scraping framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class MallProfile:
    """Describes how to scrape a specific shopping center.

    Attributes:
        mall_id: Stable technical identifier for the mall.
        mall_name: Human-readable name.
        start_url: Entry URL for the store listing.
        store_card_css: CSS selector targeting a store card.
        store_name_css: CSS selector targeting the store name inside a card.
        store_url_css: Optional CSS selector for the store detail link.
        next_page_css: Optional CSS selector for the pagination next link.
        requires_javascript: Whether dynamic rendering is expected.
        store_card_xpath: Optional XPath selector for Selenium workflows.
        store_name_xpath: Optional XPath selector for Selenium workflows.
        store_url_xpath: Optional XPath selector for Selenium workflows.
        brand_aliases: Mapping of normalized brand aliases to canonical names.
    """

    mall_id: str
    mall_name: str
    start_url: str
    store_card_css: str
    store_name_css: str
    store_url_css: str | None = None
    next_page_css: str | None = None
    requires_javascript: bool = False
    store_card_xpath: str | None = None
    store_name_xpath: str | None = None
    store_url_xpath: str | None = None
    brand_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ScrapedStore:
    """Represents one store observation captured during a crawl."""

    mall_id: str
    mall_name: str
    crawl_date: date
    store_name_raw: str
    store_name_normalized: str
    source_url: str
    store_url: str | None = None
    source_mode: str = "static"
    description: str = ""
    categories: list[str] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    card_text: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert the record into a serializable dictionary."""

        return {
            "mall_id": self.mall_id,
            "mall_name": self.mall_name,
            "crawl_date": self.crawl_date.isoformat(),
            "store_name_raw": self.store_name_raw,
            "store_name_normalized": self.store_name_normalized,
            "source_url": self.source_url,
            "store_url": self.store_url or "",
            "source_mode": self.source_mode,
            "description": self.description,
            "categories": " | ".join(self.categories),
            "badges": " | ".join(self.badges),
            "card_text": self.card_text,
        }


@dataclass(slots=True)
class ScrapeRunResult:
    """Container for the outcome of a scraping run."""

    profile: MallProfile
    crawl_date: date
    records: list[ScrapedStore]
    raw_html_paths: list[Path]
    visited_urls: list[str]
    source_modes: list[str]
    run_started_at: datetime
    run_finished_at: datetime


@dataclass(slots=True)
class DiffResult:
    """Summarizes changes between two snapshots."""

    mall_id: str
    crawl_date: date
    previous_crawl_date: date | None
    openings: list[dict[str, str]]
    closures: list[dict[str, str]]
    unchanged: list[dict[str, str]]
    summary: dict[str, int]

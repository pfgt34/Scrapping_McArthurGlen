"""Hybrid scraping engine with static and dynamic fetch strategies."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from bs4 import BeautifulSoup
from bs4.element import Tag
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options

from .config import (
    CAPTCHA_MARKERS,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    ScraperRuntimeConfig,
    USER_AGENT_POOL,
)
from .models import MallProfile, ScrapeRunResult, ScrapedStore


class ScraperError(RuntimeError):
    """Base error for the scraping engine."""


class FetchError(ScraperError):
    """Raised when a page cannot be fetched reliably."""


class ParseError(ScraperError):
    """Raised when extracted HTML cannot be parsed into stores."""


class CaptchaDetectedError(ScraperError):
    """Raised when a page appears to be protected by a captcha."""


class BaseMallScraper(ABC):
    """Base class for mall scrapers.

    Subclasses only need to describe how to extract store cards from the HTML.
    The engine handles retries, source saving, pagination, and fallback between
    static and dynamic retrieval strategies.
    """

    def __init__(
        self,
        profile: MallProfile,
        runtime_config: ScraperRuntimeConfig | None = None,
        logger=None,
        proxies: dict[str, str] | None = None,
    ) -> None:
        self.profile = profile
        self.runtime_config = runtime_config or ScraperRuntimeConfig()
        self.logger = logger
        self.proxies = proxies or {}

    def run(self, crawl_date: date | None = None) -> ScrapeRunResult:
        """Execute the crawl and return a structured result."""

        crawl_date = crawl_date or date.today()
        run_started_at = datetime.utcnow()
        visited_urls: list[str] = []
        source_modes: list[str] = []
        raw_html_paths: list[Path] = []
        records: list[ScrapedStore] = []
        seen_keys: set[str] = set()

        current_url = self.profile.start_url
        page_index = 1

        while current_url and page_index <= self.runtime_config.max_pages:
            visited_urls.append(current_url)
            html, source_mode = self.fetch_page_html(current_url)

            if self.runtime_config.save_raw_html:
                raw_path = self.save_raw_html(
                    crawl_date=crawl_date,
                    page_index=page_index,
                    source_mode=source_mode,
                    source_url=current_url,
                    html=html,
                )
                raw_html_paths.append(raw_path)

            page_records = []
            effective_mode = source_mode
            try:
                page_records = self.parse_store_records(
                    html=html,
                    source_url=current_url,
                    crawl_date=crawl_date,
                    source_mode=source_mode,
                )
            except ParseError as exc:
                self._log_warning(
                    f"{self.profile.mall_name}: primary parse failed for {current_url}: {exc}"
                )

            if not page_records:
                fallback_mode = "dynamic" if source_mode == "static" else "static"
                try:
                    fallback_html = self._fetch_with_mode(url=current_url, mode=fallback_mode)
                    if self._html_is_usable(fallback_html):
                        if self.runtime_config.save_raw_html:
                            fallback_path = self.save_raw_html(
                                crawl_date=crawl_date,
                                page_index=page_index,
                                source_mode=fallback_mode,
                                source_url=current_url,
                                html=fallback_html,
                            )
                            raw_html_paths.append(fallback_path)

                        page_records = self.parse_store_records(
                            html=fallback_html,
                            source_url=current_url,
                            crawl_date=crawl_date,
                            source_mode=fallback_mode,
                        )
                        effective_mode = fallback_mode
                except Exception as exc:  # noqa: BLE001
                    self._log_warning(
                        f"{self.profile.mall_name}: fallback parse failed for {current_url}: {exc}"
                    )

            source_modes.append(effective_mode)
            for record in page_records:
                record_key = self._store_key(record)
                if record_key in seen_keys:
                    continue
                seen_keys.add(record_key)
                records.append(record)

            self._log_info(
                f"{self.profile.mall_name}: page {page_index} -> {len(page_records)} stores, mode={source_mode}"
            )

            current_url = self._extract_next_url(html=html, base_url=current_url)
            page_index += 1

        run_finished_at = datetime.utcnow()
        self._log_info(
            f"{self.profile.mall_name}: crawl complete with {len(records)} unique stores"
        )
        return ScrapeRunResult(
            profile=self.profile,
            crawl_date=crawl_date,
            records=records,
            raw_html_paths=raw_html_paths,
            visited_urls=visited_urls,
            source_modes=source_modes,
            run_started_at=run_started_at,
            run_finished_at=run_finished_at,
        )

    def fetch_page_html(self, url: str) -> tuple[str, str]:
        """Fetch a page using static or dynamic rendering with retries.

        Args:
            url: Target page URL.

        Returns:
            A tuple containing the page HTML and the fetch mode used.
        """

        first_mode = "dynamic" if self.profile.requires_javascript else "static"
        second_mode = "static" if first_mode == "dynamic" else "dynamic"
        last_error: Exception | None = None

        for attempt in range(1, self.runtime_config.retry_attempts + 1):
            for mode in (first_mode, second_mode):
                try:
                    html = self._fetch_with_mode(url=url, mode=mode)
                    if self._html_is_usable(html):
                        return html, mode
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self._log_warning(
                        f"{self.profile.mall_name}: {mode} fetch failed for {url} on attempt {attempt}: {exc}"
                    )

            if attempt < self.runtime_config.retry_attempts:
                self._sleep_with_backoff(attempt)

        raise FetchError(
            f"Unable to fetch {url} after {self.runtime_config.retry_attempts} attempts"
        ) from last_error

    def save_raw_html(
        self,
        crawl_date: date,
        page_index: int,
        source_mode: str,
        source_url: str,
        html: str,
    ) -> Path:
        """Persist the raw HTML used for audit and reprocessing."""

        target_dir = RAW_DATA_DIR / self.profile.mall_id / crawl_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_mode = source_mode.replace(" ", "_")
        raw_path = target_dir / f"{page_index:03d}_{safe_mode}.html"
        raw_path.write_text(html, encoding="utf-8")

        metadata_path = target_dir / f"{page_index:03d}_{safe_mode}.meta.txt"
        metadata_path.write_text(
            f"source_url={source_url}\nsource_mode={source_mode}\npage_index={page_index}\n",
            encoding="utf-8",
        )
        return raw_path

    def _fetch_with_mode(self, url: str, mode: str) -> str:
        if mode == "static":
            return self._fetch_static_html(url)
        if mode == "dynamic":
            return self._fetch_dynamic_html(url)
        raise ValueError(f"Unknown fetch mode: {mode}")

    def _fetch_static_html(self, url: str) -> str:
        headers = {"User-Agent": random.choice(USER_AGENT_POOL)}
        request = Request(url, headers=headers)
        opener = build_opener(HTTPCookieProcessor())

        if self.proxies:
            opener = build_opener(HTTPCookieProcessor(), ProxyHandler(self.proxies))

        with opener.open(request, timeout=self.runtime_config.timeout_seconds) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(content_type, errors="replace")

    def _fetch_dynamic_html(self, url: str) -> str:
        options = Options()
        if self.runtime_config.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--user-agent={random.choice(USER_AGENT_POOL)}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if self.proxies.get("http") or self.proxies.get("https"):
            proxy_url = self.proxies.get("https") or self.proxies.get("http")
            if proxy_url:
                options.add_argument(f"--proxy-server={proxy_url}")

        driver = webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(self.runtime_config.timeout_seconds)
            driver.get(url)
            time.sleep(2.0)
            return driver.page_source
        except TimeoutException as exc:
            raise FetchError(f"Timed out loading {url}") from exc
        except WebDriverException as exc:
            raise FetchError(f"Selenium error while loading {url}") from exc
        finally:
            driver.quit()

    def _html_is_usable(self, html: str) -> bool:
        lowered = html.lower()
        if any(marker in lowered for marker in CAPTCHA_MARKERS):
            if not self.handle_captcha(html):
                raise CaptchaDetectedError(
                    f"Captcha detected on {self.profile.mall_name}"
                )
        return len(html.strip()) > 200

    def _sleep_with_backoff(self, attempt: int) -> None:
        delay = self.runtime_config.retry_backoff_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, delay * 0.2)
        time.sleep(delay + jitter)

    def _extract_next_url(self, html: str, base_url: str) -> str | None:
        if not self.profile.next_page_css:
            return None

        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.select_one(self.profile.next_page_css)
        if next_link is None:
            return None

        href = next_link.get("href")
        if not href:
            return None

        return urljoin(base_url, href)

    def _store_key(self, record: ScrapedStore) -> str:
        normalized_url = (record.store_url or "").strip().lower()
        normalized_name = record.store_name_normalized.strip().lower()
        return f"{normalized_name}|{normalized_url}"

    def _log_info(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)

    def _log_warning(self, message: str) -> None:
        if self.logger is not None:
            self.logger.warning(message)

    @abstractmethod
    def parse_store_records(
        self,
        html: str,
        source_url: str,
        crawl_date: date,
        source_mode: str,
    ) -> list[ScrapedStore]:
        """Extract store records from a page of HTML."""

    def handle_captcha(self, html: str) -> bool:
        """Hook for custom captcha handling.

        Return True if the page can still be processed, otherwise False.
        """

        self._log_warning(
            f"{self.profile.mall_name}: captcha marker detected, manual intervention required"
        )
        return False


class GenericMallScraper(BaseMallScraper):
    """Generic implementation driven by CSS selectors in the profile."""

    def parse_store_records(
        self,
        html: str,
        source_url: str,
        crawl_date: date,
        source_mode: str,
    ) -> list[ScrapedStore]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(self.profile.store_card_css)
        if not cards:
            raise ParseError(
                f"No store cards found for {self.profile.mall_name} using {self.profile.store_card_css}"
            )

        records: list[ScrapedStore] = []
        for card in cards:
            raw_name = self._extract_store_name(card)
            if not raw_name:
                continue

            store_url = self._extract_store_url(card=card, base_url=source_url)
            normalized_name = self._normalize_brand_name(raw_name)
            records.append(
                ScrapedStore(
                    mall_id=self.profile.mall_id,
                    mall_name=self.profile.mall_name,
                    crawl_date=crawl_date,
                    store_name_raw=raw_name,
                    store_name_normalized=normalized_name,
                    source_url=source_url,
                    store_url=store_url,
                    source_mode=source_mode,
                )
            )
        return records

    def _extract_store_name(self, card: Tag) -> str:
        name_element = card.select_one(self.profile.store_name_css)
        if name_element is None:
            return ""
        return " ".join(name_element.get_text(" ", strip=True).split())

    def _extract_store_url(self, card: Tag, base_url: str) -> str | None:
        if self.profile.store_url_css:
            url_element = card.select_one(self.profile.store_url_css)
            if url_element is not None:
                href = url_element.get("href") or url_element.get("data-href")
                if href:
                    return urljoin(base_url, href)

        if card.name == "a":
            href = card.get("href")
            if href:
                return urljoin(base_url, href)
        return None

    def _normalize_brand_name(self, raw_name: str) -> str:
        text = raw_name.lower().strip()
        text = text.replace("’", "'")
        text = " ".join(text.split())

        aliases = {self._normalize_key(key): value for key, value in self.profile.brand_aliases.items()}
        normalized_key = self._normalize_key(text)
        if normalized_key in aliases:
            return aliases[normalized_key]

        return self._title_case_brand(text)

    @staticmethod
    def _normalize_key(text: str) -> str:
        import re
        import unicodedata

        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower()
        ascii_text = re.sub(r"[^a-z0-9&+\s'-]", " ", ascii_text)
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        ascii_text = ascii_text.replace("france", "").replace("store", "").replace("boutique", "")
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        return ascii_text

    @staticmethod
    def _title_case_brand(text: str) -> str:
        tokens = []
        for token in text.split():
            if token in {"h&m", "c&a"}:
                tokens.append(token.upper())
            else:
                tokens.append(token.capitalize())
        return " ".join(tokens) if tokens else text

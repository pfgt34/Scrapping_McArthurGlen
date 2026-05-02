"""McArthurGlen-specific discovery and scraping helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from .config import DEFAULT_BRAND_ALIASES
from .models import MallProfile, ScrapedStore
from .scraper_engine import GenericMallScraper

MCARTHURGLEN_PORTFOLIO_URL = "https://www.mcarthurglen.com/en/outlets/"

CENTER_LINK_RE = re.compile(r"/en/outlets/(?P<country>[a-z]{2})/designer-outlet-[^/]+/?$")
STORE_LINK_RE = re.compile(
    r"/en/outlets/(?P<country>[a-z]{2})/designer-outlet-[^/]+/stores/(?P<slug>[^/?#]+)/?$"
)

MCARTHURGLEN_PORTFOLIO_PROFILE = MallProfile(
    mall_id="mcarthurglen-portfolio",
    mall_name="McArthurGlen Portfolio",
    start_url=MCARTHURGLEN_PORTFOLIO_URL,
    store_card_css='a[href*="/en/outlets/"][href*="designer-outlet-"]',
    store_name_css='a[href*="/en/outlets/"][href*="designer-outlet-"]',
    store_url_css='a[href*="/en/outlets/"][href*="designer-outlet-"]',
    next_page_css=None,
    requires_javascript=False,
    store_card_xpath=None,
    store_name_xpath=None,
    store_url_xpath=None,
    brand_aliases=DEFAULT_BRAND_ALIASES,
)


@dataclass(frozen=True, slots=True)
class McArthurGlenCenter:
    """Represents one McArthurGlen center discovered from the portfolio page."""

    mall_id: str
    mall_name: str
    country_code: str
    center_url: str
    stores_url: str


def build_center_profile(center: McArthurGlenCenter) -> MallProfile:
    """Build a mall profile for one McArthurGlen center."""

    return MallProfile(
        mall_id=center.mall_id,
        mall_name=center.mall_name,
        start_url=center.stores_url,
        store_card_css='a[href*="/stores/"]',
        store_name_css='a[href*="/stores/"]',
        store_url_css='a[href*="/stores/"]',
        next_page_css=None,
        requires_javascript=False,
        store_card_xpath=None,
        store_name_xpath=None,
        store_url_xpath=None,
        brand_aliases=DEFAULT_BRAND_ALIASES,
    )


def build_center_profile_from_url(center_url: str) -> MallProfile:
    """Build a mall profile from a McArthurGlen center URL."""

    normalized_center_url = center_url.rstrip("/") + "/"
    if normalized_center_url.endswith("/stores/"):
        normalized_center_url = normalized_center_url[: -len("stores/")]

    parsed_url = urlparse(normalized_center_url)
    path_parts = [part for part in parsed_url.path.split("/") if part]
    if len(path_parts) < 4:
        raise ValueError(f"Unsupported McArthurGlen center URL: {center_url}")

    country_code = path_parts[2]
    center_slug = path_parts[3]
    center_name = _slug_to_display_name(center_slug)
    mall_id = f"mcarthurglen-{country_code}-{center_slug}"
    stores_url = urljoin(normalized_center_url, "stores/")
    center = McArthurGlenCenter(
        mall_id=mall_id,
        mall_name=f"McArthurGlen {center_name}",
        country_code=country_code,
        center_url=normalized_center_url,
        stores_url=stores_url,
    )
    return build_center_profile(center)


def discover_centers(portfolio_html: str, base_url: str = MCARTHURGLEN_PORTFOLIO_URL) -> list[McArthurGlenCenter]:
    """Discover McArthurGlen centers from the portfolio listing page."""

    soup = BeautifulSoup(portfolio_html, "html.parser")
    centers: list[McArthurGlenCenter] = []
    seen_urls: set[str] = set()

    for anchor in soup.select('a[href*="/en/outlets/"][href*="designer-outlet-"]'):
        href = anchor.get("href")
        if not href:
            continue

        match = CENTER_LINK_RE.search(href)
        if not match:
            continue

        center_url = urljoin(base_url, href)
        if center_url in seen_urls:
            continue

        seen_urls.add(center_url)
        country_code = match.group("country")
        center_slug = _extract_center_slug(center_url)
        center_name = _extract_center_name(anchor, center_slug)
        mall_id = f"mcarthurglen-{country_code}-{center_slug}"
        stores_url = urljoin(center_url.rstrip("/") + "/", "stores/")
        centers.append(
            McArthurGlenCenter(
                mall_id=mall_id,
                mall_name=f"McArthurGlen {center_name}",
                country_code=country_code,
                center_url=center_url.rstrip("/") + "/",
                stores_url=stores_url,
            )
        )

    return centers


class McArthurGlenScraper(GenericMallScraper):
    """McArthurGlen-specific scraper for outlet store listings."""

    def parse_store_records(
        self,
        html: str,
        source_url: str,
        crawl_date: date,
        source_mode: str,
    ) -> list[ScrapedStore]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[ScrapedStore] = []
        seen_keys: set[str] = set()

        for anchor in soup.select('a[href*="/stores/"]'):
            href = anchor.get("href")
            if not href:
                continue

            match = STORE_LINK_RE.search(href)
            if not match:
                continue

            raw_name = self._extract_store_name(anchor)
            if not raw_name:
                raw_name = _slug_to_display_name(match.group("slug"))

            store_url = urljoin(source_url, href)
            normalized_name = self._normalize_brand_name(raw_name)
            card_container = self._extract_card_container(anchor)
            card_text = self._extract_card_text(card_container)
            description, categories, badges = self._parse_card_metadata(card_text, raw_name)
            record_key = f"{normalized_name.lower().strip()}|{store_url.lower().strip()}"
            if record_key in seen_keys:
                continue

            seen_keys.add(record_key)
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
                    description=description,
                    categories=categories,
                    badges=badges,
                    card_text=card_text,
                )
            )

        if not records:
            raise ValueError(
                f"No McArthurGlen stores found for {self.profile.mall_name} on {source_url}"
            )

        return records

    @staticmethod
    def _extract_store_name(anchor: Tag) -> str:
        """Extract a clean store name from a store anchor."""

        text = " ".join(anchor.stripped_strings)
        text = re.sub(
            r"\b(new opening|temporarily closed|coming soon|closed)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _extract_card_container(anchor: Tag) -> Tag:
        """Find the most relevant container for a store card."""

        candidate: Tag = anchor
        for parent in anchor.parents:
            if not isinstance(parent, Tag):
                break
            if parent.name in {"article", "li", "div"}:
                parent_text = " ".join(parent.stripped_strings)
                if len(parent_text) >= max(len(anchor.get_text(" ", strip=True)) + 20, 60):
                    candidate = parent
                    if len(parent_text) > 120:
                        return candidate
        return candidate

    @staticmethod
    def _extract_card_text(container: Tag) -> str:
        """Serialize the visible card text into a compact string."""

        text = " \n ".join(container.stripped_strings)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _parse_card_metadata(card_text: str, store_name: str) -> tuple[str, list[str], list[str]]:
        """Extract description, categories, and badges from a card text blob."""

        if not card_text:
            return "", [], []

        normalized_text = card_text.replace(store_name, "", 1).strip()
        normalized_text = re.sub(r"\s+", " ", normalized_text)

        badges: list[str] = []
        badge_patterns = [
            (r"\bnew opening\b", "New opening"),
            (r"\btemporarily closed\b", "Temporarily closed"),
            (r"\bcoming soon\b", "Coming soon"),
            (r"\bavailable within\b", "Available within"),
        ]
        for pattern, label in badge_patterns:
            if re.search(pattern, normalized_text, flags=re.IGNORECASE):
                badges.append(label)

        if re.search(r"\b\d+ more offer", normalized_text, flags=re.IGNORECASE):
            badges.append("More offers")

        description = ""
        categories: list[str] = []
        parts = [part.strip() for part in re.split(r"\s{2,}|\n", card_text) if part.strip()]

        candidate_lines = [part for part in parts if store_name.lower() not in part.lower()]
        if candidate_lines:
            # Prefer the first substantive sentence as description.
            for part in candidate_lines:
                if any(token in part.lower() for token in ("available within", "new opening", "temporarily closed", "more offer")):
                    continue
                if len(part) > 35:
                    description = part
                    break

            for part in candidate_lines:
                if part == description:
                    continue
                if any(token in part.lower() for token in ("available within", "new opening", "temporarily closed")):
                    continue
                if "," in part or " & " in part or "/" in part:
                    categories = [item.strip() for item in re.split(r",|\|", part) if item.strip()]
                    if categories:
                        break

        return description, categories, badges


def _extract_center_slug(center_url: str) -> str:
    path_parts = [part for part in urlparse(center_url).path.split("/") if part]
    if len(path_parts) < 4:
        raise ValueError(f"Unsupported McArthurGlen center URL: {center_url}")
    return path_parts[3]


def _extract_center_name(anchor: Tag, center_slug: str) -> str:
    text = " ".join(anchor.stripped_strings)
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        return text
    return _slug_to_display_name(center_slug)


def _slug_to_display_name(slug: str) -> str:
    cleaned_slug = slug.replace("designer-outlet-", "")
    cleaned_slug = cleaned_slug.replace("-", " ").strip()
    if not cleaned_slug:
        return "McArthurGlen Center"
    return " ".join(token.capitalize() for token in cleaned_slug.split())

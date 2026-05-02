"""Scraping framework for mall mapping and time-based change detection."""

from .config import WESTFIELD_LIKE_PROFILE, ScraperRuntimeConfig
from .models import MallProfile, ScrapeRunResult, ScrapedStore
from .mcarthurglen import MCARTHURGLEN_PORTFOLIO_URL, McArthurGlenScraper

__all__ = [
    "MallProfile",
    "ScrapeRunResult",
    "ScrapedStore",
    "ScraperRuntimeConfig",
    "MCARTHURGLEN_PORTFOLIO_URL",
    "McArthurGlenScraper",
    "WESTFIELD_LIKE_PROFILE",
]

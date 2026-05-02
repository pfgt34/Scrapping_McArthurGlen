"""Pipeline orchestrator for the mall scraping framework."""

from __future__ import annotations

import argparse
from datetime import date

from .config import WESTFIELD_LIKE_PROFILE, ScraperRuntimeConfig, setup_logging
from .models import MallProfile
from .processor import StoreProcessor
from .scraper_engine import GenericMallScraper, ScraperError
from .mcarthurglen import (
    MCARTHURGLEN_PORTFOLIO_URL,
    MCARTHURGLEN_PORTFOLIO_PROFILE,
    McArthurGlenScraper,
    build_center_profile_from_url,
    discover_centers,
)
from .provence_ui import run_provence_dashboard


def _build_profile(mall_id: str, start_url: str) -> MallProfile:
    """Create a profile instance from the default template."""

    return MallProfile(
        mall_id=mall_id,
        mall_name=WESTFIELD_LIKE_PROFILE.mall_name,
        start_url=start_url,
        store_card_css=WESTFIELD_LIKE_PROFILE.store_card_css,
        store_name_css=WESTFIELD_LIKE_PROFILE.store_name_css,
        store_url_css=WESTFIELD_LIKE_PROFILE.store_url_css,
        next_page_css=WESTFIELD_LIKE_PROFILE.next_page_css,
        requires_javascript=WESTFIELD_LIKE_PROFILE.requires_javascript,
        store_card_xpath=WESTFIELD_LIKE_PROFILE.store_card_xpath,
        store_name_xpath=WESTFIELD_LIKE_PROFILE.store_name_xpath,
        store_url_xpath=WESTFIELD_LIKE_PROFILE.store_url_xpath,
        brand_aliases=WESTFIELD_LIKE_PROFILE.brand_aliases,
    )


def run_pipeline(
    profile: MallProfile = WESTFIELD_LIKE_PROFILE,
    runtime_config: ScraperRuntimeConfig | None = None,
    scraper_cls: type[GenericMallScraper] = GenericMallScraper,
) -> None:
    """Execute the end-to-end ETL pipeline for one mall profile."""

    logger = setup_logging("mall_pipeline")
    runtime_config = runtime_config or ScraperRuntimeConfig()
    scraper = scraper_cls(profile=profile, runtime_config=runtime_config, logger=logger)
    processor = StoreProcessor(brand_aliases=profile.brand_aliases)

    logger.info("Starting crawl for %s", profile.mall_name)
    result = scraper.run()
    current_frame = processor.records_to_dataframe(result.records)
    current_snapshot_path = processor.save_snapshot(
        frame=current_frame,
        mall_id=profile.mall_id,
        crawl_date=result.crawl_date,
    )

    previous_frame = processor.load_previous_snapshot(
        mall_id=profile.mall_id,
        current_crawl_date=result.crawl_date,
    )
    previous_crawl_date = None
    if not previous_frame.empty and "crawl_date" in previous_frame.columns:
        try:
            previous_crawl_date = date.fromisoformat(str(previous_frame["crawl_date"].iloc[0]))
        except Exception:  # noqa: BLE001
            previous_crawl_date = None

    diff = processor.compute_diff(
        previous_frame=previous_frame,
        current_frame=current_frame,
        mall_id=profile.mall_id,
        crawl_date=result.crawl_date,
        previous_crawl_date=previous_crawl_date,
    )
    diff_paths = processor.save_diff(diff)

    logger.info(
        "Completed pipeline for %s | stores=%s | openings=%s | closures=%s | snapshot=%s",
        profile.mall_name,
        diff.summary["current_total"],
        diff.summary["openings"],
        diff.summary["closures"],
        current_snapshot_path,
    )
    logger.info("Diff files written: %s, %s, %s", *diff_paths)


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description="Mall scraping pipeline")
    parser.add_argument(
        "--mall-id",
        default=WESTFIELD_LIKE_PROFILE.mall_id,
        help="Mall technical identifier",
    )
    parser.add_argument(
        "--start-url",
        default=WESTFIELD_LIKE_PROFILE.start_url,
        help="Mall store listing URL",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Selenium in headless mode",
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=3,
        help="Number of retry attempts per page",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Fetch timeout in seconds",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=25,
        help="Maximum number of pages to crawl",
    )
    parser.add_argument(
        "--center-url",
        default="",
        help="Specific McArthurGlen center URL to crawl (its /stores/ page will be used)",
    )
    parser.add_argument(
        "--mcarthurglen-portfolio",
        action="store_true",
        help="Discover all McArthurGlen centers from the portfolio page and crawl each one",
    )
    parser.add_argument(
        "--provence-ui",
        action="store_true",
        help="Launch the local frontend for McArthurGlen Provence",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        default=8050,
        help="Port used by the Provence frontend",
    )
    parser.add_argument(
        "--refresh-frontend-data",
        action="store_true",
        help="Force a fresh scrape before rendering the Provence frontend",
    )
    return parser


def run_mcarthurglen_portfolio(runtime_config: ScraperRuntimeConfig) -> None:
    """Discover all McArthurGlen centers and crawl each one."""

    logger = setup_logging("mall_pipeline")
    portfolio_scraper = McArthurGlenScraper(
        profile=MCARTHURGLEN_PORTFOLIO_PROFILE,
        runtime_config=runtime_config,
        logger=logger,
    )
    html, _ = portfolio_scraper.fetch_page_html(MCARTHURGLEN_PORTFOLIO_URL)
    centers = discover_centers(html)
    logger.info("Discovered %s McArthurGlen centers", len(centers))

    for center in centers:
        center_profile = build_center_profile_from_url(center.center_url)
        logger.info("Crawling McArthurGlen center: %s", center_profile.mall_name)
        run_pipeline(
            profile=center_profile,
            runtime_config=runtime_config,
            scraper_cls=McArthurGlenScraper,
        )


def main() -> None:
    """CLI entry point for the mall scraping pipeline."""

    args = build_arg_parser().parse_args()
    runtime_config = ScraperRuntimeConfig(
        timeout_seconds=args.timeout_seconds,
        retry_attempts=args.retry_attempts,
        retry_backoff_seconds=1.5,
        headless=args.headless,
        max_pages=args.max_pages,
    )

    if args.provence_ui:
        run_provence_dashboard(port=args.frontend_port, force_refresh=args.refresh_frontend_data)
        return

    if args.mcarthurglen_portfolio:
        run_mcarthurglen_portfolio(runtime_config=runtime_config)
        return

    try:
        if args.center_url:
            profile = build_center_profile_from_url(args.center_url)
            run_pipeline(
                profile=profile,
                runtime_config=runtime_config,
                scraper_cls=McArthurGlenScraper,
            )
            return

        profile = _build_profile(mall_id=args.mall_id, start_url=args.start_url)
        run_pipeline(profile=profile, runtime_config=runtime_config)
    except ScraperError as exc:
        logger = setup_logging("mall_pipeline")
        logger.exception("Pipeline failed: %s", exc)
        raise


if __name__ == "__main__":
    main()

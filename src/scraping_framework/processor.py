"""Transformation and diffing logic for mall store snapshots."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from .config import PROCESSED_DATA_DIR
from .models import DiffResult, ScrapedStore


@dataclass(slots=True)
class StoreProcessor:
    """Transforms crawled records and computes daily changes."""

    brand_aliases: Mapping[str, str]
    processed_dir: Path = PROCESSED_DATA_DIR

    def records_to_dataframe(self, records: Iterable[ScrapedStore]) -> pd.DataFrame:
        """Convert records to a normalized pandas DataFrame."""

        rows = [record.to_dict() for record in records]
        if not rows:
            return pd.DataFrame(
                columns=[
                    "mall_id",
                    "mall_name",
                    "crawl_date",
                    "store_name_raw",
                    "store_name_normalized",
                    "source_url",
                    "store_url",
                    "source_mode",
                    "store_key",
                ]
            )

        frame = pd.DataFrame(rows)
        frame["store_name_normalized"] = frame["store_name_raw"].apply(
            lambda value: self.normalize_brand_name(value)
        )
        frame["store_key"] = frame.apply(self._build_store_key, axis=1)
        frame["crawl_date"] = pd.to_datetime(frame["crawl_date"]).dt.date
        return frame

    def normalize_brand_name(self, raw_name: str) -> str:
        """Normalize raw store names to a canonical brand label.

        Args:
            raw_name: Store name captured from the site.

        Returns:
            Canonicalized brand name.
        """

        if not raw_name:
            return ""

        normalized_key = self._normalize_key(raw_name)
        alias_map = {self._normalize_key(key): value for key, value in self.brand_aliases.items()}
        if normalized_key in alias_map:
            return alias_map[normalized_key]

        cleaned = self._remove_suffixes(normalized_key)
        if cleaned in alias_map:
            return alias_map[cleaned]

        return self._title_case_brand(cleaned or normalized_key)

    def save_snapshot(self, frame: pd.DataFrame, mall_id: str, crawl_date: date) -> Path:
        """Persist a daily snapshot in parquet-friendly CSV format."""

        target_dir = self.processed_dir / mall_id
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = target_dir / f"{crawl_date.isoformat()}.csv"
        frame.to_csv(snapshot_path, index=False, encoding="utf-8")
        return snapshot_path

    def load_previous_snapshot(
        self,
        mall_id: str,
        current_crawl_date: date,
    ) -> pd.DataFrame:
        """Load the most recent snapshot before the current crawl date."""

        target_dir = self.processed_dir / mall_id
        if not target_dir.exists():
            return pd.DataFrame()

        candidate_files = sorted(target_dir.glob("*.csv"))
        previous_files = [path for path in candidate_files if path.stem < current_crawl_date.isoformat()]
        if not previous_files:
            return pd.DataFrame()

        return pd.read_csv(previous_files[-1])

    def compute_diff(
        self,
        previous_frame: pd.DataFrame,
        current_frame: pd.DataFrame,
        mall_id: str,
        crawl_date: date,
        previous_crawl_date: date | None = None,
    ) -> DiffResult:
        """Compute openings and closures by comparing two snapshots."""

        previous_frame = previous_frame.copy() if not previous_frame.empty else pd.DataFrame()
        current_frame = current_frame.copy() if not current_frame.empty else pd.DataFrame()

        if previous_frame.empty:
            openings = current_frame.to_dict(orient="records")
            closures: list[dict[str, str]] = []
            unchanged: list[dict[str, str]] = []
        else:
            previous_frame["store_key"] = previous_frame.apply(self._build_store_key, axis=1)
            current_frame["store_key"] = current_frame.apply(self._build_store_key, axis=1)

            previous_keys = set(previous_frame["store_key"].astype(str))
            current_keys = set(current_frame["store_key"].astype(str))

            openings = current_frame[current_frame["store_key"].astype(str).isin(current_keys - previous_keys)]
            closures = previous_frame[previous_frame["store_key"].astype(str).isin(previous_keys - current_keys)]
            unchanged = current_frame[current_frame["store_key"].astype(str).isin(previous_keys & current_keys)]

            openings = openings.to_dict(orient="records")
            closures = closures.to_dict(orient="records")
            unchanged = unchanged.to_dict(orient="records")

        summary = {
            "openings": len(openings),
            "closures": len(closures),
            "unchanged": len(unchanged),
            "current_total": len(current_frame),
            "previous_total": len(previous_frame),
        }
        return DiffResult(
            mall_id=mall_id,
            crawl_date=crawl_date,
            previous_crawl_date=previous_crawl_date,
            openings=openings,
            closures=closures,
            unchanged=unchanged,
            summary=summary,
        )

    def save_diff(self, diff: DiffResult) -> tuple[Path, Path, Path]:
        """Persist diff results as CSV files for audit and downstream use."""

        target_dir = self.processed_dir / diff.mall_id / diff.crawl_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)

        openings_path = target_dir / "openings.csv"
        closures_path = target_dir / "closures.csv"
        unchanged_path = target_dir / "unchanged.csv"

        pd.DataFrame(diff.openings).to_csv(openings_path, index=False, encoding="utf-8")
        pd.DataFrame(diff.closures).to_csv(closures_path, index=False, encoding="utf-8")
        pd.DataFrame(diff.unchanged).to_csv(unchanged_path, index=False, encoding="utf-8")

        return openings_path, closures_path, unchanged_path

    def _build_store_key(self, row: pd.Series) -> str:
        normalized_name = str(row.get("store_name_normalized", "")).strip().lower()
        normalized_url = str(row.get("store_url", "")).strip().lower()
        if not normalized_url:
            return normalized_name
        return f"{normalized_name}|{normalized_url}"

    @staticmethod
    def _normalize_key(text: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower().strip()
        ascii_text = re.sub(r"[^a-z0-9&+\s'-]", " ", ascii_text)
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        return ascii_text

    @staticmethod
    def _remove_suffixes(text: str) -> str:
        suffixes = {
            "france",
            "fr",
            "store",
            "stores",
            "boutique",
            "shop",
            "official",
            "europe",
            "paris",
        }
        tokens = [token for token in text.split() if token not in suffixes]
        return " ".join(tokens).strip()

    @staticmethod
    def _title_case_brand(text: str) -> str:
        if not text:
            return text

        special_cases = {"h&m": "H&M", "c&a": "C&A", "uniqlo": "UNIQLO"}
        if text in special_cases:
            return special_cases[text]

        return " ".join(token.capitalize() for token in text.split())

"""CLI job: run full HS ingestion workflow."""

from __future__ import annotations

import argparse

from pathlib import Path

from hs_tracker.config import load_config
from hs_tracker.db import connect, init_db
from hs_tracker.ingestion.clinicaltrials import refresh_clinicaltrials
from hs_tracker.ingestion.decks import scan_all_sponsors
from hs_tracker.ingestion.sources import scan_sponsor_sources
from hs_tracker.service import ensure_default_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full HS ingestion workflow")
    parser.add_argument("--rolling-years", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument(
        "--source-config",
        default="data/source_configs/sponsor_sources.json",
    )
    parser.add_argument("--deck-root", default="data/pipeline_decks")
    parser.add_argument("--skip-ctgov", action="store_true")
    parser.add_argument("--skip-sources", action="store_true")
    parser.add_argument("--skip-decks", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    rolling_years = args.rolling_years or cfg.rolling_years

    summary: dict[str, dict[str, int]] = {}
    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)

        if not args.skip_ctgov:
            summary["clinicaltrials"] = refresh_clinicaltrials(
                conn,
                rolling_years=rolling_years,
                page_size=args.page_size,
                max_pages=args.max_pages,
            )

        if not args.skip_sources:
            summary["sponsor_sources"] = scan_sponsor_sources(
                conn,
                config_path=Path(args.source_config),
            )

        if not args.skip_decks:
            summary["pipeline_decks"] = scan_all_sponsors(
                conn,
                base_dir=Path(args.deck_root),
            )

    print(summary)


if __name__ == "__main__":
    main()

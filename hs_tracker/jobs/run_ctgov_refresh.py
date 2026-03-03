"""CLI job: refresh trials from ClinicalTrials.gov."""

from __future__ import annotations

import argparse

from hs_tracker.config import load_config
from hs_tracker.db import connect, init_db
from hs_tracker.ingestion.clinicaltrials import refresh_clinicaltrials
from hs_tracker.service import ensure_default_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh HS trials from ClinicalTrials.gov")
    parser.add_argument("--rolling-years", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    cfg = load_config()
    rolling_years = args.rolling_years or cfg.rolling_years

    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)
        stats = refresh_clinicaltrials(
            conn,
            rolling_years=rolling_years,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )

    print(stats)


if __name__ == "__main__":
    main()

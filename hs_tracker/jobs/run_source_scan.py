"""CLI job: scan sponsor press-release and pipeline-page sources."""

from __future__ import annotations

import argparse
from pathlib import Path

from hs_tracker.config import load_config
from hs_tracker.db import connect, init_db
from hs_tracker.ingestion.sources import scan_sponsor_sources
from hs_tracker.service import ensure_default_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan sponsor press-release feeds/pages and pipeline pages"
    )
    parser.add_argument(
        "--config",
        default="data/source_configs/sponsor_sources.json",
        help="JSON config with sponsor source scraping rules",
    )
    args = parser.parse_args()

    cfg = load_config()
    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)
        stats = scan_sponsor_sources(conn, config_path=Path(args.config))

    print(stats)


if __name__ == "__main__":
    main()

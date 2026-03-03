"""CLI job: scan sponsor pipeline decks."""

from __future__ import annotations

import argparse
from pathlib import Path

from hs_tracker.config import load_config
from hs_tracker.db import connect, init_db
from hs_tracker.ingestion.decks import scan_all_sponsors
from hs_tracker.service import ensure_default_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan sponsor pipeline decks for HS signals")
    parser.add_argument(
        "--deck-root",
        default="data/pipeline_decks",
        help="Folder containing one subfolder per sponsor with deck PDFs",
    )
    args = parser.parse_args()

    cfg = load_config()
    with connect(cfg.db_path) as conn:
        init_db(conn)
        ensure_default_settings(conn)
        stats = scan_all_sponsors(conn, base_dir=Path(args.deck_root))

    print(stats)


if __name__ == "__main__":
    main()

"""Runtime configuration for HS tracker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hs_tracker.constants import DEFAULT_ROLLING_YEARS


@dataclass(frozen=True)
class HSConfig:
    db_path: Path
    rolling_years: int


def load_config() -> HSConfig:
    default_db = Path("data") / "hs_tracker.db"
    db_path = Path(os.getenv("HS_TRACKER_DB_PATH", default_db.as_posix()))
    rolling_years = int(os.getenv("HS_TRACKER_ROLLING_YEARS", str(DEFAULT_ROLLING_YEARS)))
    return HSConfig(db_path=db_path, rolling_years=rolling_years)

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalSettings:
    days_per_month: float = 365.25 / 12.0
    week_ending_day: int = 6  # Sunday default
    max_sites: int = 500
    max_duration_days: int = 3650

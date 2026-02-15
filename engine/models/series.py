from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailySeries:
    incident: dict[date, float]
    cumulative: dict[date, float]

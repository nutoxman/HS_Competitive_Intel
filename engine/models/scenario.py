from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from engine.models.types import GoalType, State


DriverType = Literal["Fixed Sites", "Fixed Timeline"]


@dataclass(frozen=True)
class ScenarioInputs:
    name: str

    goal_type: GoalType
    goal_n: int

    screen_fail_rate: float
    discontinuation_rate: float

    period_type: State
    driver: DriverType

    fsfv: date
    lsfv: date | None  # required if Fixed Timeline
    sites: int | None  # required if Fixed Sites

    lag_sr_days: int
    lag_rc_days: int

    sar_pct: list[float]  # 6 values
    rr_per_site_per_month: list[float]  # 6 values

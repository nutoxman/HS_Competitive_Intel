from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GoalType = Literal["Randomized", "Completed"]
State = Literal["Screened", "Randomized", "Completed"]


@dataclass(frozen=True)
class Targets:
    screened: float
    randomized: float
    completed: float


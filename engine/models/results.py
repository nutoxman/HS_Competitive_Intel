from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from engine.core.solvers import SolveResult
from engine.core.derive_states import StateSeriesSet
from engine.core.primary import PrimaryDaily
from engine.models.types import Targets


@dataclass(frozen=True)
class DerivedTimelines:
    screened_fsfv: date
    screened_lsfv: date
    randomized_fsfv: date
    randomized_lsfv: date
    completed_fsfv: date
    completed_lslv: date


@dataclass(frozen=True)
class ScenarioRunResult:
    inputs_name: str
    targets: Targets
    solve: SolveResult
    timelines: DerivedTimelines

    primary: PrimaryDaily
    states: StateSeriesSet

    milestones_time: dict[str, list[dict]]      # keys: "Screened"/"Randomized"/"Completed"
    milestones_target: dict[str, list[dict]]    # keys same as above

    buckets: dict[str, dict[str, list[dict]]]
    # buckets[bucket_type][state] -> list[dict]
    # bucket_type in {"year","quarter","month","week"}

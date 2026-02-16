from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from engine.core.series_ops import cumulative_from_incident
from engine.core.targets import ValidationError
from engine.core.derive_states import StateSeriesSet
from engine.models.series import DailySeries


@dataclass(frozen=True)
class AllocationResult:
    allocations: dict[str, int]
    weights: dict[str, float]


def allocate_goal(goal_n: int, weights: dict[str, float]) -> AllocationResult:
    """
    Allocate integer targets across keys proportional to weights.
    Uses largest remainder method to ensure sum == goal_n.
    """
    if goal_n <= 0:
        raise ValidationError("Goal N must be > 0.")
    if not weights:
        raise ValidationError("No weights provided for allocation.")

    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValidationError("Total allocation weight must be > 0.")

    raw = {k: goal_n * (w / total_weight) for k, w in weights.items()}
    floors = {k: int(v) for k, v in raw.items()}
    remainder = goal_n - sum(floors.values())

    # Distribute remainder by largest fractional parts
    fracs = sorted(((raw[k] - floors[k], k) for k in raw), reverse=True)
    alloc = dict(floors)
    for i in range(remainder):
        _, k = fracs[i % len(fracs)]
        alloc[k] += 1

    return AllocationResult(allocations=alloc, weights=weights)


def _sum_incident(series_list: Iterable[dict[date, float]]) -> dict[date, float]:
    out: dict[date, float] = {}
    for series in series_list:
        for d, v in series.items():
            out[d] = out.get(d, 0.0) + float(v)
    return out


def aggregate_states(state_sets: Iterable[StateSeriesSet]) -> StateSeriesSet:
    """
    Aggregate state series across countries by summing incident by date and
    recomputing cumulative (to preserve monotonicity).
    """
    state_sets = list(state_sets)
    if not state_sets:
        empty = DailySeries(incident={}, cumulative={})
        return StateSeriesSet(screened=empty, randomized=empty, completed=empty)

    scr_inc = _sum_incident(s.screened.incident for s in state_sets)
    rand_inc = _sum_incident(s.randomized.incident for s in state_sets)
    comp_inc = _sum_incident(s.completed.incident for s in state_sets)

    screened = DailySeries(incident=scr_inc, cumulative=cumulative_from_incident(scr_inc))
    randomized = DailySeries(incident=rand_inc, cumulative=cumulative_from_incident(rand_inc))
    completed = DailySeries(incident=comp_inc, cumulative=cumulative_from_incident(comp_inc))

    return StateSeriesSet(screened=screened, randomized=randomized, completed=completed)

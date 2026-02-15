from __future__ import annotations

from engine.models.types import State
from engine.models.types import Targets


def get_target_for_state(targets: Targets, state: State) -> float:
    if state == "Screened":
        return targets.screened
    if state == "Randomized":
        return targets.randomized
    if state == "Completed":
        return targets.completed
    raise ValueError(f"Unsupported state: {state!r}")

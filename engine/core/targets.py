from __future__ import annotations

from engine.models.types import GoalType, Targets


class ValidationError(ValueError):
    """Raised when scenario inputs are invalid."""


def _validate_rate(name: str, value: float) -> None:
    if not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a number.")
    if value < 0 or value >= 1:
        raise ValidationError(f"{name} must be in [0, 1). Got {value!r}.")


def derive_targets(goal_type: GoalType, goal_n: int, screen_fail_rate: float, discontinuation_rate: float) -> Targets:
    """
    Derive Screened/Randomized/Completed targets from a single global goal.

    Rules (authoritative):
    - Keep fractional internally.
    - goal_n must be > 0.
    - Rates must be in [0,1).
    """
    if goal_n is None or int(goal_n) != goal_n or goal_n <= 0:
        raise ValidationError(f"Goal N must be a positive integer. Got {goal_n!r}.")

    _validate_rate("Screen fail rate", float(screen_fail_rate))
    _validate_rate("Discontinuation rate", float(discontinuation_rate))

    sfr = float(screen_fail_rate)
    dr = float(discontinuation_rate)

    if goal_type == "Randomized":
        randomized = float(goal_n)
        screened = randomized / (1.0 - sfr)
        completed = randomized * (1.0 - dr)
        return Targets(screened=screened, randomized=randomized, completed=completed)

    if goal_type == "Completed":
        completed = float(goal_n)
        randomized = completed / (1.0 - dr)
        screened = randomized / (1.0 - sfr)
        return Targets(screened=screened, randomized=randomized, completed=completed)

    raise ValidationError(f"Unsupported goal_type: {goal_type!r}")

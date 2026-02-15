from __future__ import annotations

from dataclasses import dataclass

from engine.core.targets import ValidationError
from engine.core.series_ops import cumulative_from_incident, scale_series, shift_series
from engine.models.series import DailySeries
from engine.models.types import State


@dataclass(frozen=True)
class StateSeriesSet:
    screened: DailySeries
    randomized: DailySeries
    completed: DailySeries


def derive_states_from_primary(
    period_type: State,
    primary_new: dict,
    screen_fail_rate: float,
    discontinuation_rate: float,
    lag_sr_days: int,
    lag_rc_days: int,
) -> StateSeriesSet:
    """
    Derive daily incident series for Screened/Randomized/Completed from the primary incident stream.

    Rules (authoritative):
    - Uses shift + multiply/divide derivation.
    - Applies uncertainty by running this function separately on banded primary streams.
    - Keeps fractional values internally (no rounding).
    """
    # Validate
    if lag_sr_days < 0 or lag_rc_days < 0:
        raise ValidationError("Lags must be >= 0.")
    if screen_fail_rate < 0 or screen_fail_rate >= 1:
        raise ValidationError("Screen fail rate must be in [0,1).")
    if discontinuation_rate < 0 or discontinuation_rate >= 1:
        raise ValidationError("Discontinuation rate must be in [0,1).")

    sfr = float(screen_fail_rate)
    dr = float(discontinuation_rate)

    primary_incident = {d: float(v) for d, v in primary_new.items()}

    if period_type == "Randomized":
        rand = primary_incident
        scr = shift_series(scale_series(rand, 1.0 / (1.0 - sfr)), days=-lag_sr_days)
        comp = shift_series(scale_series(rand, (1.0 - dr)), days=+lag_rc_days)

    elif period_type == "Screened":
        scr = primary_incident
        rand = shift_series(scale_series(scr, (1.0 - sfr)), days=+lag_sr_days)
        comp = shift_series(scale_series(scr, (1.0 - sfr) * (1.0 - dr)), days=+(lag_sr_days + lag_rc_days))

    elif period_type == "Completed":
        comp = primary_incident
        rand = shift_series(scale_series(comp, 1.0 / (1.0 - dr)), days=-lag_rc_days)
        scr = shift_series(scale_series(rand, 1.0 / (1.0 - sfr)), days=-lag_sr_days)

    else:
        raise ValidationError(f"Unsupported period_type: {period_type!r}")

    # Build cumulative
    screened = DailySeries(incident=scr, cumulative=cumulative_from_incident(scr))
    randomized = DailySeries(incident=rand, cumulative=cumulative_from_incident(rand))
    completed = DailySeries(incident=comp, cumulative=cumulative_from_incident(comp))

    return StateSeriesSet(screened=screened, randomized=randomized, completed=completed)

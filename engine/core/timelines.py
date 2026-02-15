from __future__ import annotations

from datetime import date, timedelta

from engine.core.targets import ValidationError
from engine.models.results import DerivedTimelines
from engine.models.types import State


def derive_state_timelines(
    *,
    fsfv: date,
    lsfv: date,
    period_type: State,
    lag_sr_days: int,
    lag_rc_days: int,
) -> DerivedTimelines:
    """
    Derive FSFV/LSFV (and LSLV) for Screened/Randomized/Completed based on primary period and lags.

    FSFV inclusive, LSFV exclusive.
    Completed uses LSLV exclusive as completion window end.
    """
    if lsfv <= fsfv:
        raise ValidationError("LSFV must be after FSFV.")
    if lag_sr_days < 0 or lag_rc_days < 0:
        raise ValidationError("Lags must be >= 0.")

    if period_type == "Screened":
        scr_fsfv, scr_lsfv = fsfv, lsfv
        rand_fsfv = fsfv + timedelta(days=lag_sr_days)
        rand_lsfv = lsfv + timedelta(days=lag_sr_days)
        comp_fsfv = fsfv + timedelta(days=lag_sr_days + lag_rc_days)
        comp_lslv = lsfv + timedelta(days=lag_sr_days + lag_rc_days)

    elif period_type == "Randomized":
        rand_fsfv, rand_lsfv = fsfv, lsfv
        scr_fsfv = fsfv - timedelta(days=lag_sr_days)
        scr_lsfv = lsfv - timedelta(days=lag_sr_days)
        comp_fsfv = fsfv + timedelta(days=lag_rc_days)
        comp_lslv = lsfv + timedelta(days=lag_rc_days)

    elif period_type == "Completed":
        comp_fsfv, comp_lslv = fsfv, lsfv
        rand_fsfv = fsfv - timedelta(days=lag_rc_days)
        rand_lsfv = lsfv - timedelta(days=lag_rc_days)
        scr_fsfv = fsfv - timedelta(days=lag_rc_days + lag_sr_days)
        scr_lsfv = lsfv - timedelta(days=lag_rc_days + lag_sr_days)

    else:
        raise ValidationError(f"Unsupported period_type: {period_type!r}")

    return DerivedTimelines(
        screened_fsfv=scr_fsfv,
        screened_lsfv=scr_lsfv,
        randomized_fsfv=rand_fsfv,
        randomized_lsfv=rand_lsfv,
        completed_fsfv=comp_fsfv,
        completed_lslv=comp_lslv,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from engine.core.targets import ValidationError
from engine.core.interp import interp_piecewise_linear
from engine.models.settings import GlobalSettings


MILESTONE_PCTS = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]


@dataclass(frozen=True)
class PrimaryDaily:
    fsfv: date
    lsfv: date
    sites: int
    new_primary: dict[date, float]       # incident subjects/day
    active_sites: dict[date, float]      # deterministic sites active
    activation_pct: dict[date, float]    # deterministic percent active (0-100)


def _validate_ramp(name: str, values: list[float], allow_negative: bool = False) -> None:
    if len(values) != 6:
        raise ValidationError(f"{name} must have 6 values at 0/20/40/60/80/100%. Got {len(values)}.")
    for v in values:
        if not isinstance(v, (int, float)):
            raise ValidationError(f"{name} values must be numeric. Got {v!r}.")
        if not allow_negative and v < 0:
            raise ValidationError(f"{name} values must be >= 0. Got {v!r}.")


def build_primary_daily(
    fsfv: date,
    lsfv: date,
    sites: int,
    sar_pct: list[float],
    rr_per_site_per_month: list[float],
    settings: GlobalSettings,
    throughput_multiplier: float = 1.0,
) -> PrimaryDaily:
    """
    Build primary daily incident series for t in [FSFV, LSFV).

    - FSFV inclusive; LSFV exclusive.
    - SAR is percent of sites active (0-100) interpolated over time.
    - RR is subjects per site per month interpolated over time.
    - Converts RR to per-day using settings.days_per_month.
    - throughput_multiplier scales incident throughput only (used for uncertainty bands).
    - active_sites and activation_pct are deterministic and not scaled.
    """
    if lsfv <= fsfv:
        raise ValidationError(f"LSFV must be after FSFV. Got fsfv={fsfv!r}, lsfv={lsfv!r}.")
    if sites is None or int(sites) != sites or sites <= 0:
        raise ValidationError(f"Sites must be a positive integer. Got {sites!r}.")
    if settings.days_per_month <= 0:
        raise ValidationError(f"days_per_month must be > 0. Got {settings.days_per_month!r}.")
    if throughput_multiplier < 0:
        # We clamp negative multipliers to 0 to avoid negative throughput.
        throughput_multiplier = 0.0

    _validate_ramp("SAR%", sar_pct)
    _validate_ramp("RR", rr_per_site_per_month)

    # Validate SAR bounds (0-100). We still allow non-monotonic.
    for v in sar_pct:
        if v < 0 or v > 100:
            raise ValidationError(f"SAR% values must be in [0,100]. Got {v!r}.")

    duration_days = (lsfv - fsfv).days
    if duration_days <= 0:
        raise ValidationError("Recruitment duration must be at least 1 day.")

    new_primary: dict[date, float] = {}
    active_sites: dict[date, float] = {}
    activation_pct: dict[date, float] = {}

    for day_idx in range(duration_days):
        d = fsfv + timedelta(days=day_idx)

        # Progress percent from 0..100 inclusive across the interval.
        # Using day_idx/(duration_days-1) gives endpoints exact when duration_days>1.
        if duration_days == 1:
            pct = 0.0
        else:
            pct = (day_idx / (duration_days - 1)) * 100.0

        sar = interp_piecewise_linear(MILESTONE_PCTS, sar_pct, pct)  # in %
        rr = interp_piecewise_linear(MILESTONE_PCTS, rr_per_site_per_month, pct)  # per site per month

        sar = max(0.0, min(100.0, sar))
        rr = max(0.0, rr)

        act_sites = float(sites) * (sar / 100.0)
        per_site_per_day = rr / settings.days_per_month

        inc = act_sites * per_site_per_day * throughput_multiplier
        if inc < 0:
            inc = 0.0

        active_sites[d] = act_sites
        activation_pct[d] = sar
        new_primary[d] = inc

    return PrimaryDaily(
        fsfv=fsfv,
        lsfv=lsfv,
        sites=int(sites),
        new_primary=new_primary,
        active_sites=active_sites,
        activation_pct=activation_pct,
    )

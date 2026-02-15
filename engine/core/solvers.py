from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from engine.core.primary import build_primary_daily
from engine.core.derive_states import derive_states_from_primary
from engine.core.targets import ValidationError
from engine.core.solver_helpers import get_target_for_state
from engine.models.settings import GlobalSettings
from engine.models.types import State, Targets


@dataclass(frozen=True)
class SolveResult:
    solved_sites: int | None = None
    solved_lsfv: date | None = None
    reached: bool = True
    warning: str | None = None


def solve_lsfv_fixed_sites(
    *,
    fsfv: date,
    sites: int,
    period_type: State,
    targets: Targets,
    screen_fail_rate: float,
    discontinuation_rate: float,
    lag_sr_days: int,
    lag_rc_days: int,
    sar_pct: list[float],
    rr_per_site_per_month: list[float],
    settings: GlobalSettings,
    throughput_multiplier: float = 1.0,
) -> SolveResult:
    """
    Fixed Sites: solve for earliest LSFV (exclusive) such that cumulative(primary) >= target(primary).
    Uses day-by-day expansion up to max_duration_days.
    """
    target = get_target_for_state(targets, period_type)

    # Iterate duration 1..max_duration_days
    for dur in range(1, settings.max_duration_days + 1):
        lsfv = fsfv + timedelta(days=dur)

        primary = build_primary_daily(
            fsfv=fsfv,
            lsfv=lsfv,
            sites=sites,
            sar_pct=sar_pct,
            rr_per_site_per_month=rr_per_site_per_month,
            settings=settings,
            throughput_multiplier=throughput_multiplier,
        )

        states = derive_states_from_primary(
            period_type=period_type,
            primary_new=primary.new_primary,
            screen_fail_rate=screen_fail_rate,
            discontinuation_rate=discontinuation_rate,
            lag_sr_days=lag_sr_days,
            lag_rc_days=lag_rc_days,
        )

        # Primary cumulative uses the derived series for that state
        if period_type == "Screened":
            cum = states.screened.cumulative
        elif period_type == "Randomized":
            cum = states.randomized.cumulative
        else:
            cum = states.completed.cumulative

        if not cum:
            continue

        # LSFV exclusive: check last available day (LSFV - 1 day)
        last_day = max(cum.keys())
        if cum[last_day] >= target:
            return SolveResult(solved_lsfv=lsfv)

    return SolveResult(
        solved_lsfv=None,
        reached=False,
        warning="Target unreachable within max_duration_days guardrail.",
    )


def solve_sites_fixed_timeline(
    *,
    fsfv: date,
    lsfv: date,
    period_type: State,
    targets: Targets,
    screen_fail_rate: float,
    discontinuation_rate: float,
    lag_sr_days: int,
    lag_rc_days: int,
    sar_pct: list[float],
    rr_per_site_per_month: list[float],
    settings: GlobalSettings,
    throughput_multiplier: float = 1.0,
) -> SolveResult:
    """
    Fixed Timeline: solve for minimum integer sites such that cumulative(primary) >= target(primary).
    Rounds up (ceil) and checks.
    """
    if lsfv <= fsfv:
        raise ValidationError("LSFV must be after FSFV.")

    target = get_target_for_state(targets, period_type)

    # Quick per-site estimate
    primary_per_site = build_primary_daily(
        fsfv=fsfv,
        lsfv=lsfv,
        sites=1,
        sar_pct=sar_pct,
        rr_per_site_per_month=rr_per_site_per_month,
        settings=settings,
        throughput_multiplier=throughput_multiplier,
    )

    states_per_site = derive_states_from_primary(
        period_type=period_type,
        primary_new=primary_per_site.new_primary,
        screen_fail_rate=screen_fail_rate,
        discontinuation_rate=discontinuation_rate,
        lag_sr_days=lag_sr_days,
        lag_rc_days=lag_rc_days,
    )

    if period_type == "Screened":
        cum_per_site = states_per_site.screened.cumulative
    elif period_type == "Randomized":
        cum_per_site = states_per_site.randomized.cumulative
    else:
        cum_per_site = states_per_site.completed.cumulative

    if not cum_per_site:
        return SolveResult(solved_sites=None, reached=False, warning="No recruitment generated.")

    last_day = max(cum_per_site.keys())
    total_per_site = cum_per_site[last_day]

    if total_per_site <= 0:
        return SolveResult(solved_sites=None, reached=False, warning="No recruitment generated (per-site total is zero).")

    # Initial ceil estimate
    import math
    est = math.ceil(target / total_per_site)
    est = max(1, est)

    if est > settings.max_sites:
        return SolveResult(solved_sites=None, reached=False, warning="Required sites exceed max_sites guardrail.")

    # Verify and increment if needed (should usually pass first try)
    for sites in range(est, settings.max_sites + 1):
        primary = build_primary_daily(
            fsfv=fsfv,
            lsfv=lsfv,
            sites=sites,
            sar_pct=sar_pct,
            rr_per_site_per_month=rr_per_site_per_month,
            settings=settings,
            throughput_multiplier=throughput_multiplier,
        )
        states = derive_states_from_primary(
            period_type=period_type,
            primary_new=primary.new_primary,
            screen_fail_rate=screen_fail_rate,
            discontinuation_rate=discontinuation_rate,
            lag_sr_days=lag_sr_days,
            lag_rc_days=lag_rc_days,
        )

        if period_type == "Screened":
            cum = states.screened.cumulative
        elif period_type == "Randomized":
            cum = states.randomized.cumulative
        else:
            cum = states.completed.cumulative

        last_day = max(cum.keys())
        if cum[last_day] >= target:
            return SolveResult(solved_sites=sites)

    return SolveResult(solved_sites=None, reached=False, warning="Target unreachable within max_sites guardrail.")

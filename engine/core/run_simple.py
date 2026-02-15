from __future__ import annotations

from engine.core.buckets import build_bucket_summary
from engine.core.derive_states import derive_states_from_primary
from engine.core.milestones import incremental_time_milestones, target_milestones
from engine.core.primary import build_primary_daily
from engine.core.solvers import solve_lsfv_fixed_sites, solve_sites_fixed_timeline
from engine.core.targets import derive_targets, ValidationError
from engine.core.timelines import derive_state_timelines
from engine.models.results import ScenarioRunResult
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


def run_simple_scenario(inputs: ScenarioInputs, settings: GlobalSettings) -> ScenarioRunResult:
    # 1) derive targets
    targets = derive_targets(
        inputs.goal_type, inputs.goal_n, inputs.screen_fail_rate, inputs.discontinuation_rate
    )

    # 2) solve if needed to get complete fsfv/lsfv/sites
    if inputs.driver == "Fixed Sites":
        if inputs.sites is None:
            raise ValidationError("Sites required for Fixed Sites driver.")
        solve = solve_lsfv_fixed_sites(
            fsfv=inputs.fsfv,
            sites=inputs.sites,
            period_type=inputs.period_type,
            targets=targets,
            screen_fail_rate=inputs.screen_fail_rate,
            discontinuation_rate=inputs.discontinuation_rate,
            lag_sr_days=inputs.lag_sr_days,
            lag_rc_days=inputs.lag_rc_days,
            sar_pct=inputs.sar_pct,
            rr_per_site_per_month=inputs.rr_per_site_per_month,
            settings=settings,
        )
        if not solve.reached or solve.solved_lsfv is None:
            # Still return partial? For simple mode, we raise to force user fix.
            raise ValidationError(solve.warning or "Unable to solve LSFV.")
        lsfv = solve.solved_lsfv
        sites = inputs.sites

    elif inputs.driver == "Fixed Timeline":
        if inputs.lsfv is None:
            raise ValidationError("LSFV required for Fixed Timeline driver.")
        solve = solve_sites_fixed_timeline(
            fsfv=inputs.fsfv,
            lsfv=inputs.lsfv,
            period_type=inputs.period_type,
            targets=targets,
            screen_fail_rate=inputs.screen_fail_rate,
            discontinuation_rate=inputs.discontinuation_rate,
            lag_sr_days=inputs.lag_sr_days,
            lag_rc_days=inputs.lag_rc_days,
            sar_pct=inputs.sar_pct,
            rr_per_site_per_month=inputs.rr_per_site_per_month,
            settings=settings,
        )
        if not solve.reached or solve.solved_sites is None:
            raise ValidationError(solve.warning or "Unable to solve Sites.")
        lsfv = inputs.lsfv
        sites = solve.solved_sites

    else:
        raise ValidationError(f"Unsupported driver: {inputs.driver!r}")

    # 3) build primary daily series
    primary = build_primary_daily(
        fsfv=inputs.fsfv,
        lsfv=lsfv,
        sites=sites,
        sar_pct=inputs.sar_pct,
        rr_per_site_per_month=inputs.rr_per_site_per_month,
        settings=settings,
    )

    # 4) derive states
    states = derive_states_from_primary(
        period_type=inputs.period_type,
        primary_new=primary.new_primary,
        screen_fail_rate=inputs.screen_fail_rate,
        discontinuation_rate=inputs.discontinuation_rate,
        lag_sr_days=inputs.lag_sr_days,
        lag_rc_days=inputs.lag_rc_days,
    )

    # 5) derive state timelines
    timelines = derive_state_timelines(
        fsfv=inputs.fsfv,
        lsfv=lsfv,
        period_type=inputs.period_type,
        lag_sr_days=inputs.lag_sr_days,
        lag_rc_days=inputs.lag_rc_days,
    )

    # 6) milestones
    milestones_time = {
        "Screened": incremental_time_milestones(timelines.screened_fsfv, timelines.screened_lsfv, states.screened.cumulative),
        "Randomized": incremental_time_milestones(timelines.randomized_fsfv, timelines.randomized_lsfv, states.randomized.cumulative),
        "Completed": incremental_time_milestones(timelines.completed_fsfv, timelines.completed_lslv, states.completed.cumulative),
    }

    milestones_target = {
        "Screened": target_milestones(states.screened.cumulative, targets.screened),
        "Randomized": target_milestones(states.randomized.cumulative, targets.randomized),
        "Completed": target_milestones(states.completed.cumulative, targets.completed),
    }

    # 7) buckets for each state and bucket type
    bucket_types = ["year", "quarter", "month", "week"]
    buckets: dict[str, dict[str, list[dict]]] = {bt: {} for bt in bucket_types}

    for bt in bucket_types:
        buckets[bt]["Screened"] = build_bucket_summary(
            incident=states.screened.incident,
            cumulative=states.screened.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore
            settings=settings,
        )
        buckets[bt]["Randomized"] = build_bucket_summary(
            incident=states.randomized.incident,
            cumulative=states.randomized.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore
            settings=settings,
        )
        buckets[bt]["Completed"] = build_bucket_summary(
            incident=states.completed.incident,
            cumulative=states.completed.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore
            settings=settings,
        )

    return ScenarioRunResult(
        inputs_name=inputs.name,
        targets=targets,
        solve=solve,
        timelines=timelines,
        primary=primary,
        states=states,
        milestones_time=milestones_time,
        milestones_target=milestones_target,
        buckets=buckets,
    )

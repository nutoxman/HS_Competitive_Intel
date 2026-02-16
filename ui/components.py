from __future__ import annotations

from datetime import date
import altair as alt
import pandas as pd
import streamlit as st

from engine.core.run_simple import run_simple_scenario
from engine.core.targets import ValidationError
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


def render_scenario_inputs(scenario_key: str) -> ScenarioInputs:
    """
    Renders inputs for a scenario and returns ScenarioInputs.
    Uses st.session_state to persist values per scenario.
    """

    st.subheader(f"Scenario {scenario_key} Inputs")

    # Initialize session defaults if not present
    if f"{scenario_key}_initialized" not in st.session_state:
        st.session_state[f"{scenario_key}_goal_type"] = "Randomized"
        st.session_state[f"{scenario_key}_goal_n"] = 100
        st.session_state[f"{scenario_key}_screen_fail_rate"] = 0.2
        st.session_state[f"{scenario_key}_discontinuation_rate"] = 0.1
        st.session_state[f"{scenario_key}_period_type"] = "Randomized"
        st.session_state[f"{scenario_key}_driver"] = "Fixed Timeline"
        st.session_state[f"{scenario_key}_fsfv"] = date(2026, 1, 1)
        st.session_state[f"{scenario_key}_lsfv"] = date(2026, 6, 1)
        st.session_state[f"{scenario_key}_sites"] = 50
        st.session_state[f"{scenario_key}_lag_sr_days"] = 14
        st.session_state[f"{scenario_key}_lag_rc_days"] = 30
        st.session_state[f"{scenario_key}_sar_pct"] = [0, 20, 40, 60, 80, 100]
        st.session_state[f"{scenario_key}_rr_pct"] = [0.0, 0.5, 1.0, 1.0, 1.0, 1.0]
        st.session_state[f"{scenario_key}_include"] = True
        st.session_state[f"{scenario_key}_uncertainty_enabled"] = False
        st.session_state[f"{scenario_key}_uncertainty_lower_pct"] = 10.0
        st.session_state[f"{scenario_key}_uncertainty_upper_pct"] = 10.0
        st.session_state[f"{scenario_key}_initialized"] = True

    col1, col2, col3 = st.columns(3)

    with col1:
        goal_type = st.selectbox(
            "Goal Type",
            ["Randomized", "Completed"],
            key=f"{scenario_key}_goal_type",
        )
        goal_n = st.number_input(
            "Goal N",
            min_value=1,
            step=1,
            key=f"{scenario_key}_goal_n",
        )
        screen_fail_rate = st.slider(
            "Screen fail rate",
            0.0,
            0.99,
            key=f"{scenario_key}_screen_fail_rate",
        )
        discontinuation_rate = st.slider(
            "Discontinuation rate",
            0.0,
            0.99,
            key=f"{scenario_key}_discontinuation_rate",
        )

    with col2:
        period_type = st.selectbox(
            "Recruitment period type (primary)",
            ["Screened", "Randomized", "Completed"],
            key=f"{scenario_key}_period_type",
        )
        driver = st.selectbox(
            "Driver",
            ["Fixed Sites", "Fixed Timeline"],
            key=f"{scenario_key}_driver",
        )
        fsfv = st.date_input(
            "FSFV (inclusive)",
            key=f"{scenario_key}_fsfv",
        )

        if driver == "Fixed Timeline":
            lsfv = st.date_input(
                "LSFV (exclusive)",
                key=f"{scenario_key}_lsfv",
            )
            sites = None
        else:
            lsfv = None
            sites = st.number_input(
                "Sites",
                min_value=1,
                step=1,
                key=f"{scenario_key}_sites",
            )

    with col3:
        lag_sr_days = st.number_input(
            "Lag Screened → Randomized (days)",
            min_value=0,
            step=1,
            key=f"{scenario_key}_lag_sr_days",
        )
        lag_rc_days = st.number_input(
            "Lag Randomized → Completed (days)",
            min_value=0,
            step=1,
            key=f"{scenario_key}_lag_rc_days",
        )
        include = st.checkbox(
            "Include in comparison",
            key=f"{scenario_key}_include",
        )

    st.markdown("### SAR ramp (percent of sites active)")
    sar_df = pd.DataFrame([st.session_state[f"{scenario_key}_sar_pct"]], columns=["0%", "20%", "40%", "60%", "80%", "100%"])
    sar_edit = st.data_editor(sar_df, num_rows="fixed", hide_index=True, key=f"{scenario_key}_sar_editor")
    sar_pct = [float(sar_edit.iloc[0][c]) for c in sar_edit.columns]
    st.session_state[f"{scenario_key}_sar_pct"] = sar_pct

    st.markdown("### RR ramp (subjects per site per month)")
    rr_df = pd.DataFrame([st.session_state[f"{scenario_key}_rr_pct"]], columns=["0%", "20%", "40%", "60%", "80%", "100%"])
    rr_edit = st.data_editor(rr_df, num_rows="fixed", hide_index=True, key=f"{scenario_key}_rr_editor")
    rr_pct = [float(rr_edit.iloc[0][c]) for c in rr_edit.columns]
    st.session_state[f"{scenario_key}_rr_pct"] = rr_pct

    st.markdown("### Uncertainty bands")
    ucol1, ucol2, ucol3 = st.columns([1, 1, 1])
    with ucol1:
        uncertainty_enabled = st.checkbox(
            "Show uncertainty",
            key=f"{scenario_key}_uncertainty_enabled",
        )
    with ucol2:
        uncertainty_lower_pct = st.number_input(
            "Lower % (below)",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{scenario_key}_uncertainty_lower_pct",
        )
    with ucol3:
        uncertainty_upper_pct = st.number_input(
            "Upper % (above)",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{scenario_key}_uncertainty_upper_pct",
        )

    return ScenarioInputs(
        name=scenario_key,
        goal_type=goal_type,
        goal_n=int(goal_n),
        screen_fail_rate=float(screen_fail_rate),
        discontinuation_rate=float(discontinuation_rate),
        period_type=period_type,
        driver=driver,
        fsfv=fsfv,
        lsfv=lsfv,
        sites=int(sites) if sites is not None else None,
        lag_sr_days=int(lag_sr_days),
        lag_rc_days=int(lag_rc_days),
        sar_pct=sar_pct,
        rr_per_site_per_month=rr_pct,
    )


def render_results(out, scenario_key: str):
    st.success("Run complete.")

    st.markdown("## Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Target Screened", round(out.targets.screened))
        st.metric("Target Randomized", round(out.targets.randomized))
        st.metric("Target Completed", round(out.targets.completed))

    with col2:
        if out.solve.solved_sites is not None:
            st.metric("Solved Sites", out.solve.solved_sites)
        if out.solve.solved_lsfv is not None:
            st.metric("Solved LSFV", out.solve.solved_lsfv.isoformat())

    with col3:
        st.write("**Derived timelines**")
        st.write(f"Screened: {out.timelines.screened_fsfv} → {out.timelines.screened_lsfv}")
        st.write(f"Randomized: {out.timelines.randomized_fsfv} → {out.timelines.randomized_lsfv}")
        st.write(f"Completed: {out.timelines.completed_fsfv} → {out.timelines.completed_lslv}")

    # Cumulative chart (with optional uncertainty bands)
    def to_df(series_dict):
        return pd.DataFrame({"date": list(series_dict.keys()), "value": list(series_dict.values())}).sort_values("date")

    df_scr = to_df(out.states.screened.cumulative).rename(columns={"value": "Screened"})
    df_rand = to_df(out.states.randomized.cumulative).rename(columns={"value": "Randomized"})
    df_comp = to_df(out.states.completed.cumulative).rename(columns={"value": "Completed"})

    df = (
        df_scr.merge(df_rand, on="date", how="outer")
        .merge(df_comp, on="date", how="outer")
        .fillna(method="ffill")
        .fillna(0.0)
    )

    st.markdown("## Cumulative recruitment over time")

    df_long = df.melt(id_vars=["date"], value_vars=["Screened", "Randomized", "Completed"], var_name="state", value_name="value")

    u_enabled = st.session_state.get(f"{scenario_key}_uncertainty_enabled", False)
    u_lower = float(st.session_state.get(f"{scenario_key}_uncertainty_lower_pct", 10.0))
    u_upper = float(st.session_state.get(f"{scenario_key}_uncertainty_upper_pct", 10.0))

    df_long["lower"] = (df_long["value"] * (1.0 - u_lower / 100.0)).clip(lower=0.0)
    df_long["upper"] = df_long["value"] * (1.0 + u_upper / 100.0)

    base = alt.Chart(df_long).encode(
        x=alt.X("date:T", title="Date"),
        color=alt.Color("state:N", title="State"),
    )

    layers = []
    if u_enabled:
        layers.append(
            base.mark_area(opacity=0.18).encode(
                y=alt.Y("lower:Q", title="Cumulative"),
                y2="upper:Q",
            )
        )

    layers.append(
        base.mark_line().encode(
            y=alt.Y("value:Q", title="Cumulative"),
        )
    )

    st.altair_chart(alt.layer(*layers).properties(height=320), use_container_width=True)

    st.markdown("### Bucket summary (Monthly, Randomized)")
    bucket_df = pd.DataFrame(out.buckets["month"]["Randomized"])
    st.dataframe(bucket_df, use_container_width=True)

    st.markdown("## Incremental (5%) milestones over time")
    sel_state = st.selectbox("State", ["Screened", "Randomized", "Completed"], key=f"{scenario_key}_milestone_state",)
    st.dataframe(pd.DataFrame(out.milestones_time[sel_state]), use_container_width=True)

    st.markdown("## Target milestones (5% of target)")
    st.dataframe(pd.DataFrame(out.milestones_target[sel_state]), use_container_width=True)

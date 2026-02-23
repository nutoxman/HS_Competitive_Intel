from __future__ import annotations

from datetime import date, timedelta
import altair as alt
import pandas as pd
import streamlit as st

from engine.core.run_simple import run_simple_scenario
from engine.core.targets import ValidationError
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


DATE_DISPLAY_FORMAT = "%d-%b-%Y"
DATE_INPUT_FORMAT = "DD-MM-YYYY"


def _format_number(value):
    if value is None:
        return ""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 2)
    return value


def _format_dataframe_numbers(df: pd.DataFrame) -> pd.DataFrame:
    def fmt(v):
        return _format_number(v)

    return df.applymap(fmt)


def _format_date(value):
    if isinstance(value, date):
        return value.strftime(DATE_DISPLAY_FORMAT)
    return value


def _format_dataframe_dates(df: pd.DataFrame) -> pd.DataFrame:
    return df.applymap(_format_date)


def _coerce_to_date(value):
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    raise TypeError(f"Unsupported date value: {value!r}")


def _resolve_date_range(selection, default_start: date, default_end: date) -> tuple[date, date]:
    if isinstance(selection, tuple) and len(selection) == 2:
        start, end = selection
    elif isinstance(selection, list) and len(selection) == 2:
        start, end = selection
    elif isinstance(selection, date):
        start = end = selection
    else:
        start, end = default_start, default_end

    start = _coerce_to_date(start)
    end = _coerce_to_date(end)
    if end < start:
        start, end = end, start
    return start, end


def _one_year_after(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + 1)


def _milestone_dates(fsfv: date, lsfv: date) -> list[date]:
    duration = (lsfv - fsfv).days
    milestones = []
    for pct in [0, 20, 40, 60, 80, 100]:
        if duration <= 1:
            offset = 0
        else:
            offset = int((pct / 100.0) * (duration - 1))
        milestones.append(fsfv + timedelta(days=offset))
    return milestones


def render_scenario_inputs(scenario_key: str) -> ScenarioInputs:
    """
    Renders inputs for a scenario and returns ScenarioInputs.
    Uses st.session_state to persist values per scenario.
    """

    st.subheader(f"Scenario {scenario_key} Inputs")

    # Initialize session defaults if not present
    if f"{scenario_key}_initialized" not in st.session_state:
        today = date.today()
        st.session_state[f"{scenario_key}_goal_type"] = "Randomized"
        st.session_state[f"{scenario_key}_goal_n"] = 100
        st.session_state[f"{scenario_key}_screen_fail_rate"] = 0.2
        st.session_state[f"{scenario_key}_discontinuation_rate"] = 0.1
        st.session_state[f"{scenario_key}_period_type"] = "Randomized"
        st.session_state[f"{scenario_key}_simple_scenario"] = "Simple Scenario: Simple Scenario: # of Sites Drives Timeline"
        st.session_state[f"{scenario_key}_driver"] = "Fixed Sites"
        st.session_state[f"{scenario_key}_fsfv"] = today
        st.session_state[f"{scenario_key}_lsfv"] = _one_year_after(today)
        st.session_state[f"{scenario_key}_sites"] = 10
        st.session_state[f"{scenario_key}_lag_sr_days"] = 14
        st.session_state[f"{scenario_key}_lag_rc_days"] = 60
        st.session_state[f"{scenario_key}_sar_pct"] = [20, 40, 60, 80, 100, 100]
        st.session_state[f"{scenario_key}_rr_pct"] = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        st.session_state[f"{scenario_key}_include"] = True
        st.session_state[f"{scenario_key}_uncertainty_enabled"] = False
        st.session_state[f"{scenario_key}_uncertainty_lower_pct"] = 10.0
        st.session_state[f"{scenario_key}_uncertainty_upper_pct"] = 10.0
        st.session_state[f"{scenario_key}_initialized"] = True

    if st.session_state.get(f"{scenario_key}_period_type") not in {"Screened", "Randomized"}:
        st.session_state[f"{scenario_key}_period_type"] = "Randomized"

    global_scenario = st.session_state.get("simple_mode_scenario")
    if global_scenario:
        st.session_state[f"{scenario_key}_simple_scenario"] = global_scenario
        simple_scenario = global_scenario
        st.caption(f"Scenario mode: {simple_scenario}")
    else:
        simple_scenario = st.selectbox(
            "Simple Scenario",
            [
                "Simple Scenario: Simple Scenario: # of Sites Drives Timeline",
                "Simple Scenario: Timeline Drives # of Sites",
            ],
            key=f"{scenario_key}_simple_scenario",
        )

    if simple_scenario.startswith("Simple Scenario: Simple Scenario: # of Sites Drives Timeline"):
        driver = "Fixed Sites"
    else:
        driver = "Fixed Timeline"

    st.session_state[f"{scenario_key}_driver"] = driver
    st.caption(f"Driver: {driver}")

    col1, col2, col3 = st.columns(3)

    with col1:
        goal_type = st.selectbox(
            "Solve For",
            ["Randomized", "Completed"],
            format_func=lambda v: {"Randomized": "Total Randomized", "Completed": "Total Completed"}[v],
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
            "Recruitment Rate type (primary)",
            ["Screened", "Randomized"],
            key=f"{scenario_key}_period_type",
        )
        fsfv = st.date_input(
            "FSFV (inclusive)",
            key=f"{scenario_key}_fsfv",
            format=DATE_INPUT_FORMAT,
        )

        if driver == "Fixed Timeline":
            lsfv = st.date_input(
                "LSFV (exclusive)",
                key=f"{scenario_key}_lsfv",
                format=DATE_INPUT_FORMAT,
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

    rr_label_map = {
        "Screened": "screened",
        "Randomized": "randomized",
    }
    rr_label = rr_label_map.get(period_type, "randomized")
    st.markdown(f"### # of subjects {rr_label}/site/month")
    rr_columns = ["0% (FSFV)", "20%", "40%", "60%", "80%", "100%"]
    rr_input_cols = ["#/site/month"] + rr_columns
    rr_input_df = pd.DataFrame(
        [["Rate"] + st.session_state[f"{scenario_key}_rr_pct"]],
        columns=rr_input_cols,
    )
    rr_input_config = {
        "#/site/month": st.column_config.TextColumn(disabled=True, width="small"),
    }
    for col in rr_columns:
        rr_input_config[col] = st.column_config.NumberColumn(width="small")
    rr_edit = st.data_editor(
        rr_input_df,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        column_config=rr_input_config,
        key=f"{scenario_key}_rr_editor",
    )
    rr_pct = [float(rr_edit.iloc[0][c]) for c in rr_columns]
    st.session_state[f"{scenario_key}_rr_pct"] = rr_pct

    if f"{scenario_key}_result" in st.session_state:
        out = st.session_state[f"{scenario_key}_result"]
        milestone_dates = _milestone_dates(out.primary.fsfv, out.primary.lsfv)
        settings = GlobalSettings()
        total_per_month = [out.primary.new_primary.get(d, 0.0) * settings.days_per_month for d in milestone_dates]
        rr_out_df = pd.DataFrame(
            [
                ["Milestone Date"] + [_format_date(d) for d in milestone_dates],
                [f"Total {rr_label.title()}/month"] + total_per_month,
            ],
            columns=rr_input_cols,
        )
        rr_out_df = _format_dataframe_numbers(rr_out_df)
        rr_output_config = {"#/site/month": st.column_config.TextColumn(disabled=True, width="small")}
        for col in rr_columns:
            rr_output_config[col] = st.column_config.TextColumn(width="small")
        st.caption("Calculated outputs at milestones")
        st.dataframe(
            rr_out_df,
            width="stretch",
            hide_index=True,
            column_config=rr_output_config,
        )

    st.markdown("### Site Activation Rate at % Milestones from FSFV to LSFV")
    sar_columns = ["0% (FSFV)", "20%", "40%", "60%", "80%", "100%"]
    sar_input_cols = ["Metric"] + sar_columns
    sar_input_df = pd.DataFrame(
        [["SAR%"] + st.session_state[f"{scenario_key}_sar_pct"]],
        columns=sar_input_cols,
    )
    sar_input_config = {
        "Metric": st.column_config.TextColumn(disabled=True, width="small"),
    }
    for col in sar_columns:
        sar_input_config[col] = st.column_config.NumberColumn(width="small")
    sar_edit = st.data_editor(
        sar_input_df,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        column_config=sar_input_config,
        key=f"{scenario_key}_sar_editor",
    )
    sar_pct = [float(sar_edit.iloc[0][c]) for c in sar_columns]
    st.session_state[f"{scenario_key}_sar_pct"] = sar_pct

    if f"{scenario_key}_result" in st.session_state:
        out = st.session_state[f"{scenario_key}_result"]
        milestone_dates = _milestone_dates(out.primary.fsfv, out.primary.lsfv)
        active_sites = [out.primary.active_sites.get(d, 0.0) for d in milestone_dates]
        sar_out_df = pd.DataFrame(
            [
                ["Milestone Date"] + [_format_date(d) for d in milestone_dates],
                ["Active Sites"] + active_sites,
            ],
            columns=sar_input_cols,
        )
        sar_out_df = _format_dataframe_numbers(sar_out_df)
        sar_output_config = {"Metric": st.column_config.TextColumn(disabled=True, width="small")}
        for col in sar_columns:
            sar_output_config[col] = st.column_config.TextColumn(width="small")
        st.caption("Calculated outputs at milestones")
        st.dataframe(
            sar_out_df,
            width="stretch",
            hide_index=True,
            column_config=sar_output_config,
        )

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

    st.markdown(
        """
<style>
  div[data-testid="stMetric"] {
    font-size: 10pt;
  }
</style>
""",
        unsafe_allow_html=True,
    )

    st.markdown("## Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Target Screened", _format_number(out.targets.screened))
        st.metric("Target Randomized", _format_number(out.targets.randomized))
        st.metric("Target Completed", _format_number(out.targets.completed))

    with col2:
        if out.solve.solved_sites is not None:
            st.metric("Solved Sites", _format_number(out.solve.solved_sites))
        if out.solve.solved_lsfv is not None:
            st.metric("Solved LSFV", _format_date(out.solve.solved_lsfv))

    with col3:
        fsfv = out.primary.fsfv
        fslv = out.timelines.completed_fsfv
        lsfv = out.primary.lsfv
        lslv = out.timelines.completed_lslv
        st.write("**Timelines**")
        st.write(f"FSFV: {_format_date(fsfv)}")
        st.write(f"FSLV: {_format_date(fslv)}")
        st.write(f"LSFV: {_format_date(lsfv)}")
        st.write(f"LSLV: {_format_date(lslv)}")

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

    domain_min = _coerce_to_date(df_long["date"].min()) if not df_long.empty else out.timelines.completed_fsfv
    domain_max = _coerce_to_date(out.timelines.completed_lslv + timedelta(days=30))
    selected_range = st.date_input(
        "Display date range",
        value=(domain_min, domain_max),
        key=f"{scenario_key}_chart_date_range",
        format=DATE_INPUT_FORMAT,
    )
    range_start, range_end = _resolve_date_range(selected_range, domain_min, domain_max)

    base = alt.Chart(df_long).encode(
        x=alt.X(
            "date:T",
            title="Date",
            scale=alt.Scale(domain=[range_start, range_end]),
            axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
        ),
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
            tooltip=[
                alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                alt.Tooltip("state:N", title="State"),
                alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
            ],
        )
    )

    show_sites = st.checkbox("Show active sites by month", value=False, key=f"{scenario_key}_show_active_sites")
    if show_sites and out.primary.active_sites:
        active_df = pd.DataFrame(
            {"date": list(out.primary.active_sites.keys()), "active_sites": list(out.primary.active_sites.values())}
        ).sort_values("date")
        active_df["month"] = active_df["date"].apply(lambda d: date(d.year, d.month, 1))
        monthly = (
            active_df.groupby("month", as_index=False)["active_sites"]
            .mean()
            .rename(columns={"month": "date"})
        )

        bar = (
            alt.Chart(monthly)
            .mark_bar(opacity=0.25)
            .encode(
                x=alt.X(
                    "date:T",
                    scale=alt.Scale(domain=[range_start, range_end]),
                    axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                ),
                y=alt.Y("active_sites:Q", axis=alt.Axis(title="Active Sites", orient="right")),
                tooltip=[
                    alt.Tooltip("date:T", title="Month", format=DATE_DISPLAY_FORMAT),
                    alt.Tooltip("active_sites:Q", title="Active Sites", format=".1f"),
                ],
            )
        )
        layers.append(bar)

    chart = alt.layer(*layers).properties(height=320)
    if show_sites:
        chart = chart.resolve_scale(y="independent")

    st.altair_chart(chart, width="stretch")

    st.markdown("### Bucket summary (Monthly, Randomized)")
    bucket_df = pd.DataFrame(out.buckets["month"]["Randomized"]).rename(
        columns={
            "incremental": "Incremental Enrollment",
            "cumulative_to_date": "Cumulative Enrollment",
            "avg_active_sites": "Sites Active",
            "avg_activation_pct": "% of Sites Active",
        }
    )
    bucket_df = _format_dataframe_numbers(bucket_df)
    st.dataframe(bucket_df, width="stretch")

    st.markdown("## Incremental (5%) milestones over time")
    sel_state = st.selectbox("State", ["Screened", "Randomized", "Completed"], key=f"{scenario_key}_milestone_state")
    milestones_time_df = pd.DataFrame(out.milestones_time[sel_state])
    milestones_time_df = _format_dataframe_dates(milestones_time_df)
    milestones_time_df = _format_dataframe_numbers(milestones_time_df)
    st.dataframe(milestones_time_df, width="stretch")

    st.markdown("## Target milestones (5% of target)")
    milestones_target_df = pd.DataFrame(out.milestones_target[sel_state])
    milestones_target_df = _format_dataframe_dates(milestones_target_df)
    milestones_target_df = _format_dataframe_numbers(milestones_target_df)
    st.dataframe(milestones_target_df, width="stretch")

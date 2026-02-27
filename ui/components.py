from __future__ import annotations

from datetime import date, timedelta
import altair as alt
import pandas as pd
import streamlit as st

from engine.core.solvers import solve_lsfv_fixed_sites, solve_sites_fixed_timeline
from engine.core.targets import ValidationError, derive_targets
from engine.core.timelines import derive_state_timelines
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


DATE_DISPLAY_FORMAT = "%d-%b-%Y"
DATE_INPUT_FORMAT = "DD-MM-YYYY"
TABLE_FONT_COLOR = "#09CFEA"
LEGACY_FIXED_SITES_MODE = "Simple Scenario: Simple Scenario: # of Sites Drives Timeline"
FIXED_SITES_MODE = "Simple Scenario: # of Sites Drives Timeline"
FIXED_TIMELINE_MODE = "Simple Scenario: Timeline Drives # of Sites"
STATE_SERIES_ORDER = ["Screened", "Randomized", "Completed"]
SUBJECTS_LEGEND_TITLE = "# of Subjects"
# Vega-Lite default continuous bar width is 5px; increased by 125% total.
ACTIVE_SITES_BAR_WIDTH_PX = 11.25
AXIS_TICK_SIZE_PX = 5
TIMELINE_MARKER_COLOR = "#FFEA00"


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
    # Keep the selected range within the current domain.
    start = max(default_start, min(start, default_end))
    end = max(default_start, min(end, default_end))
    if end < start:
        start, end = end, start
    return start, end


def _one_year_after(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + 1)


def _render_table_color_css(scenario_key: str) -> None:
    st.markdown(
        f"""
<style>
  .st-key-{scenario_key}_rr_editor [data-testid="stDataEditor"] th,
  .st-key-{scenario_key}_rr_editor [data-testid="stDataEditor"] td,
  .st-key-{scenario_key}_rr_editor [data-testid="stDataEditor"] input,
  .st-key-{scenario_key}_rr_editor [data-testid="stDataEditor"] textarea,
  .st-key-{scenario_key}_sar_editor [data-testid="stDataEditor"] th,
  .st-key-{scenario_key}_sar_editor [data-testid="stDataEditor"] td,
  .st-key-{scenario_key}_sar_editor [data-testid="stDataEditor"] input,
  .st-key-{scenario_key}_sar_editor [data-testid="stDataEditor"] textarea {{
    color: {TABLE_FONT_COLOR} !important;
  }}
</style>
""",
        unsafe_allow_html=True,
    )


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


def _normalize_simple_mode_label(mode: str | None) -> str | None:
    if mode == LEGACY_FIXED_SITES_MODE:
        return FIXED_SITES_MODE
    return mode


def _extend_cumulative_df_to_date(df: pd.DataFrame, end_date: date) -> pd.DataFrame:
    if df.empty:
        return df
    current_end = _coerce_to_date(df["date"].max())
    if end_date <= current_end:
        return df

    extension_dates = pd.date_range(start=current_end + timedelta(days=1), end=end_date, freq="D").date
    if len(extension_dates) == 0:
        return df

    extension = pd.DataFrame({"date": extension_dates})
    last_row = df.iloc[-1]
    for col in df.columns:
        if col == "date":
            continue
        extension[col] = last_row[col]

    return pd.concat([df, extension], ignore_index=True)


def _scenario_inputs_from_session_state(scenario_key: str, fallback_out) -> ScenarioInputs | None:
    try:
        driver = st.session_state.get(f"{scenario_key}_driver", "Fixed Sites")
        fsfv = _coerce_to_date(st.session_state.get(f"{scenario_key}_fsfv", fallback_out.primary.fsfv))
        lsfv_raw = st.session_state.get(f"{scenario_key}_lsfv", fallback_out.primary.lsfv)
        sites_raw = st.session_state.get(f"{scenario_key}_sites", fallback_out.primary.sites)

        lsfv = _coerce_to_date(lsfv_raw) if driver == "Fixed Timeline" else None
        sites = int(sites_raw) if driver == "Fixed Sites" else None

        return ScenarioInputs(
            name=scenario_key,
            goal_type=st.session_state.get(f"{scenario_key}_goal_type", "Randomized"),
            goal_n=int(st.session_state.get(f"{scenario_key}_goal_n", 100)),
            screen_fail_rate=float(st.session_state.get(f"{scenario_key}_screen_fail_rate", 0.2)),
            discontinuation_rate=float(st.session_state.get(f"{scenario_key}_discontinuation_rate", 0.1)),
            period_type=st.session_state.get(f"{scenario_key}_period_type", "Screened"),
            driver=driver,
            fsfv=fsfv,
            lsfv=lsfv,
            sites=sites,
            lag_sr_days=int(st.session_state.get(f"{scenario_key}_lag_sr_days", 14)),
            lag_rc_days=int(st.session_state.get(f"{scenario_key}_lag_rc_days", 60)),
            sar_pct=[float(v) for v in st.session_state.get(f"{scenario_key}_sar_pct", [20, 40, 60, 80, 100, 100])],
            rr_per_site_per_month=[float(v) for v in st.session_state.get(f"{scenario_key}_rr_pct", [1, 1, 1, 1, 1, 1])],
        )
    except Exception:
        return None


def _solve_uncertainty_timelines(
    scenario_key: str,
    out,
    lower_pct: float,
    upper_pct: float,
) -> tuple[dict[str, date] | None, dict[str, date] | None]:
    inputs = _scenario_inputs_from_session_state(scenario_key, out)
    if not inputs:
        return None, None

    settings = GlobalSettings()
    targets = derive_targets(
        inputs.goal_type,
        inputs.goal_n,
        inputs.screen_fail_rate,
        inputs.discontinuation_rate,
    )

    def solve_with_multiplier(multiplier: float) -> dict[str, date] | None:
        try:
            if inputs.driver == "Fixed Sites":
                if inputs.sites is None:
                    return None
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
                    throughput_multiplier=multiplier,
                )
                if not solve.reached or solve.solved_lsfv is None:
                    return None
                solved_lsfv = solve.solved_lsfv
            else:
                lsfv_fixed = inputs.lsfv or out.primary.lsfv
                solve = solve_sites_fixed_timeline(
                    fsfv=inputs.fsfv,
                    lsfv=lsfv_fixed,
                    period_type=inputs.period_type,
                    targets=targets,
                    screen_fail_rate=inputs.screen_fail_rate,
                    discontinuation_rate=inputs.discontinuation_rate,
                    lag_sr_days=inputs.lag_sr_days,
                    lag_rc_days=inputs.lag_rc_days,
                    sar_pct=inputs.sar_pct,
                    rr_per_site_per_month=inputs.rr_per_site_per_month,
                    settings=settings,
                    throughput_multiplier=multiplier,
                )
                if not solve.reached:
                    return None
                solved_lsfv = lsfv_fixed

            t = derive_state_timelines(
                fsfv=inputs.fsfv,
                lsfv=solved_lsfv,
                period_type=inputs.period_type,
                lag_sr_days=inputs.lag_sr_days,
                lag_rc_days=inputs.lag_rc_days,
            )
            return {
                "fsfv": inputs.fsfv,
                "fslv": t.completed_fsfv,
                "lsfv": solved_lsfv,
                "lslv": t.completed_lslv,
            }
        except ValidationError:
            return None

    pessimistic = solve_with_multiplier(max(0.0, 1.0 - lower_pct / 100.0))
    optimistic = solve_with_multiplier(1.0 + upper_pct / 100.0)
    return optimistic, pessimistic


def _render_timeline_block(title: str, timeline_values: dict[str, date] | None) -> None:
    st.markdown(f"<p style='font-size:10pt;font-weight:700;margin:0;'>{title}</p>", unsafe_allow_html=True)
    if not timeline_values:
        st.markdown("<p style='font-size:10pt;margin:0.2rem 0;'>FSFV: --</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:10pt;margin:0.2rem 0;'>FSLV: --</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:10pt;margin:0.2rem 0;'>LSFV: --</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:10pt;margin:0.2rem 0;'>LSLV: --</p>", unsafe_allow_html=True)
        return

    st.markdown(
        f"<p style='font-size:10pt;margin:0.2rem 0;'>FSFV: {_format_date(timeline_values['fsfv'])}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:10pt;margin:0.2rem 0;'>FSLV: {_format_date(timeline_values['fslv'])}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:10pt;margin:0.2rem 0;'>LSFV: {_format_date(timeline_values['lsfv'])}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:10pt;margin:0.2rem 0;'>LSLV: {_format_date(timeline_values['lslv'])}</p>",
        unsafe_allow_html=True,
    )


def render_scenario_inputs(scenario_key: str) -> ScenarioInputs:
    """
    Renders inputs for a scenario and returns ScenarioInputs.
    Uses st.session_state to persist values per scenario.
    """

    # Initialize session defaults if not present
    if f"{scenario_key}_initialized" not in st.session_state:
        today = date.today()
        st.session_state[f"{scenario_key}_goal_type"] = "Randomized"
        st.session_state[f"{scenario_key}_goal_n"] = 100
        st.session_state[f"{scenario_key}_screen_fail_rate"] = 0.2
        st.session_state[f"{scenario_key}_discontinuation_rate"] = 0.1
        st.session_state[f"{scenario_key}_period_type"] = "Screened"
        st.session_state[f"{scenario_key}_simple_scenario"] = FIXED_SITES_MODE
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

    existing_scenario = _normalize_simple_mode_label(st.session_state.get(f"{scenario_key}_simple_scenario"))
    if existing_scenario:
        st.session_state[f"{scenario_key}_simple_scenario"] = existing_scenario

    global_scenario = _normalize_simple_mode_label(st.session_state.get("simple_mode_scenario"))
    if global_scenario:
        st.session_state[f"{scenario_key}_simple_scenario"] = global_scenario
        simple_scenario = global_scenario
    else:
        simple_scenario = st.selectbox(
            "Simple Scenario",
            [
                FIXED_SITES_MODE,
                FIXED_TIMELINE_MODE,
            ],
            key=f"{scenario_key}_simple_scenario",
        )

    mode_suffix = {
        FIXED_SITES_MODE: "# of Sites Drives Timeline",
        FIXED_TIMELINE_MODE: "Timeline Drives # of Sites",
    }.get(simple_scenario, simple_scenario)
    st.markdown(
        f"<p style='font-size:11pt;font-weight:700;margin:0 0 0.5rem 0;'>Scenario {scenario_key} Inputs: {mode_suffix}</p>",
        unsafe_allow_html=True,
    )

    if simple_scenario == FIXED_SITES_MODE:
        driver = "Fixed Sites"
    else:
        driver = "Fixed Timeline"

    st.session_state[f"{scenario_key}_driver"] = driver
    _render_table_color_css(scenario_key)

    if driver == "Fixed Sites":
        row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)
        with row1_col1:
            sites = st.number_input(
                "Sites",
                min_value=1,
                step=1,
                key=f"{scenario_key}_sites",
            )
        with row1_col2:
            period_type = st.selectbox(
                "Recruitment Rate type (primary)",
                ["Screened", "Randomized"],
                key=f"{scenario_key}_period_type",
            )
        with row1_col3:
            lag_sr_days = st.number_input(
                "Lag Screened → Randomized (days)",
                min_value=0,
                step=1,
                key=f"{scenario_key}_lag_sr_days",
            )
        with row1_col4:
            screen_fail_rate = st.slider(
                "Screen fail rate",
                0.0,
                0.99,
                key=f"{scenario_key}_screen_fail_rate",
            )

        row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)
        with row2_col1:
            goal_n = st.number_input(
                "Goal N",
                min_value=1,
                step=1,
                key=f"{scenario_key}_goal_n",
            )
        with row2_col2:
            fsfv = st.date_input(
                "FSFV (inclusive)",
                key=f"{scenario_key}_fsfv",
                format=DATE_INPUT_FORMAT,
            )
        with row2_col3:
            lag_rc_days = st.number_input(
                "Lag Randomized → Completed (days)",
                min_value=0,
                step=1,
                key=f"{scenario_key}_lag_rc_days",
            )
        with row2_col4:
            discontinuation_rate = st.slider(
                "Discontinuation rate",
                0.0,
                0.99,
                key=f"{scenario_key}_discontinuation_rate",
            )

        row3_col1, _, _, _ = st.columns(4)
        with row3_col1:
            goal_type = st.selectbox(
                "Solve For",
                ["Randomized", "Completed"],
                format_func=lambda v: {"Randomized": "Total Randomized", "Completed": "Total Completed"}[v],
                key=f"{scenario_key}_goal_type",
            )

        include = st.checkbox(
            "Include in comparison",
            key=f"{scenario_key}_include",
        )
        lsfv = None
    else:
        row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)
        with row1_col1:
            goal_n = st.number_input(
                "Goal N",
                min_value=1,
                step=1,
                key=f"{scenario_key}_goal_n",
            )
        with row1_col2:
            period_type = st.selectbox(
                "Recruitment Rate type (primary)",
                ["Screened", "Randomized"],
                key=f"{scenario_key}_period_type",
            )
        with row1_col3:
            lag_sr_days = st.number_input(
                "Lag Screened → Randomized (days)",
                min_value=0,
                step=1,
                key=f"{scenario_key}_lag_sr_days",
            )
        with row1_col4:
            screen_fail_rate = st.slider(
                "Screen fail rate",
                0.0,
                0.99,
                key=f"{scenario_key}_screen_fail_rate",
            )

        row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)
        with row2_col1:
            goal_type = st.selectbox(
                "Solve For",
                ["Randomized", "Completed"],
                format_func=lambda v: {"Randomized": "Total Randomized", "Completed": "Total Completed"}[v],
                key=f"{scenario_key}_goal_type",
            )
        with row2_col2:
            fsfv = st.date_input(
                "FSFV (inclusive)",
                key=f"{scenario_key}_fsfv",
                format=DATE_INPUT_FORMAT,
            )
        with row2_col3:
            lag_rc_days = st.number_input(
                "Lag Randomized → Completed (days)",
                min_value=0,
                step=1,
                key=f"{scenario_key}_lag_rc_days",
            )
        with row2_col4:
            discontinuation_rate = st.slider(
                "Discontinuation rate",
                0.0,
                0.99,
                key=f"{scenario_key}_discontinuation_rate",
            )

        row3_col1, _, _, _ = st.columns(4)
        with row3_col1:
            lsfv = st.date_input(
                "LSFV (exclusive)",
                key=f"{scenario_key}_lsfv",
                format=DATE_INPUT_FORMAT,
            )

        include = st.checkbox(
            "Include in comparison",
            key=f"{scenario_key}_include",
        )
        sites = None

    with st.expander("Site Activation and Enrollment Rate Ramp Tuning", expanded=True):
        st.markdown(
            "<p style='font-size:11pt;font-weight:700;margin:0.5rem 0;'>Site Activation Ramp: % sites active over time (FSFV to LSFV)</p>",
            unsafe_allow_html=True,
        )
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

        rr_label_map = {
            "Screened": "screened",
            "Randomized": "randomized",
        }
        rr_label = rr_label_map.get(period_type, "randomized")
        st.markdown(
            f"<p style='font-size:11pt;font-weight:700;margin:0.5rem 0;'>Recruitment Ramp Tuning: # of subjects {rr_label}/site/month</p>",
            unsafe_allow_html=True,
        )
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

    st.markdown("<p style='font-size:11pt;font-weight:700;margin:0.5rem 0;'>Uncertainty bands</p>", unsafe_allow_html=True)
    ucol1, ucol2, ucol3 = st.columns([1, 1, 1])
    with ucol1:
        uncertainty_enabled = st.checkbox(
            "Show uncertainty",
            key=f"{scenario_key}_uncertainty_enabled",
        )
    with ucol2:
        uncertainty_lower_pct = st.number_input(
            "Pessimistic: Lower % (below)",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{scenario_key}_uncertainty_lower_pct",
        )
    with ucol3:
        uncertainty_upper_pct = st.number_input(
            "Optimistic: Upper % (above)",
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

    u_enabled = st.session_state.get(f"{scenario_key}_uncertainty_enabled", False)
    u_lower = float(st.session_state.get(f"{scenario_key}_uncertainty_lower_pct", 10.0))
    u_upper = float(st.session_state.get(f"{scenario_key}_uncertainty_upper_pct", 10.0))

    total_randomized = max(out.states.randomized.cumulative.values()) if out.states.randomized.cumulative else 0.0
    total_screened = max(out.states.screened.cumulative.values()) if out.states.screened.cumulative else 0.0
    duration_days = max(1, (out.primary.lsfv - out.primary.fsfv).days)
    site_months = out.primary.sites * (duration_days / GlobalSettings().days_per_month)
    avg_randomized_per_site_month = (total_randomized / site_months) if site_months > 0 else 0.0
    avg_screened_per_site_month = (total_screened / site_months) if site_months > 0 else 0.0

    optimistic_timelines = None
    pessimistic_timelines = None
    if u_enabled:
        optimistic_timelines, pessimistic_timelines = _solve_uncertainty_timelines(
            scenario_key,
            out,
            u_lower,
            u_upper,
        )

    st.markdown(
        """
<style>
  div[data-testid="stMetric"],
  div[data-testid="stMetricLabel"] *,
  div[data-testid="stMetricValue"] *,
  div[data-testid="stMetricDelta"] * {
    font-size: 10pt;
  }
</style>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<hr style='border:0;border-top:1px solid rgba(128,128,128,0.45);margin:0.65rem 0 0.45rem 0;'>",
        unsafe_allow_html=True,
    )
    st.markdown("<p style='font-size:10pt;font-weight:700;'>Summary</p>", unsafe_allow_html=True)

    if u_enabled:
        col1, col2, col3, col4, col5 = st.columns(5)
    else:
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
        st.metric("Avg Randomized/site/month", _format_number(avg_randomized_per_site_month))
        st.metric("Avg Screened/site/month", _format_number(avg_screened_per_site_month))

    with col3:
        _render_timeline_block(
            "Timelines",
            {
                "fsfv": out.primary.fsfv,
                "fslv": out.timelines.completed_fsfv,
                "lsfv": out.primary.lsfv,
                "lslv": out.timelines.completed_lslv,
            },
        )

    if u_enabled:
        with col4:
            _render_timeline_block("Optimistic Timelines", optimistic_timelines)
        with col5:
            _render_timeline_block("Pessimistic Timelines", pessimistic_timelines)

    pessimistic_lslv = out.timelines.completed_lslv
    if pessimistic_timelines and "lslv" in pessimistic_timelines:
        pessimistic_lslv = max(pessimistic_lslv, pessimistic_timelines["lslv"])

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
    if u_enabled:
        df = _extend_cumulative_df_to_date(df, pessimistic_lslv)

    st.markdown(
        "<hr style='border:0;border-top:1px solid rgba(128,128,128,0.45);margin:0.65rem 0 0.45rem 0;'>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='font-size:10pt;font-weight:700;margin:0.5rem 0;'>Cumulative recruitment over time</p>",
        unsafe_allow_html=True,
    )

    df_long = df.melt(id_vars=["date"], value_vars=["Screened", "Randomized", "Completed"], var_name="state", value_name="value")

    df_long["lower"] = (df_long["value"] * (1.0 - u_lower / 100.0)).clip(lower=0.0)
    df_long["upper"] = df_long["value"] * (1.0 + u_upper / 100.0)

    chart_col, controls_col = st.columns([5, 1], gap="medium")
    with controls_col:
        show_sites = st.checkbox("Show active sites by month", value=False, key=f"{scenario_key}_show_active_sites")
        show_timeline_markers = st.checkbox(
            "Show timeline markers",
            value=True,
            key=f"{scenario_key}_show_timeline_markers",
        )
    show_sites_prev_key = f"{scenario_key}_show_active_sites_prev"
    show_sites_prev = bool(st.session_state.get(show_sites_prev_key, False))

    monthly = None
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

    domain_min = _coerce_to_date(df_long["date"].min()) if not df_long.empty else out.timelines.completed_fsfv
    if monthly is not None and not monthly.empty:
        domain_min = min(domain_min, _coerce_to_date(monthly["date"].min()))
    domain_max = _coerce_to_date(pessimistic_lslv + timedelta(days=30))
    chart_range_key = f"{scenario_key}_chart_date_range"
    selected_range = st.session_state.get(chart_range_key, (domain_min, domain_max))
    range_start, range_end = _resolve_date_range(selected_range, domain_min, domain_max)
    baseline_domain_max = _coerce_to_date(out.timelines.completed_lslv + timedelta(days=30))
    if domain_max > baseline_domain_max and range_end == baseline_domain_max:
        range_end = domain_max
    if show_sites and (not show_sites_prev) and monthly is not None and not monthly.empty:
        first_month_start = _coerce_to_date(monthly["date"].min())
        range_start = min(range_start, first_month_start)
        st.session_state[chart_range_key] = (range_start, range_end)
    st.session_state[show_sites_prev_key] = show_sites

    base = alt.Chart(df_long).encode(
        x=alt.X(
            "date:T",
            title="Date",
            scale=alt.Scale(domain=[range_start, range_end]),
            axis=alt.Axis(
                format=DATE_DISPLAY_FORMAT,
                ticks=True,
                tickSize=AXIS_TICK_SIZE_PX,
                grid=True,
            ),
        ),
        color=alt.Color(
            "state:N",
            title=SUBJECTS_LEGEND_TITLE,
            scale=alt.Scale(domain=STATE_SERIES_ORDER),
        ),
    )

    layers = []
    cumulative_axis = alt.Axis(
        title="Cumulative",
        orient="left",
        ticks=True,
        tickSize=AXIS_TICK_SIZE_PX,
        grid=True,
    )
    if u_enabled:
        layers.append(
            base.mark_area(opacity=0.18).encode(
                y=alt.Y(
                    "lower:Q",
                    axis=None if show_sites else cumulative_axis,
                ),
                y2="upper:Q",
            )
        )

    layers.append(
        base.mark_line().encode(
            y=alt.Y(
                "value:Q",
                axis=cumulative_axis,
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                alt.Tooltip("state:N", title="State"),
                alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
            ],
        )
    )

    if monthly is not None and not monthly.empty:
        bar = (
            alt.Chart(monthly)
            .mark_bar(opacity=0.25, size=ACTIVE_SITES_BAR_WIDTH_PX)
            .encode(
                x=alt.X(
                    "date:T",
                    scale=alt.Scale(domain=[range_start, range_end]),
                    axis=alt.Axis(
                        format=DATE_DISPLAY_FORMAT,
                        ticks=True,
                        tickSize=AXIS_TICK_SIZE_PX,
                        grid=True,
                    ),
                ),
                y=alt.Y(
                    "active_sites:Q",
                    axis=alt.Axis(
                        title="Active Sites",
                        orient="right",
                        ticks=True,
                        tickSize=AXIS_TICK_SIZE_PX,
                        grid=False,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Month", format=DATE_DISPLAY_FORMAT),
                    alt.Tooltip("active_sites:Q", title="Active Sites", format=".1f"),
                ],
            )
        )
        layers.append(bar)

    if show_timeline_markers:
        timeline_markers = pd.DataFrame(
            [
                {"label": "FSFV", "date": out.primary.fsfv},
                {"label": "FSLV", "date": out.timelines.completed_fsfv},
                {"label": "LSFV", "date": out.primary.lsfv},
                {"label": "LSLV", "date": out.timelines.completed_lslv},
            ]
        )
        layers.append(
            alt.Chart(timeline_markers)
            .mark_rule(color=TIMELINE_MARKER_COLOR, strokeDash=[4, 4], strokeWidth=1.25)
            .encode(
                x=alt.X(
                    "date:T",
                    scale=alt.Scale(domain=[range_start, range_end]),
                )
            )
        )
        layers.append(
            alt.Chart(timeline_markers)
            .mark_text(
                color=TIMELINE_MARKER_COLOR,
                align="left",
                baseline="top",
                dx=4,
                dy=4,
                fontSize=10,
                fontWeight="bold",
            )
            .encode(
                x=alt.X(
                    "date:T",
                    scale=alt.Scale(domain=[range_start, range_end]),
                ),
                y=alt.value(4),
                text="label:N",
            )
        )

    chart = alt.layer(*layers).properties(height=320)
    if show_sites:
        chart = chart.resolve_scale(y="independent")

    with chart_col:
        st.altair_chart(chart, width="stretch")
        st.slider(
            "X-axis date range",
            min_value=domain_min,
            max_value=domain_max,
            value=(range_start, range_end),
            key=chart_range_key,
        )

    st.markdown(
        "<p style='font-size:10pt;font-weight:700;'>Bucket summary (Monthly, Randomized)</p>",
        unsafe_allow_html=True,
    )
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

    st.markdown(
        "<p style='font-size:10pt;font-weight:700;'>Incremental (5%) milestones over time</p>",
        unsafe_allow_html=True,
    )
    sel_state = st.selectbox("State", ["Screened", "Randomized", "Completed"], key=f"{scenario_key}_milestone_state")
    milestones_time_df = pd.DataFrame(out.milestones_time[sel_state])
    milestones_time_df = _format_dataframe_dates(milestones_time_df)
    milestones_time_df = _format_dataframe_numbers(milestones_time_df)
    st.dataframe(milestones_time_df, width="stretch")

    st.markdown(
        "<p style='font-size:10pt;font-weight:700;'>Target milestones (5% of target)</p>",
        unsafe_allow_html=True,
    )
    milestones_target_df = pd.DataFrame(out.milestones_target[sel_state])
    milestones_target_df = _format_dataframe_dates(milestones_target_df)
    milestones_target_df = _format_dataframe_numbers(milestones_target_df)
    st.dataframe(milestones_target_df, width="stretch")

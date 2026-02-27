from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st

from engine.core.advanced import aggregate_states
from engine.core.buckets import build_bucket_summary
from engine.core.derive_states import derive_states_from_primary
from engine.core.milestones import incremental_time_milestones, target_milestones
from engine.core.primary import build_primary_daily
from engine.core.series_ops import scale_series
from engine.core.solvers import SolveResult, solve_lsfv_fixed_sites
from engine.core.targets import ValidationError
from engine.core.timelines import derive_state_timelines
from engine.models.results import ScenarioRunResult
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings
from engine.models.types import Targets
from export.advanced_pdf import build_advanced_pdf
from ui.persistence import dump_advanced_state, from_json_bytes, load_advanced_state, to_json_bytes


COUNTRY_DATA_PATH = "data/un_members_m49.csv"
DATE_DISPLAY_FORMAT = "%d-%b-%Y"
DATE_INPUT_FORMAT = "DD-MM-YYYY"
ADV_FIXED_DRIVER = "Fixed Sites"
ADV_DEFAULT_SAR_PCT = [20, 40, 60, 80, 100, 100]
ADV_DEFAULT_RR_PER_SITE_PER_MONTH = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]


@st.cache_data(show_spinner=False)
def load_countries() -> pd.DataFrame:
    df = pd.read_csv(COUNTRY_DATA_PATH)
    # Standardize column names
    df = df.rename(
        columns={
            "un_member_name": "country",
            "iso3": "iso3",
            "region": "region",
            "subregion": "subregion",
        }
    )
    return df


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


def _validate_probability(name: str, value: float) -> None:
    if value < 0.0 or value >= 1.0:
        raise ValidationError(f"{name} must be in [0, 1). Got {value!r}.")


def _derive_targets_from_primary_target(
    *,
    period_type: str,
    target_n: int,
    screen_fail_rate: float,
    discontinuation_rate: float,
) -> Targets:
    if target_n <= 0:
        raise ValidationError("Target N must be a positive integer.")

    _validate_probability("Screen fail rate", float(screen_fail_rate))
    _validate_probability("Discontinuation rate", float(discontinuation_rate))

    sfr = float(screen_fail_rate)
    dr = float(discontinuation_rate)

    if period_type == "Screened":
        screened = float(target_n)
        randomized = screened * (1.0 - sfr)
    elif period_type == "Randomized":
        randomized = float(target_n)
        screened = randomized / (1.0 - sfr)
    else:
        raise ValidationError(f"Unsupported Recruitment Rate type: {period_type!r}")

    completed = randomized * (1.0 - dr)
    return Targets(screened=screened, randomized=randomized, completed=completed)


def _run_fixed_sites_country_scenario(
    *,
    name: str,
    period_type: str,
    target_n: int,
    fsfv: date,
    sites: int,
    screen_fail_rate: float,
    discontinuation_rate: float,
    lag_sr_days: int,
    lag_rc_days: int,
    sar_pct: list[float],
    rr_per_site_per_month: list[float],
    settings: GlobalSettings,
) -> ScenarioRunResult:
    targets = _derive_targets_from_primary_target(
        period_type=period_type,
        target_n=target_n,
        screen_fail_rate=screen_fail_rate,
        discontinuation_rate=discontinuation_rate,
    )

    solve = solve_lsfv_fixed_sites(
        fsfv=fsfv,
        sites=sites,
        period_type=period_type,  # type: ignore[arg-type]
        targets=targets,
        screen_fail_rate=screen_fail_rate,
        discontinuation_rate=discontinuation_rate,
        lag_sr_days=lag_sr_days,
        lag_rc_days=lag_rc_days,
        sar_pct=sar_pct,
        rr_per_site_per_month=rr_per_site_per_month,
        settings=settings,
    )
    if not solve.reached or solve.solved_lsfv is None:
        raise ValidationError(solve.warning or "Unable to solve LSFV.")

    return _build_country_result_for_lsfv(
        name=name,
        period_type=period_type,
        targets=targets,
        solved_lsfv=solve.solved_lsfv,
        fsfv=fsfv,
        lsfv=solve.solved_lsfv,
        sites=sites,
        screen_fail_rate=screen_fail_rate,
        discontinuation_rate=discontinuation_rate,
        lag_sr_days=lag_sr_days,
        lag_rc_days=lag_rc_days,
        sar_pct=sar_pct,
        rr_per_site_per_month=rr_per_site_per_month,
        settings=settings,
    )


def _build_country_result_for_lsfv(
    *,
    name: str,
    period_type: str,
    targets: Targets,
    solved_lsfv: date,
    fsfv: date,
    lsfv: date,
    sites: int,
    screen_fail_rate: float,
    discontinuation_rate: float,
    lag_sr_days: int,
    lag_rc_days: int,
    sar_pct: list[float],
    rr_per_site_per_month: list[float],
    settings: GlobalSettings,
) -> ScenarioRunResult:
    primary = build_primary_daily(
        fsfv=fsfv,
        lsfv=lsfv,
        sites=sites,
        sar_pct=sar_pct,
        rr_per_site_per_month=rr_per_site_per_month,
        settings=settings,
    )

    states = derive_states_from_primary(
        period_type=period_type,  # type: ignore[arg-type]
        primary_new=primary.new_primary,
        screen_fail_rate=screen_fail_rate,
        discontinuation_rate=discontinuation_rate,
        lag_sr_days=lag_sr_days,
        lag_rc_days=lag_rc_days,
    )

    timelines = derive_state_timelines(
        fsfv=fsfv,
        lsfv=lsfv,
        period_type=period_type,  # type: ignore[arg-type]
        lag_sr_days=lag_sr_days,
        lag_rc_days=lag_rc_days,
    )

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

    bucket_types = ["year", "quarter", "month", "week"]
    buckets: dict[str, dict[str, list[dict]]] = {bt: {} for bt in bucket_types}
    for bt in bucket_types:
        buckets[bt]["Screened"] = build_bucket_summary(
            incident=states.screened.incident,
            cumulative=states.screened.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore[arg-type]
            settings=settings,
        )
        buckets[bt]["Randomized"] = build_bucket_summary(
            incident=states.randomized.incident,
            cumulative=states.randomized.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore[arg-type]
            settings=settings,
        )
        buckets[bt]["Completed"] = build_bucket_summary(
            incident=states.completed.incident,
            cumulative=states.completed.cumulative,
            active_sites=primary.active_sites,
            activation_pct=primary.activation_pct,
            bucket_type=bt,  # type: ignore[arg-type]
            settings=settings,
        )

    return ScenarioRunResult(
        inputs_name=name,
        targets=targets,
        solve=SolveResult(solved_sites=sites, solved_lsfv=solved_lsfv, reached=True, warning=None),
        timelines=timelines,
        primary=primary,
        states=states,
        milestones_time=milestones_time,
        milestones_target=milestones_target,
        buckets=buckets,
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


def _value_at_or_before(series: dict[date, float], d: date) -> float:
    if not series:
        return 0.0
    if d in series:
        return float(series[d])
    eligible = [k for k in series.keys() if k <= d]
    if not eligible:
        return 0.0
    return float(series[max(eligible)])


def _init_defaults() -> None:
    today = date.today()
    defaults = {
        "adv_screen_fail_rate": 0.25,
        "adv_discontinuation_rate": 0.1,
        "adv_period_type": "Screened",
        "_adv_period_picked": False,
        "adv_driver": ADV_FIXED_DRIVER,
        "adv_lag_sr_days": 14,
        "adv_lag_rc_days": 30,
        "adv_uncertainty_enabled": False,
        "adv_uncertainty_lower_pct": 10.0,
        "adv_uncertainty_upper_pct": 10.0,
        "adv_global_fsfv": today,
        "adv_global_lsfv": _one_year_after(today),
        "adv_global_sites": 10,
        "adv_global_sar_pct": [20, 40, 60, 80, 100, 100],
        "adv_global_rr_pct": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "adv_selected_countries": ["United States"],
        "adv_country_config": {},
        "adv_map_metric": "Randomized total",
        "adv_map_view": "World",
        "adv_map_color_scheme": "blues",
        "adv_pie_enabled": False,
        "adv_pie_scope": "Global",
        "adv_pie_metric_family": "Enrollment",
        "adv_pie_state": "Randomized",
        "adv_pie_label_mode": "Both",
        "adv_pie_country": None,
        "adv_selected_country": None,
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    if st.session_state.get("adv_period_type") not in {"Screened", "Randomized"}:
        st.session_state["adv_period_type"] = "Screened"
    if st.session_state.get("adv_pie_scope") not in {"Global", "Region"}:
        st.session_state["adv_pie_scope"] = "Global"
    if st.session_state.get("adv_pie_label_mode") not in {"Percent", "Value", "Both"}:
        st.session_state["adv_pie_label_mode"] = "Both"

    st.session_state["adv_initialized"] = True


def _default_country_row(country: dict[str, Any]) -> dict[str, Any]:
    return {
        "ISO3": country["iso3"],
        "Country": country["country"],
        "Region": country.get("region", ""),
        "Subregion": country.get("subregion", ""),
        "FSFV": date.today(),
        "Sites": 10,
        "Target N": 10,
        "SAR_0": ADV_DEFAULT_SAR_PCT[0],
        "SAR_20": ADV_DEFAULT_SAR_PCT[1],
        "SAR_40": ADV_DEFAULT_SAR_PCT[2],
        "SAR_60": ADV_DEFAULT_SAR_PCT[3],
        "SAR_80": ADV_DEFAULT_SAR_PCT[4],
        "SAR_100": ADV_DEFAULT_SAR_PCT[5],
        "RR_0": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[0],
        "RR_20": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[1],
        "RR_40": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[2],
        "RR_60": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[3],
        "RR_80": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[4],
        "RR_100": ADV_DEFAULT_RR_PER_SITE_PER_MONTH[5],
    }


def _build_country_df(countries_df: pd.DataFrame, selected: list[str]) -> pd.DataFrame:
    config = st.session_state["adv_country_config"]

    rows = []
    for _, row in countries_df[countries_df["country"].isin(selected)].iterrows():
        iso = row["iso3"]
        default_row = _default_country_row(row.to_dict())
        existing_row = config.get(iso, {})
        merged_row = {**default_row, **existing_row}

        # Compatibility for legacy fixed-timeline rows loaded from older saves.
        sites = merged_row.get("Sites")
        if sites is None or (isinstance(sites, float) and pd.isna(sites)):
            merged_row["Sites"] = 10
        else:
            try:
                merged_row["Sites"] = max(1, int(sites))
            except Exception:
                merged_row["Sites"] = 10

        target_n = merged_row.get("Target N")
        if target_n is None or (isinstance(target_n, float) and pd.isna(target_n)):
            merged_row["Target N"] = 10
        else:
            try:
                merged_row["Target N"] = max(1, int(target_n))
            except Exception:
                merged_row["Target N"] = 10

        config[iso] = merged_row
        rows.append(merged_row)

    # Keep order consistent with selection
    order_map = {name: i for i, name in enumerate(selected)}
    rows.sort(key=lambda r: order_map.get(r["Country"], 0))

    return pd.DataFrame(rows)


def _update_config_from_df(df: pd.DataFrame) -> None:
    config = st.session_state["adv_country_config"]
    for _, row in df.iterrows():
        iso = row["ISO3"]
        config[iso] = row.to_dict()


def _validate_country_rows(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []

    required_cols = ["FSFV", "SAR_0", "SAR_20", "SAR_40", "SAR_60", "SAR_80", "SAR_100",
                     "RR_0", "RR_20", "RR_40", "RR_60", "RR_80", "RR_100", "Target N", "Sites"]

    for _, row in df.iterrows():
        country = row["Country"]
        for col in required_cols:
            if pd.isna(row[col]):
                errors.append(f"{country}: {col} is required.")

        fsfv = row["FSFV"]
        if not isinstance(fsfv, date):
            errors.append(f"{country}: FSFV must be a date.")

        sites = row["Sites"]
        if pd.isna(sites) or int(sites) != sites or int(sites) <= 0:
            errors.append(f"{country}: Sites must be a positive integer.")
        target_n = row["Target N"]
        if pd.isna(target_n) or int(target_n) != target_n or int(target_n) <= 0:
            errors.append(f"{country}: Target N must be a positive integer.")

        # Validate SAR/RR ranges
        sar_vals = [row[c] for c in ["SAR_0", "SAR_20", "SAR_40", "SAR_60", "SAR_80", "SAR_100"]]
        rr_vals = [row[c] for c in ["RR_0", "RR_20", "RR_40", "RR_60", "RR_80", "RR_100"]]

        for v in sar_vals:
            if pd.isna(v) or v < 0 or v > 100:
                errors.append(f"{country}: SAR values must be in [0, 100].")
                break
        for v in rr_vals:
            if pd.isna(v) or v < 0:
                errors.append(f"{country}: RR values must be >= 0.")
                break

    return errors


def _extract_country_inputs(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        iso = row["ISO3"]
        sar = [float(row[c]) for c in ["SAR_0", "SAR_20", "SAR_40", "SAR_60", "SAR_80", "SAR_100"]]
        rr = [float(row[c]) for c in ["RR_0", "RR_20", "RR_40", "RR_60", "RR_80", "RR_100"]]
        out[iso] = {
            "country": row["Country"],
            "region": row.get("Region", ""),
            "subregion": row.get("Subregion", ""),
            "fsfv": row["FSFV"],
            "sites": int(row["Sites"]),
            "target_n": int(row["Target N"]),
            "sar": sar,
            "rr": rr,
        }
    return out


def _build_uncertainty_states(
    inputs: ScenarioInputs,
    settings: GlobalSettings,
    lower_pct: float,
    upper_pct: float,
    *,
    lsfv: date,
    sites: int,
):
    primary = build_primary_daily(
        fsfv=inputs.fsfv,
        lsfv=lsfv,
        sites=sites,
        sar_pct=inputs.sar_pct,
        rr_per_site_per_month=inputs.rr_per_site_per_month,
        settings=settings,
    )

    lower_incident = scale_series(primary.new_primary, 1.0 - lower_pct / 100.0)
    upper_incident = scale_series(primary.new_primary, 1.0 + upper_pct / 100.0)

    lower_states = derive_states_from_primary(
        period_type=inputs.period_type,
        primary_new=lower_incident,
        screen_fail_rate=inputs.screen_fail_rate,
        discontinuation_rate=inputs.discontinuation_rate,
        lag_sr_days=inputs.lag_sr_days,
        lag_rc_days=inputs.lag_rc_days,
    )
    upper_states = derive_states_from_primary(
        period_type=inputs.period_type,
        primary_new=upper_incident,
        screen_fail_rate=inputs.screen_fail_rate,
        discontinuation_rate=inputs.discontinuation_rate,
        lag_sr_days=inputs.lag_sr_days,
        lag_rc_days=inputs.lag_rc_days,
    )

    return lower_states, upper_states


def render() -> None:
    st.title("Recruitment Scenario Planner — Advanced Mode")
    st.caption("Advanced Mode supports country-level targets with multi-country roll-up.")

    _init_defaults()

    if "_adv_pending_load_payload" in st.session_state:
        try:
            load_advanced_state(st.session_state["_adv_pending_load_payload"], st.session_state)
            st.session_state.pop("_adv_pending_load_payload", None)
            st.success("Loaded advanced scenario (results cleared; re-run).")
        except Exception as e:
            st.session_state.pop("_adv_pending_load_payload", None)
            st.error(f"Failed to apply loaded file: {e}")

    if st.session_state.get("adv_period_type") not in {"Screened", "Randomized"}:
        st.session_state["adv_period_type"] = "Screened"
    st.session_state["adv_driver"] = ADV_FIXED_DRIVER

    settings = GlobalSettings()
    countries_df = load_countries()

    period_options = ["(select)", "Screened", "Randomized"]
    if "adv_period_type_picker" not in st.session_state:
        if st.session_state.get("_adv_period_picked", False) and st.session_state.get("adv_period_type") in {"Screened", "Randomized"}:
            st.session_state["adv_period_type_picker"] = st.session_state["adv_period_type"]
        else:
            st.session_state["adv_period_type_picker"] = "(select)"

    selected_period = st.selectbox(
        "Recruitment Rate type (primary)",
        period_options,
        key="adv_period_type_picker",
    )
    period_selected = selected_period in {"Screened", "Randomized"}
    if period_selected:
        st.session_state["adv_period_type"] = selected_period
        st.session_state["_adv_period_picked"] = True
    else:
        st.session_state["_adv_period_picked"] = False

    st.markdown("<p style='font-size:10pt;font-weight:700;margin:0 0 0.35rem 0;'>Countries</p>", unsafe_allow_html=True)
    country_options = sorted(countries_df["country"].tolist())

    def _set_selected_countries(countries: list[str]) -> None:
        unique = [c for c in dict.fromkeys(countries) if c in country_options]
        if len(unique) > 20:
            st.session_state["adv_selected_countries"] = unique[:20]
            st.session_state["adv_country_selection_notice"] = "Selection was limited to 20 countries."
        else:
            st.session_state["adv_selected_countries"] = unique
            st.session_state.pop("adv_country_selection_notice", None)

    def _clear_selected_countries() -> None:
        st.session_state["adv_selected_countries"] = []
        st.session_state.pop("adv_country_selection_notice", None)

    if len(st.session_state.get("adv_selected_countries", [])) > 20:
        _set_selected_countries(st.session_state.get("adv_selected_countries", []))

    select_col, clear_col = st.columns([5, 1])
    with select_col:
        selected = st.multiselect(
            "Select countries (1–20)",
            options=country_options,
            key="adv_selected_countries",
            max_selections=20,
            placeholder="Search countries and select up to 20",
            disabled=not period_selected,
        )
    with clear_col:
        st.button(
            "Clear all",
            key="adv_clear_countries",
            on_click=_clear_selected_countries,
            disabled=not st.session_state.get("adv_selected_countries"),
            use_container_width=True,
        )
    if "adv_country_selection_notice" in st.session_state:
        st.info(st.session_state["adv_country_selection_notice"])

    effective_selected = selected if period_selected else []

    if not period_selected:
        st.info("Select Recruitment Rate type (primary) first to enable country selection.")
    if period_selected and not effective_selected:
        st.info("Select at least one country to configure Advanced inputs.")

    country_df = _build_country_df(countries_df, effective_selected) if effective_selected else pd.DataFrame()

    edited_df = pd.DataFrame()
    run_signature_text: str | None = None
    if not country_df.empty:
        target_col_label = (
            "Target Screened" if st.session_state["adv_period_type"] == "Screened" else "Target Randomized"
        )
        cols = [
            "ISO3",
            "Country",
            "Region",
            "Subregion",
            "FSFV",
            "Sites",
            "Target N",
            "SAR_0",
            "SAR_20",
            "SAR_40",
            "SAR_60",
            "SAR_80",
            "SAR_100",
            "RR_0",
            "RR_20",
            "RR_40",
            "RR_60",
            "RR_80",
            "RR_100",
        ]
        country_df = country_df[cols]
        country_df_ui = country_df.rename(columns={"Target N": target_col_label})

        st.markdown(
            "<p style='font-size:10pt;font-weight:700;margin:0.6rem 0 0.35rem 0;'>Country Configuration</p>",
            unsafe_allow_html=True,
        )
        column_config = {
            "ISO3": st.column_config.TextColumn(disabled=True),
            "Country": st.column_config.TextColumn(disabled=True),
            "Region": st.column_config.TextColumn(disabled=True),
            "Subregion": st.column_config.TextColumn(disabled=True),
            "FSFV": st.column_config.DateColumn(format=DATE_INPUT_FORMAT),
            "Sites": st.column_config.NumberColumn(min_value=1, step=1),
            target_col_label: st.column_config.NumberColumn(min_value=1, step=1),
        }

        period_editor_key = "_adv_last_period_type_for_editor"
        if st.session_state.get(period_editor_key) != st.session_state["adv_period_type"]:
            st.session_state.pop("adv_country_editor", None)
            st.session_state[period_editor_key] = st.session_state["adv_period_type"]

        edited_df_ui = st.data_editor(
            country_df_ui,
            num_rows="fixed",
            width="stretch",
            key="adv_country_editor",
            column_config=column_config,
        )
        edited_df = edited_df_ui.rename(columns={target_col_label: "Target N"})
        _update_config_from_df(edited_df)

        errors = _validate_country_rows(edited_df)
        fsfvs = [row["FSFV"] for _, row in edited_df.iterrows() if isinstance(row["FSFV"], date)]
        if fsfvs:
            st.info(f"Derived global FSFV (earliest): {_format_date(min(fsfvs))}")

        if "adv_results" in st.session_state:
            primary_state = "Screened" if st.session_state["adv_period_type"] == "Screened" else "Randomized"
            milestone_rows = []
            for country_result in st.session_state["adv_results"].get("countries", []):
                out = country_result.get("result")
                if not out:
                    continue
                primary_cumulative_series = (
                    out.states.screened.cumulative if primary_state == "Screened" else out.states.randomized.cumulative
                )
                for pct, milestone_date in zip([0, 20, 40, 60, 80, 100], _milestone_dates(out.primary.fsfv, out.primary.lsfv)):
                    active_sites = float(out.primary.active_sites.get(milestone_date, 0.0))
                    total_primary_month = float(out.primary.new_primary.get(milestone_date, 0.0)) * settings.days_per_month
                    rr_per_site_month = total_primary_month / active_sites if active_sites > 0 else 0.0
                    milestone_rows.append(
                        {
                            "Country": country_result["country"],
                            "Milestone %": pct,
                            "Milestone Date": milestone_date,
                            "SAR % (input milestone)": out.primary.activation_pct.get(milestone_date, 0.0),
                            f"RR {primary_state}/site/month (input milestone)": rr_per_site_month,
                            f"Incident {primary_state}/month (RR milestone)": total_primary_month,
                            f"Cumulative {primary_state} (to milestone date)": _value_at_or_before(
                                primary_cumulative_series, milestone_date
                            ),
                            "Active Sites (SAR milestone)": active_sites,
                        }
                    )
            if milestone_rows:
                st.markdown("### Country SAR/RR Milestone Outputs")
                milestone_df = pd.DataFrame(milestone_rows)
                milestone_df = _format_dataframe_dates(milestone_df)
                milestone_df = _format_dataframe_numbers(milestone_df)
                st.dataframe(milestone_df, width="stretch")
    else:
        errors = []

    if effective_selected:
        with st.expander("Global Inputs", expanded=True):
            gcol1, gcol2, gcol3, gcol4 = st.columns(4)
            with gcol1:
                st.number_input(
                    "Lag Screened → Randomized (days)",
                    min_value=0,
                    step=1,
                    key="adv_lag_sr_days",
                )
            with gcol2:
                st.slider("Screen fail rate", 0.0, 0.99, key="adv_screen_fail_rate")
            with gcol3:
                st.number_input(
                    "Lag Randomized → Completed (days)",
                    min_value=0,
                    step=1,
                    key="adv_lag_rc_days",
                )
            with gcol4:
                st.slider("Discontinuation rate", 0.0, 0.99, key="adv_discontinuation_rate")

            st.markdown(
                "<p style='font-size:10pt;font-weight:700;margin:0.6rem 0 0.35rem 0;'>Global Uncertainty</p>",
                unsafe_allow_html=True,
            )
            ucol1, ucol2, ucol3 = st.columns([1, 1, 1])
            with ucol1:
                st.checkbox("Enable uncertainty", key="adv_uncertainty_enabled")
            with ucol2:
                st.number_input(
                    "Lower % (below)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="adv_uncertainty_lower_pct",
                )
            with ucol3:
                st.number_input(
                    "Upper % (above)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="adv_uncertainty_upper_pct",
                )

    if not edited_df.empty:
        run_signature_text = (
            f"{edited_df.to_json(date_format='iso', orient='split')}|"
            f"{st.session_state['adv_period_type']}|"
            f"{st.session_state['adv_lag_sr_days']}|{st.session_state['adv_lag_rc_days']}|"
            f"{st.session_state['adv_screen_fail_rate']}|{st.session_state['adv_discontinuation_rate']}"
        )
        if "adv_results" in st.session_state:
            last_run_signature = st.session_state.get("_adv_last_run_signature")
            if last_run_signature and last_run_signature != run_signature_text:
                st.session_state["_adv_results_stale"] = True

    if errors:
        st.error("Please fix the following before running:")
        for e in errors:
            st.write(f"- {e}")

    if st.session_state.get("_adv_results_stale", False):
        st.warning("Current results are stale due to input changes. Re-run Advanced Scenario to refresh outputs.")

    can_run = period_selected and bool(effective_selected) and not errors and len(effective_selected) <= 20 and not edited_df.empty

    if st.button("Run Advanced Scenario", type="primary", disabled=not can_run):
        try:
            country_inputs = _extract_country_inputs(edited_df)

            results = []
            warnings = []

            for iso, c in country_inputs.items():
                try:
                    result = _run_fixed_sites_country_scenario(
                        name=c["country"],
                        period_type=st.session_state["adv_period_type"],
                        target_n=int(c["target_n"]),
                        fsfv=c["fsfv"],
                        sites=int(c["sites"]),
                        screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                        discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                        lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                        lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                        sar_pct=c["sar"],
                        rr_per_site_per_month=c["rr"],
                        settings=settings,
                    )
                    status = "ok"
                    warning = None
                except ValidationError as e:
                    result = None
                    status = "failed"
                    warning = str(e)

                uncertainty = None
                pessimistic_solve = None
                optimistic_solve = None

                if result and st.session_state["adv_uncertainty_enabled"]:
                    lower_pct = float(st.session_state["adv_uncertainty_lower_pct"])
                    upper_pct = float(st.session_state["adv_uncertainty_upper_pct"])

                    uncertainty_inputs = ScenarioInputs(
                        name=c["country"],
                        goal_type="Randomized",
                        goal_n=int(c["target_n"]),
                        screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                        discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                        period_type=st.session_state["adv_period_type"],  # type: ignore[arg-type]
                        driver=ADV_FIXED_DRIVER,
                        fsfv=c["fsfv"],
                        lsfv=None,
                        sites=int(c["sites"]),
                        lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                        lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                        sar_pct=c["sar"],
                        rr_per_site_per_month=c["rr"],
                    )
                    lower_states, upper_states = _build_uncertainty_states(
                        uncertainty_inputs,
                        settings,
                        lower_pct,
                        upper_pct,
                        lsfv=result.primary.lsfv,
                        sites=result.primary.sites,
                    )

                    targets = _derive_targets_from_primary_target(
                        period_type=st.session_state["adv_period_type"],
                        target_n=int(c["target_n"]),
                        screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                        discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                    )
                    pessimistic_solve = solve_lsfv_fixed_sites(
                        fsfv=c["fsfv"],
                        sites=int(c["sites"]),
                        period_type=st.session_state["adv_period_type"],  # type: ignore[arg-type]
                        targets=targets,
                        screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                        discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                        lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                        lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                        sar_pct=c["sar"],
                        rr_per_site_per_month=c["rr"],
                        settings=settings,
                        throughput_multiplier=max(0.0, 1.0 - lower_pct / 100.0),
                    )
                    optimistic_solve = solve_lsfv_fixed_sites(
                        fsfv=c["fsfv"],
                        sites=int(c["sites"]),
                        period_type=st.session_state["adv_period_type"],  # type: ignore[arg-type]
                        targets=targets,
                        screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                        discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                        lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                        lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                        sar_pct=c["sar"],
                        rr_per_site_per_month=c["rr"],
                        settings=settings,
                        throughput_multiplier=1.0 + upper_pct / 100.0,
                    )
                    uncertainty = {
                        "lower_states": lower_states,
                        "upper_states": upper_states,
                    }
                    if pessimistic_solve and not pessimistic_solve.reached:
                        warnings.append(f"{c['country']}: pessimistic solve unreachable within guardrails.")

                results.append({
                    "iso3": iso,
                    "country": c["country"],
                    "region": c["region"],
                    "subregion": c["subregion"],
                    "input_config": c,
                    "input_target_n": int(c["target_n"]),
                    "status": status,
                    "warning": warning,
                    "result": result,
                    "uncertainty": uncertainty,
                    "optimistic_solve": optimistic_solve,
                    "pessimistic_solve": pessimistic_solve,
                })

            ok_results = [r for r in results if r["status"] == "ok" and r["result"]]
            solved_lsfv_values = [
                r["result"].solve.solved_lsfv
                for r in ok_results
                if r["result"] and r["result"].solve.solved_lsfv is not None
            ]
            latest_solved_lsfv = max(solved_lsfv_values) if solved_lsfv_values else None

            # Competitive recruitment behavior: once open, a country remains active
            # until the latest solved LSFV across the selected countries.
            if latest_solved_lsfv is not None:
                for r in results:
                    out = r.get("result")
                    if not out:
                        continue
                    input_cfg = r.get("input_config", {})
                    if latest_solved_lsfv > out.primary.lsfv:
                        r["result"] = _build_country_result_for_lsfv(
                            name=r["country"],
                            period_type=st.session_state["adv_period_type"],
                            targets=out.targets,
                            solved_lsfv=out.solve.solved_lsfv or out.primary.lsfv,
                            fsfv=input_cfg.get("fsfv", out.primary.fsfv),
                            lsfv=latest_solved_lsfv,
                            sites=int(input_cfg.get("sites", out.primary.sites)),
                            screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                            discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                            lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                            lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                            sar_pct=list(input_cfg.get("sar", [20, 40, 60, 80, 100, 100])),
                            rr_per_site_per_month=list(input_cfg.get("rr", [1.0, 1.0, 1.0, 1.0, 1.0, 1.0])),
                            settings=settings,
                        )

                    if st.session_state["adv_uncertainty_enabled"] and r.get("uncertainty") is not None:
                        uncertainty_inputs = ScenarioInputs(
                            name=r["country"],
                            goal_type="Randomized",
                            goal_n=int(r.get("input_target_n", 1)),
                            screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                            discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                            period_type=st.session_state["adv_period_type"],  # type: ignore[arg-type]
                            driver=ADV_FIXED_DRIVER,
                            fsfv=input_cfg.get("fsfv", out.primary.fsfv),
                            lsfv=None,
                            sites=int(input_cfg.get("sites", out.primary.sites)),
                            lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                            lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                            sar_pct=list(input_cfg.get("sar", [20, 40, 60, 80, 100, 100])),
                            rr_per_site_per_month=list(input_cfg.get("rr", [1.0, 1.0, 1.0, 1.0, 1.0, 1.0])),
                        )
                        lower_states, upper_states = _build_uncertainty_states(
                            uncertainty_inputs,
                            settings,
                            float(st.session_state["adv_uncertainty_lower_pct"]),
                            float(st.session_state["adv_uncertainty_upper_pct"]),
                            lsfv=latest_solved_lsfv,
                            sites=int(input_cfg.get("sites", out.primary.sites)),
                        )
                        r["uncertainty"] = {
                            "lower_states": lower_states,
                            "upper_states": upper_states,
                        }

            ok_results = [r for r in results if r["status"] == "ok" and r["result"]]
            global_states = aggregate_states([r["result"].states for r in ok_results]) if ok_results else None

            global_uncertainty = None
            if st.session_state["adv_uncertainty_enabled"] and ok_results:
                lower_sets = [r["uncertainty"]["lower_states"] for r in ok_results if r["uncertainty"]]
                upper_sets = [r["uncertainty"]["upper_states"] for r in ok_results if r["uncertainty"]]
                if lower_sets and upper_sets:
                    global_uncertainty = {
                        "lower": aggregate_states(lower_sets),
                        "upper": aggregate_states(upper_sets),
                    }

            lslv_values = [r["result"].timelines.completed_lslv for r in ok_results]
            global_lslv = max(lslv_values) if lslv_values else None

            st.session_state["adv_results"] = {
                "countries": results,
                "global_states": global_states,
                "global_uncertainty": global_uncertainty,
                "global_lslv": global_lslv,
                "warnings": warnings,
            }
            st.session_state["_adv_results_stale"] = False
            if run_signature_text is not None:
                st.session_state["_adv_last_run_signature"] = run_signature_text

            st.success("Advanced scenario run complete.")
        except Exception as e:
            st.exception(e)

    # ---- Results ----
    if "adv_results" in st.session_state:
        res = st.session_state["adv_results"]
        if res.get("warnings"):
            for w in res["warnings"]:
                st.warning(w)

        primary_state = "Screened" if st.session_state["adv_period_type"] == "Screened" else "Randomized"
        run_input_rows = []
        for r in res["countries"]:
            out = r.get("result")
            if not out:
                continue
            solved_lsfv = out.solve.solved_lsfv or out.primary.lsfv
            solved_endpoint = solved_lsfv - timedelta(days=1)
            cumulative_primary_solved = (
                _value_at_or_before(out.states.screened.cumulative, solved_endpoint)
                if primary_state == "Screened"
                else _value_at_or_before(out.states.randomized.cumulative, solved_endpoint)
            )
            run_input_rows.append(
                {
                    "Country": r["country"],
                    f"Input Target {primary_state} (used)": r.get("input_target_n"),
                    f"Cumulative {primary_state} at Solved LSFV": cumulative_primary_solved,
                    "Sites (used)": out.primary.sites,
                    "FSFV (used)": out.primary.fsfv,
                    "LSFV (solved target)": solved_lsfv,
                    "Enrollment End LSFV": out.primary.lsfv,
                }
            )
        if run_input_rows:
            st.markdown("## Run Inputs Used")
            run_input_df = pd.DataFrame(run_input_rows)
            run_input_df = _format_dataframe_dates(run_input_df)
            run_input_df = _format_dataframe_numbers(run_input_df)
            st.dataframe(run_input_df, width="stretch")

        st.markdown("## Country Summary")
        target_input_col = f"Input Target {primary_state}"
        cumulative_primary_col = f"Cumulative {primary_state} at Solved LSFV"
        rows = []
        totals = {
            "screened_100": 0.0,
            "randomized_100": 0.0,
            "completed_100": 0.0,
            "sites_100": 0.0,
            "input_target_n": 0.0,
        }
        fsfv_values: list[date] = []
        fslv_values: list[date] = []
        lsfv_values: list[date] = []
        lslv_values: list[date] = []

        for r in res["countries"]:
            out = r.get("result")
            if not out:
                continue

            solved_endpoint = out.primary.lsfv - timedelta(days=1)
            total_screened_100 = _value_at_or_before(out.states.screened.cumulative, solved_endpoint)
            total_randomized_100 = _value_at_or_before(out.states.randomized.cumulative, solved_endpoint)
            total_completed_100 = _value_at_or_before(out.states.completed.cumulative, solved_endpoint)
            total_sites_100 = _value_at_or_before(out.primary.active_sites, solved_endpoint)
            primary_cumulative_solved = total_screened_100 if primary_state == "Screened" else total_randomized_100

            totals["screened_100"] += total_screened_100
            totals["randomized_100"] += total_randomized_100
            totals["completed_100"] += total_completed_100
            totals["sites_100"] += total_sites_100
            totals["input_target_n"] += float(r.get("input_target_n", 0.0))
            fsfv_values.append(out.primary.fsfv)
            fslv_values.append(out.timelines.completed_fsfv)
            lsfv_values.append(out.primary.lsfv)
            lslv_values.append(out.timelines.completed_lslv)

            rows.append(
                {
                    "Country": r["country"],
                    "Region": r["region"],
                    target_input_col: r.get("input_target_n"),
                    cumulative_primary_col: primary_cumulative_solved,
                    "Total Screened at RR = 100": total_screened_100,
                    "Total Randomized at RR = 100": total_randomized_100,
                    "Total Completed at RR = 100": total_completed_100,
                    "Total Sites at SAR = 100": total_sites_100,
                    "FSFV": out.primary.fsfv,
                    "FSLV": out.timelines.completed_fsfv,
                    "LSFV": out.solve.solved_lsfv or out.primary.lsfv,
                    "Enrollment End LSFV": out.primary.lsfv,
                    "LSLV": out.timelines.completed_lslv,
                    "Status": r["status"],
                }
            )

        if rows:
            rows.append(
                {
                    "Country": "Global",
                    "Region": "-",
                    target_input_col: totals["input_target_n"],
                    cumulative_primary_col: totals["screened_100"] if primary_state == "Screened" else totals["randomized_100"],
                    "Total Screened at RR = 100": totals["screened_100"],
                    "Total Randomized at RR = 100": totals["randomized_100"],
                    "Total Completed at RR = 100": totals["completed_100"],
                    "Total Sites at SAR = 100": totals["sites_100"],
                    "FSFV": min(fsfv_values) if fsfv_values else None,
                    "FSLV": min(fslv_values) if fslv_values else None,
                    "LSFV": max(
                        [(row["result"].solve.solved_lsfv or row["result"].primary.lsfv) for row in res["countries"] if row.get("result")]
                    ) if rows else None,
                    "Enrollment End LSFV": max(lsfv_values) if lsfv_values else None,
                    "LSLV": max(lslv_values) if lslv_values else None,
                    "Status": "ok",
                }
            )

        summary_df = pd.DataFrame(rows)
        summary_df = _format_dataframe_dates(summary_df)
        summary_df = _format_dataframe_numbers(summary_df)
        st.dataframe(summary_df, width="stretch")

        st.markdown("## Global Roll-up")
        if res["global_lslv"]:
            st.write(f"Global LSLV (latest across countries): {_format_date(res['global_lslv'])}")
        else:
            st.info("No global LSLV available (no successful countries).")

        ok_results = [r for r in res["countries"] if r["status"] == "ok" and r["result"]]

        # Global chart (global + countries)
        if res["global_states"] and ok_results:
            col1, col2, col3 = st.columns(3)
            g_scr = res["global_states"].screened.cumulative
            g_rand = res["global_states"].randomized.cumulative
            g_comp = res["global_states"].completed.cumulative
            col1.metric("Global Screened", _format_number(max(g_scr.values()) if g_scr else 0.0))
            col2.metric("Global Randomized", _format_number(max(g_rand.values()) if g_rand else 0.0))
            col3.metric("Global Completed", _format_number(max(g_comp.values()) if g_comp else 0.0))

            st.markdown("### Global + Country Cumulative Curves")
            gstate = st.selectbox("State", ["Screened", "Randomized", "Completed"], key="adv_global_state")

            st.markdown("#### Line colors")
            global_line_color = st.color_picker(
                "Global cumulative enrollment line",
                value=st.session_state.get("adv_global_line_color", "#1b9e77"),
                key="adv_global_line_color",
            )

            country_palette = [
                "#1f77b4",
                "#ff7f0e",
                "#2ca02c",
                "#d62728",
                "#9467bd",
                "#8c564b",
                "#e377c2",
                "#7f7f7f",
                "#bcbd22",
                "#17becf",
            ]
            country_entries = [(r["country"], r["iso3"]) for r in ok_results]
            country_color_map = {}
            with st.expander("Country line colors", expanded=False):
                for idx, (name, iso) in enumerate(country_entries):
                    key = f"adv_country_color_{iso}"
                    default_color = st.session_state.get(key, country_palette[idx % len(country_palette)])
                    country_color_map[name] = st.color_picker(name, value=default_color, key=key)

            rows = []
            for r in ok_results:
                out = r["result"]
                series = {
                    "Screened": out.states.screened.cumulative,
                    "Randomized": out.states.randomized.cumulative,
                    "Completed": out.states.completed.cumulative,
                }[gstate]
                for d, v in series.items():
                    rows.append({"date": d, "value": v, "country": r["country"]})

            global_series = {
                "Screened": res["global_states"].screened.cumulative,
                "Randomized": res["global_states"].randomized.cumulative,
                "Completed": res["global_states"].completed.cumulative,
            }[gstate]
            for d, v in global_series.items():
                rows.append({"date": d, "value": v, "country": "Global"})

            df = pd.DataFrame(rows).sort_values("date")
            domain_min = _coerce_to_date(df["date"].min())
            if res.get("global_lslv"):
                domain_max = _coerce_to_date(res["global_lslv"] + pd.Timedelta(days=30))
            else:
                domain_max = _coerce_to_date(df["date"].max())
            global_range_key = "adv_global_curve_date_range"
            selected_range = st.session_state.get(global_range_key, (domain_min, domain_max))
            range_start, range_end = _resolve_date_range(selected_range, domain_min, domain_max)

            layers = []
            if res.get("global_uncertainty"):
                lower = {
                    "Screened": res["global_uncertainty"]["lower"].screened.cumulative,
                    "Randomized": res["global_uncertainty"]["lower"].randomized.cumulative,
                    "Completed": res["global_uncertainty"]["lower"].completed.cumulative,
                }[gstate]
                upper = {
                    "Screened": res["global_uncertainty"]["upper"].screened.cumulative,
                    "Randomized": res["global_uncertainty"]["upper"].randomized.cumulative,
                    "Completed": res["global_uncertainty"]["upper"].completed.cumulative,
                }[gstate]
                df_band = pd.DataFrame({
                    "date": list(lower.keys()),
                    "lower": list(lower.values()),
                    "upper": [upper.get(d, 0.0) for d in lower.keys()],
                }).sort_values("date")
                layers.append(
                    alt.Chart(df_band)
                    .mark_area(opacity=0.18)
                    .encode(
                        x=alt.X(
                            "date:T",
                            scale=alt.Scale(domain=[range_start, range_end]),
                            axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                        ),
                        y="lower:Q",
                        y2="upper:Q",
                    )
                )

            country_domain = [name for name, _ in country_entries]
            country_range = [country_color_map.get(name, country_palette[i % len(country_palette)]) for i, name in enumerate(country_domain)]

            countries_line = (
                alt.Chart(df)
                .transform_filter(alt.datum.country != "Global")
                .mark_line()
                .encode(
                    x=alt.X(
                        "date:T",
                        title="Date",
                        scale=alt.Scale(domain=[range_start, range_end]),
                        axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                    ),
                    y=alt.Y("value:Q", title="Cumulative"),
                    color=alt.Color(
                        "country:N",
                        title="Country",
                        scale=alt.Scale(domain=country_domain, range=country_range),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                        alt.Tooltip("country:N", title="Country"),
                        alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
                    ],
                )
            )

            global_line = (
                alt.Chart(df)
                .transform_filter(alt.datum.country == "Global")
                .mark_line(color=global_line_color, strokeWidth=4)
                .encode(
                    x=alt.X(
                        "date:T",
                        scale=alt.Scale(domain=[range_start, range_end]),
                        axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                    ),
                    y=alt.Y("value:Q"),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                        alt.Tooltip("country:N", title="Series"),
                        alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
                    ],
                )
            )

            layers.extend([countries_line, global_line])
            st.altair_chart(alt.layer(*layers).properties(height=320), width="stretch")
            st.slider(
                "X-axis date range",
                min_value=domain_min,
                max_value=domain_max,
                value=(range_start, range_end),
                key=global_range_key,
            )

            # Site activation chart
            st.markdown("### Site Activation Over Time")
            global_sites_color = st.color_picker(
                "Global active sites line",
                value=st.session_state.get("adv_global_sites_line_color", "#1b9e77"),
                key="adv_global_sites_line_color",
            )
            monthly_rows = []
            for r in ok_results:
                out = r["result"]
                if not out.primary.active_sites:
                    continue
                df_sites = pd.DataFrame(
                    {
                        "date": list(out.primary.active_sites.keys()),
                        "active_sites": list(out.primary.active_sites.values()),
                    }
                ).sort_values("date")
                df_sites["month"] = df_sites["date"].apply(lambda d: date(d.year, d.month, 1))
                # Use first available day in each month so the first displayed point
                # aligns with FSFV (0% milestone) for that country.
                monthly = (
                    df_sites.groupby("month", as_index=False)
                    .agg(active_sites=("active_sites", "first"))
                    .sort_values("month")
                )
                monthly["country"] = r["country"]
                monthly_rows.append(monthly)

            if monthly_rows:
                bars_df = pd.concat(monthly_rows, ignore_index=True)
                global_monthly = (
                    bars_df.groupby("month", as_index=False)["active_sites"]
                    .sum()
                    .rename(columns={"active_sites": "global_active_sites_snapshot"})
                    .sort_values("month")
                )

                domain_min = bars_df["month"].min()
                if res.get("global_lslv"):
                    domain_max = _coerce_to_date(res["global_lslv"] + pd.Timedelta(days=30))
                else:
                    domain_max = _coerce_to_date(bars_df["month"].max())
                domain_min = _coerce_to_date(domain_min)
                site_range_key = "adv_site_activation_date_range"
                selected_site_range = st.session_state.get(site_range_key, (domain_min, domain_max))
                site_range_start, site_range_end = _resolve_date_range(selected_site_range, domain_min, domain_max)

                bar = (
                    alt.Chart(bars_df)
                    .mark_bar(size=18)
                    .encode(
                        x=alt.X(
                            "month:T",
                            title="Month",
                            scale=alt.Scale(domain=[site_range_start, site_range_end]),
                            axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                        ),
                        xOffset=alt.XOffset("country:N"),
                        y=alt.Y("active_sites:Q", title="Active Sites (Month Start Snapshot)"),
                        color=alt.Color(
                            "country:N",
                            title="Country",
                            scale=alt.Scale(domain=country_domain, range=country_range),
                        ),
                        tooltip=[
                            alt.Tooltip("month:T", title="Month", format=DATE_DISPLAY_FORMAT),
                            alt.Tooltip("country:N", title="Country"),
                            alt.Tooltip("active_sites:Q", title="Active Sites", format=".1f"),
                        ],
                    )
                )

                line = (
                    alt.Chart(global_monthly)
                    .mark_line(color=global_sites_color, strokeWidth=4)
                    .encode(
                        x=alt.X(
                            "month:T",
                            scale=alt.Scale(domain=[site_range_start, site_range_end]),
                            axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                        ),
                        y=alt.Y(
                            "global_active_sites_snapshot:Q",
                            axis=alt.Axis(title="Global Active Sites", orient="right"),
                        ),
                        tooltip=[
                            alt.Tooltip("month:T", title="Month", format=DATE_DISPLAY_FORMAT),
                            alt.Tooltip("global_active_sites_snapshot:Q", title="Global Active Sites", format=".1f"),
                        ],
                    )
                )

                chart = alt.layer(bar, line).resolve_scale(y="independent").properties(height=320)
                st.altair_chart(chart, width="stretch")
                st.slider(
                    "X-axis date range",
                    min_value=domain_min,
                    max_value=domain_max,
                    value=(site_range_start, site_range_end),
                    key=site_range_key,
                )
            else:
                st.info("No site activation data available for selected countries.")

        # Country drill-down
        st.markdown("## Country Drill-down")
        if ok_results:
            country_names = [r["country"] for r in ok_results]
            default_country = st.session_state.get("adv_selected_country")
            if default_country in country_names:
                default_index = country_names.index(default_country)
            else:
                default_index = 0
            sel_country = st.selectbox(
                "Country",
                country_names,
                index=default_index,
                key="adv_selected_country",
            )
            country_map = {r["country"]: r for r in ok_results}
            country_result = country_map.get(sel_country)
            if not country_result:
                st.warning("Selected country not available in results. Showing the first available country.")
                country_result = ok_results[0]
            out = country_result["result"]

            state_series_map = {
                "Screened": out.states.screened.cumulative,
                "Randomized": out.states.randomized.cumulative,
                "Completed": out.states.completed.cumulative,
            }
            rows = []
            for state_name, series in state_series_map.items():
                for d, v in series.items():
                    rows.append({"date": d, "value": v, "state": state_name})
            df = pd.DataFrame(rows).sort_values("date")
            domain_min = _coerce_to_date(df["date"].min())
            domain_max = _coerce_to_date(out.timelines.completed_lslv + pd.Timedelta(days=30))
            country_range_key = "adv_country_curve_date_range"
            selected_country_range = st.session_state.get(country_range_key, (domain_min, domain_max))
            country_range_start, country_range_end = _resolve_date_range(
                selected_country_range, domain_min, domain_max
            )
            state_domain = ["Screened", "Randomized", "Completed"]
            state_colors = ["#09CFEA", "#2CA02C", "#FF7F0E"]
            st.altair_chart(
                alt.Chart(df)
                .mark_line()
                .encode(
                    x=alt.X(
                        "date:T",
                        scale=alt.Scale(domain=[country_range_start, country_range_end]),
                        axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                    ),
                    y=alt.Y("value:Q", title="Cumulative # of Subjects"),
                    color=alt.Color(
                        "state:N",
                        title="# of Subjects",
                        scale=alt.Scale(domain=state_domain, range=state_colors),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                        alt.Tooltip("state:N", title="State"),
                        alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
                    ],
                )
                .properties(height=320),
                width="stretch",
            )
            st.slider(
                "X-axis date range",
                min_value=domain_min,
                max_value=domain_max,
                value=(country_range_start, country_range_end),
                key=country_range_key,
            )
        else:
            st.info("No successful countries to display.")

        # Map + pie
        st.markdown("## Map View")
        map_control_col1, map_control_col2, map_control_col3 = st.columns(3)
        with map_control_col1:
            metric = st.selectbox(
                "Heat map metric",
                [
                    "Randomized total",
                    "Completed total",
                    "Screened total",
                    "Sites",
                    "Randomized % of global",
                    "Completed % of global",
                    "Screened % of global",
                ],
                key="adv_map_metric",
            )
        with map_control_col2:
            view = st.selectbox(
                "Map view",
                ["World"] + sorted(countries_df["region"].dropna().unique().tolist()),
                key="adv_map_view",
            )
        with map_control_col3:
            map_color_schemes = [
                "blues",
                "teals",
                "greens",
                "oranges",
                "reds",
                "viridis",
                "magma",
                "inferno",
                "plasma",
                "turbo",
            ]
            st.selectbox(
                "Heat map color range",
                map_color_schemes,
                key="adv_map_color_scheme",
                format_func=lambda s: s.title(),
            )

        # Build metric df
        map_rows = []
        omitted_map_countries = []
        global_totals = {"screened": 0.0, "randomized": 0.0, "completed": 0.0}
        for r in res["countries"]:
            if r["result"]:
                out = r["result"]
                global_totals["screened"] += max(out.states.screened.cumulative.values()) if out.states.screened.cumulative else 0.0
                global_totals["randomized"] += max(out.states.randomized.cumulative.values()) if out.states.randomized.cumulative else 0.0
                global_totals["completed"] += max(out.states.completed.cumulative.values()) if out.states.completed.cumulative else 0.0

        for r in res["countries"]:
            if not r["result"]:
                omitted_map_countries.append(r.get("country", "Unknown"))
                continue
            out = r["result"]
            screened_total = max(out.states.screened.cumulative.values()) if out.states.screened.cumulative else 0.0
            randomized_total = max(out.states.randomized.cumulative.values()) if out.states.randomized.cumulative else 0.0
            completed_total = max(out.states.completed.cumulative.values()) if out.states.completed.cumulative else 0.0
            map_rows.append({
                "iso3": r["iso3"],
                "country": r["country"],
                "region": r["region"],
                "screened_total": screened_total,
                "randomized_total": randomized_total,
                "completed_total": completed_total,
                "sites": out.primary.sites,
            })

        map_df_all = pd.DataFrame(map_rows).copy()
        map_df = map_df_all.copy()
        if view != "World":
            map_df = map_df[map_df["region"] == view]
        map_df = map_df.copy()

        if not map_df.empty:
            map_df = map_df.merge(
                countries_df[["iso3", "m49_code"]].drop_duplicates(),
                on="iso3",
                how="left",
            )
            map_df["m49_id"] = pd.to_numeric(map_df["m49_code"], errors="coerce")

            if metric == "Randomized total":
                map_df["metric"] = map_df["randomized_total"]
            elif metric == "Completed total":
                map_df["metric"] = map_df["completed_total"]
            elif metric == "Screened total":
                map_df["metric"] = map_df["screened_total"]
            elif metric == "Sites":
                map_df["metric"] = map_df["sites"]
            elif metric == "Randomized % of global":
                denom = global_totals["randomized"] or 1.0
                map_df["metric"] = map_df["randomized_total"] / denom * 100.0
            elif metric == "Completed % of global":
                denom = global_totals["completed"] or 1.0
                map_df["metric"] = map_df["completed_total"] / denom * 100.0
            else:
                denom = global_totals["screened"] or 1.0
                map_df["metric"] = map_df["screened_total"] / denom * 100.0

            world_topology = alt.topo_feature(
                "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json",
                "countries",
            )
            map_lookup_df = map_df.dropna(subset=["m49_id"]).copy()
            map_lookup_df["m49_id"] = map_lookup_df["m49_id"].astype(int)

            base_layer = (
                alt.Chart(world_topology)
                .mark_geoshape(fill="#F5F7FA", stroke="#DCE3EB", strokeWidth=0.6)
                .project(type="equalEarth")
            )

            metric_format = ".1f"
            if "%" in metric:
                metric_format = ".2f"

            if not map_lookup_df.empty:
                lookup_rows = []
                for _, row in map_lookup_df.iterrows():
                    m49_id = row.get("m49_id")
                    if pd.isna(m49_id):
                        continue
                    try:
                        m49_int = int(m49_id)
                    except Exception:
                        continue
                    base = {
                        "country": row.get("country"),
                        "region": row.get("region"),
                        "metric": row.get("metric"),
                    }
                    lookup_rows.append({"lookup_id": str(m49_int), **base})
                    lookup_rows.append({"lookup_id": f"{m49_int:03d}", **base})
                map_lookup_norm_df = pd.DataFrame(lookup_rows)

                choropleth_layer = (
                    alt.Chart(world_topology)
                    .mark_geoshape(stroke="#DCE3EB", strokeWidth=0.6)
                    .transform_calculate(lookup_id="toString(datum.id)")
                    .transform_lookup(
                        lookup="lookup_id",
                        from_=alt.LookupData(map_lookup_norm_df, "lookup_id", ["country", "region", "metric"]),
                    )
                    .transform_filter("isValid(datum.metric)")
                    .encode(
                        color=alt.Color(
                            "metric:Q",
                            title=metric,
                            scale=alt.Scale(scheme=st.session_state["adv_map_color_scheme"]),
                        ),
                        tooltip=[
                            alt.Tooltip("country:N", title="Country"),
                            alt.Tooltip("region:N", title="Region"),
                            alt.Tooltip("metric:Q", title=metric, format=metric_format),
                        ],
                    )
                    .project(type="equalEarth")
                )
                st.altair_chart(
                    alt.layer(base_layer, choropleth_layer).properties(height=520),
                    width="stretch",
                )
            else:
                st.altair_chart(base_layer.properties(height=520), width="stretch")
                st.info("No matched country geometries available for selected map data.")

            if omitted_map_countries:
                omitted_list = ", ".join(sorted(dict.fromkeys(omitted_map_countries)))
                st.warning(f"Omitted from map (no solved result): {omitted_list}")

            st.checkbox("Show pie", key="adv_pie_enabled")
            if st.session_state["adv_pie_enabled"]:
                st.markdown("### Pie View")
                pie_scope = st.selectbox("Pie scope", ["Global", "Region"], key="adv_pie_scope")
                st.selectbox("Metric family", ["Enrollment", "Sites"], key="adv_pie_metric_family")
                st.selectbox("State", ["Screened", "Randomized", "Completed"], key="adv_pie_state")
                st.selectbox("Label mode", ["Percent", "Value", "Both"], key="adv_pie_label_mode")

                pie_df = map_df_all.copy() if pie_scope == "Global" else map_df.copy()
                names_col = "country"
                if pie_scope == "Region":
                    pie_df = pie_df.groupby("region", as_index=False).sum(numeric_only=True)
                    names_col = "region"

                if st.session_state["adv_pie_metric_family"] == "Sites":
                    pie_df["pie_value"] = pie_df["sites"]
                else:
                    state = st.session_state["adv_pie_state"]
                    if state == "Screened":
                        pie_df["pie_value"] = pie_df["screened_total"]
                    elif state == "Completed":
                        pie_df["pie_value"] = pie_df["completed_total"]
                    else:
                        pie_df["pie_value"] = pie_df["randomized_total"]

                if not pie_df.empty:
                    fig_pie = px.pie(
                        pie_df,
                        names=names_col,
                        values="pie_value",
                    )
                    if st.session_state["adv_pie_label_mode"] == "Percent":
                        fig_pie.update_traces(
                            texttemplate="%{percent:.0%}",
                            hovertemplate="%{label}<br>%{percent:.0%}<extra></extra>",
                        )
                    elif st.session_state["adv_pie_label_mode"] == "Value":
                        fig_pie.update_traces(
                            texttemplate="%{value:.0f}",
                            hovertemplate="%{label}<br>%{value:.0f}<extra></extra>",
                        )
                    else:
                        fig_pie.update_traces(
                            texttemplate="%{percent:.0%}<br>%{value:.0f}",
                            hovertemplate="%{label}<br>%{percent:.0%}<br>%{value:.0f}<extra></extra>",
                        )
                    fig_pie.update_traces(textfont=dict(size=12))
                    fig_pie.update_layout(
                        font=dict(size=12),
                        legend=dict(font=dict(size=12)),
                    )

                    st.plotly_chart(fig_pie, width="stretch")
        else:
            st.info("No map data available (no successful countries).")

        st.markdown("## Export")
        with st.expander("Export PDF", expanded=False):
            if st.button("Generate PDF"):
                try:
                    pdf_bytes = build_advanced_pdf(res, st.session_state, countries_df)
                    st.session_state["adv_pdf_bytes"] = pdf_bytes
                    st.success("PDF ready. Use the download button below.")
                except Exception as e:
                    st.exception(e)

            if "adv_pdf_bytes" in st.session_state:
                st.download_button(
                    "Download Advanced Report (PDF)",
                    data=st.session_state["adv_pdf_bytes"],
                    file_name="advanced_report.pdf",
                    mime="application/pdf",
                )

    with st.expander("Save / Load", expanded=False):
        save_name = st.text_input("Save name", value="advanced_1", key="adv_save_name")
        payload = dump_advanced_state(st.session_state)
        payload["name"] = save_name

        st.download_button(
            "Download advanced scenario (.json)",
            data=to_json_bytes(payload),
            file_name=f"{save_name}.json",
            mime="application/json",
        )

        uploaded = st.file_uploader(
            "Load advanced scenario (.json)",
            type=["json"],
            key="adv_uploader",
        )
        if uploaded is not None:
            try:
                loaded = from_json_bytes(uploaded.read())
                st.session_state["_adv_pending_load_payload"] = loaded
                st.session_state["adv_uploader"] = None
                st.rerun()
            except Exception as e:
                st.error(f"Failed to load file: {e}")

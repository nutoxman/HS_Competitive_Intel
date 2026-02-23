from __future__ import annotations

from datetime import date
from typing import Any

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st

from engine.core.advanced import allocate_goal, aggregate_states
from engine.core.derive_states import derive_states_from_primary
from engine.core.primary import build_primary_daily
from engine.core.series_ops import scale_series
from engine.core.solvers import solve_lsfv_fixed_sites, solve_sites_fixed_timeline
from engine.core.targets import ValidationError, derive_targets
from engine.core.run_simple import run_simple_scenario
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings
from export.advanced_pdf import build_advanced_pdf
from ui.persistence import dump_advanced_state, from_json_bytes, load_advanced_state, to_json_bytes


COUNTRY_DATA_PATH = "data/un_members_m49.csv"
DATE_DISPLAY_FORMAT = "%d-%b-%Y"
DATE_INPUT_FORMAT = "DD-MM-YYYY"


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
    if end < start:
        start, end = end, start
    return start, end


def _one_year_after(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + 1)


def _init_defaults() -> None:
    today = date.today()
    defaults = {
        "adv_goal_type": "Randomized",
        "adv_goal_n": 100,
        "adv_screen_fail_rate": 0.2,
        "adv_discontinuation_rate": 0.1,
        "adv_period_type": "Randomized",
        "adv_driver": "Fixed Timeline",
        "adv_lag_sr_days": 14,
        "adv_lag_rc_days": 60,
        "adv_uncertainty_enabled": False,
        "adv_uncertainty_lower_pct": 10.0,
        "adv_uncertainty_upper_pct": 10.0,
        "adv_global_fsfv": today,
        "adv_global_lsfv": _one_year_after(today),
        "adv_global_sites": 10,
        "adv_global_sar_pct": [20, 40, 60, 80, 100, 100],
        "adv_global_rr_pct": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "adv_selected_countries": [],
        "adv_country_config": {},
        "adv_map_metric": "Randomized total",
        "adv_map_view": "World",
        "adv_pie_enabled": False,
        "adv_pie_scope": "Region",
        "adv_pie_metric_family": "Enrollment",
        "adv_pie_state": "Randomized",
        "adv_pie_label_mode": "Both",
        "adv_pie_country": None,
        "adv_selected_country": None,
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    if st.session_state.get("adv_period_type") not in {"Screened", "Randomized"}:
        st.session_state["adv_period_type"] = "Randomized"

    st.session_state["adv_initialized"] = True


def _default_country_row(country: dict[str, Any]) -> dict[str, Any]:
    return {
        "ISO3": country["iso3"],
        "Country": country["country"],
        "Region": country.get("region", ""),
        "Subregion": country.get("subregion", ""),
        "FSFV": st.session_state["adv_global_fsfv"],
        "LSFV": st.session_state["adv_global_lsfv"],
        "Sites": st.session_state["adv_global_sites"],
        "SAR_0": st.session_state["adv_global_sar_pct"][0],
        "SAR_20": st.session_state["adv_global_sar_pct"][1],
        "SAR_40": st.session_state["adv_global_sar_pct"][2],
        "SAR_60": st.session_state["adv_global_sar_pct"][3],
        "SAR_80": st.session_state["adv_global_sar_pct"][4],
        "SAR_100": st.session_state["adv_global_sar_pct"][5],
        "RR_0": st.session_state["adv_global_rr_pct"][0],
        "RR_20": st.session_state["adv_global_rr_pct"][1],
        "RR_40": st.session_state["adv_global_rr_pct"][2],
        "RR_60": st.session_state["adv_global_rr_pct"][3],
        "RR_80": st.session_state["adv_global_rr_pct"][4],
        "RR_100": st.session_state["adv_global_rr_pct"][5],
    }


def _build_country_df(countries_df: pd.DataFrame, selected: list[str]) -> pd.DataFrame:
    config = st.session_state["adv_country_config"]

    rows = []
    for _, row in countries_df[countries_df["country"].isin(selected)].iterrows():
        iso = row["iso3"]
        if iso not in config:
            config[iso] = _default_country_row(row.to_dict())
        rows.append(config[iso])

    # Keep order consistent with selection
    order_map = {name: i for i, name in enumerate(selected)}
    rows.sort(key=lambda r: order_map.get(r["Country"], 0))

    return pd.DataFrame(rows)


def _update_config_from_df(df: pd.DataFrame) -> None:
    config = st.session_state["adv_country_config"]
    for _, row in df.iterrows():
        iso = row["ISO3"]
        config[iso] = row.to_dict()


def _validate_country_rows(df: pd.DataFrame, driver: str) -> list[str]:
    errors: list[str] = []

    required_cols = ["FSFV", "SAR_0", "SAR_20", "SAR_40", "SAR_60", "SAR_80", "SAR_100",
                     "RR_0", "RR_20", "RR_40", "RR_60", "RR_80", "RR_100"]
    if driver == "Fixed Timeline":
        required_cols.append("LSFV")
    else:
        required_cols.append("Sites")

    for _, row in df.iterrows():
        country = row["Country"]
        for col in required_cols:
            if pd.isna(row[col]):
                errors.append(f"{country}: {col} is required.")

        fsfv = row["FSFV"]
        if not isinstance(fsfv, date):
            errors.append(f"{country}: FSFV must be a date.")

        if driver == "Fixed Timeline":
            lsfv = row["LSFV"]
            if not isinstance(lsfv, date):
                errors.append(f"{country}: LSFV must be a date.")
            elif isinstance(fsfv, date) and lsfv <= fsfv:
                errors.append(f"{country}: LSFV must be after FSFV.")
        else:
            sites = row["Sites"]
            if pd.isna(sites) or int(sites) != sites or int(sites) <= 0:
                errors.append(f"{country}: Sites must be a positive integer.")

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


def _extract_country_inputs(df: pd.DataFrame, driver: str) -> dict[str, dict[str, Any]]:
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
            "lsfv": row["LSFV"] if driver == "Fixed Timeline" else None,
            "sites": int(row["Sites"]) if driver == "Fixed Sites" else None,
            "sar": sar,
            "rr": rr,
        }
    return out


def _compute_weights(country_inputs: dict[str, dict[str, Any]], driver: str, settings: GlobalSettings) -> dict[str, float]:
    weights: dict[str, float] = {}
    for iso, c in country_inputs.items():
        if driver == "Fixed Sites":
            sites = c["sites"]
            avg_sar = sum(c["sar"]) / len(c["sar"]) / 100.0
            avg_rr = sum(c["rr"]) / len(c["rr"])
            weights[iso] = float(sites) * avg_sar * avg_rr
        else:
            primary = build_primary_daily(
                fsfv=c["fsfv"],
                lsfv=c["lsfv"],
                sites=1,
                sar_pct=c["sar"],
                rr_per_site_per_month=c["rr"],
                settings=settings,
            )
            weights[iso] = sum(primary.new_primary.values())
    return weights


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
    st.caption("Advanced Mode supports a single scenario with multi-country allocation and roll-up.")

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
        st.session_state["adv_period_type"] = "Randomized"

    settings = GlobalSettings()
    countries_df = load_countries()

    with st.expander("Global Inputs", expanded=True):
        gcol1, gcol2, gcol3 = st.columns(3)
        with gcol1:
            st.selectbox(
                "Solve For",
                ["Randomized", "Completed"],
                key="adv_goal_type",
                format_func=lambda v: {"Randomized": "Total Randomized", "Completed": "Total Completed"}[v],
            )
            st.number_input("Goal N (global)", min_value=1, step=1, key="adv_goal_n")
            st.slider("Screen fail rate", 0.0, 0.99, key="adv_screen_fail_rate")
            st.slider("Discontinuation rate", 0.0, 0.99, key="adv_discontinuation_rate")

        with gcol2:
            st.selectbox(
                "Recruitment Rate type (primary)",
                ["Screened", "Randomized"],
                key="adv_period_type",
            )
            st.selectbox("Driver", ["Fixed Sites", "Fixed Timeline"], key="adv_driver")
            st.number_input(
                "Lag Screened → Randomized (days)",
                min_value=0,
                step=1,
                key="adv_lag_sr_days",
            )
            st.number_input(
                "Lag Randomized → Completed (days)",
                min_value=0,
                step=1,
                key="adv_lag_rc_days",
            )

        with gcol3:
            st.date_input("Default FSFV", key="adv_global_fsfv", format=DATE_INPUT_FORMAT)
            if st.session_state["adv_driver"] == "Fixed Timeline":
                st.date_input("Default LSFV", key="adv_global_lsfv", format=DATE_INPUT_FORMAT)
            else:
                st.number_input("Default Sites", min_value=1, step=1, key="adv_global_sites")

        st.markdown("### Global Defaults — Site Activation Rate at % Milestones from FSFV to LSFV")
        sar_df = pd.DataFrame([st.session_state["adv_global_sar_pct"]], columns=["0%", "20%", "40%", "60%", "80%", "100%"])
        sar_edit = st.data_editor(sar_df, num_rows="fixed", hide_index=True, key="adv_global_sar_editor")
        st.session_state["adv_global_sar_pct"] = [float(sar_edit.iloc[0][c]) for c in sar_edit.columns]

        rr_label_map = {
            "Screened": "screened",
            "Randomized": "randomized",
        }
        rr_label = rr_label_map.get(st.session_state["adv_period_type"], "randomized")
        st.markdown(f"### Global Defaults — # of subjects {rr_label}/site/month")
        rr_df = pd.DataFrame([st.session_state["adv_global_rr_pct"]], columns=["0%", "20%", "40%", "60%", "80%", "100%"])
        rr_edit = st.data_editor(rr_df, num_rows="fixed", hide_index=True, key="adv_global_rr_editor")
        st.session_state["adv_global_rr_pct"] = [float(rr_edit.iloc[0][c]) for c in rr_edit.columns]

        st.markdown("### Global Uncertainty")
        ucol1, ucol2, ucol3 = st.columns([1, 1, 1])
        with ucol1:
            st.checkbox("Enable uncertainty", key="adv_uncertainty_enabled")
        with ucol2:
            st.number_input("Lower % (below)", min_value=0.0, max_value=100.0, step=1.0, key="adv_uncertainty_lower_pct")
        with ucol3:
            st.number_input("Upper % (above)", min_value=0.0, max_value=100.0, step=1.0, key="adv_uncertainty_upper_pct")

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

    st.subheader("Countries")
    selected = st.multiselect(
        "Select countries (1–20)",
        options=sorted(countries_df["country"].tolist()),
        key="adv_selected_countries",
    )

    if len(selected) > 20:
        st.error("Advanced Mode supports up to 20 countries. Remove some selections to proceed.")

    country_df = _build_country_df(countries_df, selected) if selected else pd.DataFrame()

    if not country_df.empty:
        driver = st.session_state["adv_driver"]
        cols = [
            "ISO3",
            "Country",
            "Region",
            "Subregion",
            "FSFV",
            "LSFV" if driver == "Fixed Timeline" else "Sites",
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

        st.markdown("### Country Configuration")
        column_config = {
            "ISO3": st.column_config.TextColumn(disabled=True),
            "Country": st.column_config.TextColumn(disabled=True),
            "Region": st.column_config.TextColumn(disabled=True),
            "Subregion": st.column_config.TextColumn(disabled=True),
            "FSFV": st.column_config.DateColumn(format=DATE_INPUT_FORMAT),
        }
        if driver == "Fixed Timeline":
            column_config["LSFV"] = st.column_config.DateColumn(format=DATE_INPUT_FORMAT)
        else:
            column_config["Sites"] = st.column_config.NumberColumn(min_value=1, step=1)

        edited_df = st.data_editor(
            country_df,
            num_rows="fixed",
            width="stretch",
            key="adv_country_editor",
            column_config=column_config,
        )
        _update_config_from_df(edited_df)

        errors = _validate_country_rows(edited_df, driver)
    else:
        errors = []

    if selected and not country_df.empty:
        fsfvs = [row["FSFV"] for _, row in country_df.iterrows() if isinstance(row["FSFV"], date)]
        if fsfvs:
            st.info(f"Derived global FSFV (earliest): {_format_date(min(fsfvs))}")

    if errors:
        st.error("Please fix the following before running:")
        for e in errors:
            st.write(f"- {e}")

    can_run = bool(selected) and not errors and len(selected) <= 20

    if can_run and st.session_state["adv_goal_n"] < len(selected):
        st.error("Goal N must be at least the number of selected countries to allocate minimum 1 per country.")
        can_run = False

    if st.button("Run Advanced Scenario", type="primary", disabled=not can_run):
        try:
            driver = st.session_state["adv_driver"]
            country_inputs = _extract_country_inputs(edited_df, driver)

            weights = _compute_weights(country_inputs, driver, settings)
            allocation = allocate_goal(int(st.session_state["adv_goal_n"]), weights)

            results = []
            warnings = []

            for iso, c in country_inputs.items():
                allocated = allocation.allocations.get(iso, 0)
                if allocated <= 0:
                    results.append({
                        "iso3": iso,
                        "country": c["country"],
                        "region": c["region"],
                        "subregion": c["subregion"],
                        "status": "failed",
                        "warning": "Allocated target is 0.",
                        "result": None,
                        "uncertainty": None,
                        "optimistic_solve": None,
                        "pessimistic_solve": None,
                    })
                    continue

                inputs = ScenarioInputs(
                    name=c["country"],
                    goal_type=st.session_state["adv_goal_type"],
                    goal_n=int(allocated),
                    screen_fail_rate=float(st.session_state["adv_screen_fail_rate"]),
                    discontinuation_rate=float(st.session_state["adv_discontinuation_rate"]),
                    period_type=st.session_state["adv_period_type"],
                    driver=driver,
                    fsfv=c["fsfv"],
                    lsfv=c["lsfv"] if driver == "Fixed Timeline" else None,
                    sites=c["sites"] if driver == "Fixed Sites" else None,
                    lag_sr_days=int(st.session_state["adv_lag_sr_days"]),
                    lag_rc_days=int(st.session_state["adv_lag_rc_days"]),
                    sar_pct=c["sar"],
                    rr_per_site_per_month=c["rr"],
                )

                try:
                    result = run_simple_scenario(inputs, settings)
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

                    # Uncertainty bands on states (use baseline solved timeline/sites)
                    lsfv_primary = result.solve.solved_lsfv if driver == "Fixed Sites" else inputs.lsfv
                    sites_primary = result.solve.solved_sites if driver == "Fixed Timeline" else inputs.sites
                    if lsfv_primary is None or sites_primary is None:
                        raise ValidationError("Unable to compute uncertainty bands (missing LSFV or sites).")

                    lower_states, upper_states = _build_uncertainty_states(
                        inputs,
                        settings,
                        lower_pct,
                        upper_pct,
                        lsfv=lsfv_primary,
                        sites=sites_primary,
                    )

                    # Uncertainty solves
                    targets = derive_targets(
                        inputs.goal_type,
                        inputs.goal_n,
                        inputs.screen_fail_rate,
                        inputs.discontinuation_rate,
                    )
                    if driver == "Fixed Sites":
                        pessimistic_solve = solve_lsfv_fixed_sites(
                            fsfv=inputs.fsfv,
                            sites=inputs.sites or 1,
                            period_type=inputs.period_type,
                            targets=targets,
                            screen_fail_rate=inputs.screen_fail_rate,
                            discontinuation_rate=inputs.discontinuation_rate,
                            lag_sr_days=inputs.lag_sr_days,
                            lag_rc_days=inputs.lag_rc_days,
                            sar_pct=inputs.sar_pct,
                            rr_per_site_per_month=inputs.rr_per_site_per_month,
                            settings=settings,
                            throughput_multiplier=max(0.0, 1.0 - lower_pct / 100.0),
                        )
                        optimistic_solve = solve_lsfv_fixed_sites(
                            fsfv=inputs.fsfv,
                            sites=inputs.sites or 1,
                            period_type=inputs.period_type,
                            targets=targets,
                            screen_fail_rate=inputs.screen_fail_rate,
                            discontinuation_rate=inputs.discontinuation_rate,
                            lag_sr_days=inputs.lag_sr_days,
                            lag_rc_days=inputs.lag_rc_days,
                            sar_pct=inputs.sar_pct,
                            rr_per_site_per_month=inputs.rr_per_site_per_month,
                            settings=settings,
                            throughput_multiplier=1.0 + upper_pct / 100.0,
                        )
                    else:
                        pessimistic_solve = solve_sites_fixed_timeline(
                            fsfv=inputs.fsfv,
                            lsfv=inputs.lsfv or inputs.fsfv,
                            period_type=inputs.period_type,
                            targets=targets,
                            screen_fail_rate=inputs.screen_fail_rate,
                            discontinuation_rate=inputs.discontinuation_rate,
                            lag_sr_days=inputs.lag_sr_days,
                            lag_rc_days=inputs.lag_rc_days,
                            sar_pct=inputs.sar_pct,
                            rr_per_site_per_month=inputs.rr_per_site_per_month,
                            settings=settings,
                            throughput_multiplier=max(0.0, 1.0 - lower_pct / 100.0),
                        )
                        optimistic_solve = solve_sites_fixed_timeline(
                            fsfv=inputs.fsfv,
                            lsfv=inputs.lsfv or inputs.fsfv,
                            period_type=inputs.period_type,
                            targets=targets,
                            screen_fail_rate=inputs.screen_fail_rate,
                            discontinuation_rate=inputs.discontinuation_rate,
                            lag_sr_days=inputs.lag_sr_days,
                            lag_rc_days=inputs.lag_rc_days,
                            sar_pct=inputs.sar_pct,
                            rr_per_site_per_month=inputs.rr_per_site_per_month,
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
                    "status": status,
                    "warning": warning,
                    "result": result,
                    "uncertainty": uncertainty,
                    "optimistic_solve": optimistic_solve,
                    "pessimistic_solve": pessimistic_solve,
                })

            # Aggregate global
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

            # Global LSLV = latest country LSLV
            lslv_values = []
            for r in ok_results:
                lslv_values.append(r["result"].timelines.completed_lslv)
            global_lslv = max(lslv_values) if lslv_values else None

            st.session_state["adv_results"] = {
                "countries": results,
                "global_states": global_states,
                "global_uncertainty": global_uncertainty,
                "global_lslv": global_lslv,
                "allocation": allocation,
                "warnings": warnings,
            }

            st.success("Advanced scenario run complete.")
        except Exception as e:
            st.exception(e)

    # ---- Results ----
    if "adv_results" in st.session_state:
        res = st.session_state["adv_results"]
        if res.get("warnings"):
            for w in res["warnings"]:
                st.warning(w)

        st.markdown("## Country Summary")
        driver = st.session_state["adv_driver"]

        def _format_solve(solve, field: str):
            if solve is None:
                return None
            if not solve.reached:
                return "unreachable"
            val = getattr(solve, field, None)
            if isinstance(val, date):
                return _format_date(val)
            return val

        rows = []
        for r in res["countries"]:
            if r["result"]:
                out = r["result"]
                rows.append({
                    "Country": r["country"],
                    "Region": r["region"],
                    "Target (Randomized)": round(out.targets.randomized),
                    "Target (Completed)": round(out.targets.completed),
                    "Solved Sites": out.solve.solved_sites,
                    "Solved LSFV": out.solve.solved_lsfv,
                    "LSLV": out.timelines.completed_lslv,
                    "Pessimistic Solve": _format_solve(r["pessimistic_solve"], "solved_lsfv" if driver == "Fixed Sites" else "solved_sites"),
                    "Optimistic Solve": _format_solve(r["optimistic_solve"], "solved_lsfv" if driver == "Fixed Sites" else "solved_sites"),
                    "Status": r["status"],
                    "Warning": r["warning"],
                })
            else:
                rows.append({
                    "Country": r["country"],
                    "Region": r["region"],
                    "Target (Randomized)": None,
                    "Target (Completed)": None,
                    "Solved Sites": None,
                    "Solved LSFV": None,
                    "LSLV": None,
                    "Pessimistic Solve": None,
                    "Optimistic Solve": None,
                    "Status": r["status"],
                    "Warning": r["warning"],
                })

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
            selected_range = st.date_input(
                "Display date range",
                value=(domain_min, domain_max),
                key="adv_global_curve_date_range",
                format=DATE_INPUT_FORMAT,
            )
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

            # Site activation chart
            st.markdown("### Site Activation Over Time")
            global_sites_color = st.color_picker(
                "Global cumulative active sites line",
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
                monthly = df_sites.groupby("month", as_index=False)["active_sites"].mean()
                monthly["country"] = r["country"]
                monthly_rows.append(monthly)

            if monthly_rows:
                bars_df = pd.concat(monthly_rows, ignore_index=True)
                global_monthly = (
                    bars_df.groupby("month", as_index=False)["active_sites"]
                    .sum()
                    .rename(columns={"active_sites": "global_active_sites"})
                    .sort_values("month")
                )
                global_monthly["cumulative_active_sites"] = global_monthly["global_active_sites"].cumsum()

                domain_min = bars_df["month"].min()
                if res.get("global_lslv"):
                    domain_max = _coerce_to_date(res["global_lslv"] + pd.Timedelta(days=30))
                else:
                    domain_max = _coerce_to_date(bars_df["month"].max())
                domain_min = _coerce_to_date(domain_min)
                selected_site_range = st.date_input(
                    "Display site activation date range",
                    value=(domain_min, domain_max),
                    key="adv_site_activation_date_range",
                    format=DATE_INPUT_FORMAT,
                )
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
                        y=alt.Y("active_sites:Q", title="Avg Active Sites"),
                        color=alt.Color(
                            "country:N",
                            title="Country",
                            scale=alt.Scale(domain=country_domain, range=country_range),
                        ),
                        tooltip=[
                            alt.Tooltip("month:T", title="Month", format=DATE_DISPLAY_FORMAT),
                            alt.Tooltip("country:N", title="Country"),
                            alt.Tooltip("active_sites:Q", title="Avg Active Sites", format=".1f"),
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
                            "cumulative_active_sites:Q",
                            axis=alt.Axis(title="Cumulative Active Sites", orient="right"),
                        ),
                        tooltip=[
                            alt.Tooltip("month:T", title="Month", format=DATE_DISPLAY_FORMAT),
                            alt.Tooltip("cumulative_active_sites:Q", title="Cumulative Active Sites", format=".1f"),
                        ],
                    )
                )

                chart = alt.layer(bar, line).resolve_scale(y="independent").properties(height=320)
                st.altair_chart(chart, width="stretch")
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
            sel_state = st.selectbox("State", ["Screened", "Randomized", "Completed"], key="adv_country_state")
            country_map = {r["country"]: r for r in ok_results}
            country_result = country_map.get(sel_country)
            if not country_result:
                st.warning("Selected country not available in results. Showing the first available country.")
                country_result = ok_results[0]
            out = country_result["result"]

            series = {
                "Screened": out.states.screened.cumulative,
                "Randomized": out.states.randomized.cumulative,
                "Completed": out.states.completed.cumulative,
            }[sel_state]

            df = pd.DataFrame({"date": list(series.keys()), "value": list(series.values())}).sort_values("date")
            df["state"] = sel_state

            layers = []
            domain_min = _coerce_to_date(df["date"].min())
            domain_max = _coerce_to_date(out.timelines.completed_lslv + pd.Timedelta(days=30))
            selected_country_range = st.date_input(
                "Display country date range",
                value=(domain_min, domain_max),
                key="adv_country_curve_date_range",
                format=DATE_INPUT_FORMAT,
            )
            country_range_start, country_range_end = _resolve_date_range(
                selected_country_range, domain_min, domain_max
            )
            if country_result["uncertainty"]:
                lower = {
                    "Screened": country_result["uncertainty"]["lower_states"].screened.cumulative,
                    "Randomized": country_result["uncertainty"]["lower_states"].randomized.cumulative,
                    "Completed": country_result["uncertainty"]["lower_states"].completed.cumulative,
                }[sel_state]
                upper = {
                    "Screened": country_result["uncertainty"]["upper_states"].screened.cumulative,
                    "Randomized": country_result["uncertainty"]["upper_states"].randomized.cumulative,
                    "Completed": country_result["uncertainty"]["upper_states"].completed.cumulative,
                }[sel_state]
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
                            scale=alt.Scale(domain=[country_range_start, country_range_end]),
                            axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                        ),
                        y="lower:Q",
                        y2="upper:Q",
                    )
                )

            layers.append(
                alt.Chart(df)
                .mark_line()
                .encode(
                    x=alt.X(
                        "date:T",
                        scale=alt.Scale(domain=[country_range_start, country_range_end]),
                        axis=alt.Axis(format=DATE_DISPLAY_FORMAT),
                    ),
                    y="value:Q",
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format=DATE_DISPLAY_FORMAT),
                        alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
                    ],
                )
            )
            st.altair_chart(alt.layer(*layers).properties(height=320), width="stretch")
        else:
            st.info("No successful countries to display.")

        # Map + pie
        st.markdown("## Map View")
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
        view = st.selectbox(
            "Map view",
            ["World"] + sorted(countries_df["region"].dropna().unique().tolist()),
            key="adv_map_view",
        )

        # Build metric df
        map_rows = []
        global_totals = {"screened": 0.0, "randomized": 0.0, "completed": 0.0}
        for r in res["countries"]:
            if r["result"]:
                out = r["result"]
                global_totals["screened"] += max(out.states.screened.cumulative.values()) if out.states.screened.cumulative else 0.0
                global_totals["randomized"] += max(out.states.randomized.cumulative.values()) if out.states.randomized.cumulative else 0.0
                global_totals["completed"] += max(out.states.completed.cumulative.values()) if out.states.completed.cumulative else 0.0

        for r in res["countries"]:
            if not r["result"]:
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
                "sites": out.solve.solved_sites or 0,
            })

        map_df = pd.DataFrame(map_rows)
        if view != "World":
            map_df = map_df[map_df["region"] == view]

        if not map_df.empty:
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

            col_map, col_pie = st.columns([2, 1])
            with col_map:
                fig = px.choropleth(
                    map_df,
                    locations="iso3",
                    color="metric",
                    hover_name="country",
                    color_continuous_scale="YlOrRd",
                )
                if view != "World":
                    fig.update_geos(fitbounds="locations", visible=False)
                st.plotly_chart(fig, width="stretch")

            with col_pie:
                st.checkbox("Show pie", key="adv_pie_enabled")
                if st.session_state["adv_pie_enabled"]:
                    pie_scope = st.selectbox("Pie scope", ["Region", "Country"], key="adv_pie_scope")
                    st.selectbox("Metric family", ["Enrollment", "Sites"], key="adv_pie_metric_family")
                    st.selectbox("State", ["Screened", "Randomized", "Completed"], key="adv_pie_state")
                    st.selectbox("Label mode", ["Percent", "Value", "Both"], key="adv_pie_label_mode")

                    pie_df = map_df.copy()
                    names_col = "country"
                    if pie_scope == "Country":
                        sel = st.selectbox("Country", pie_df["country"].tolist(), key="adv_pie_country")
                        pie_df = pie_df[pie_df["country"] == sel]
                    elif view == "World":
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

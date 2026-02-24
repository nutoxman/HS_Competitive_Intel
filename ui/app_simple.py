from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.core.run_simple import run_simple_scenario
from engine.core.targets import ValidationError
from engine.models.settings import GlobalSettings
from ui.components import render_scenario_inputs, render_results


LEGACY_FIXED_SITES_MODE = "Simple Scenario: Simple Scenario: # of Sites Drives Timeline"
FIXED_SITES_MODE = "Simple Scenario: # of Sites Drives Timeline"
FIXED_TIMELINE_MODE = "Simple Scenario: Timeline Drives # of Sites"
DATE_AXIS_FORMAT = "%d-%b-%Y"
DATE_INPUT_FORMAT = "DD-MM-YYYY"


def _normalize_simple_mode(mode: str | None) -> str | None:
    if mode == LEGACY_FIXED_SITES_MODE:
        return FIXED_SITES_MODE
    return mode


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


def render():
    selected_mode = _normalize_simple_mode(st.session_state.get("simple_mode_scenario"))
    if selected_mode != st.session_state.get("simple_mode_scenario"):
        st.session_state["simple_mode_scenario"] = selected_mode

    if selected_mode == FIXED_TIMELINE_MODE:
        page_title = "Simple Mode: Timeline Drives # of Sites"
    else:
        page_title = "Simple Mode: # of Sites Drives Timeline"
    st.markdown(
        f"<p style='font-size:12pt;font-weight:600;margin:0 0 1rem 0;'>{page_title}</p>",
        unsafe_allow_html=True,
    )

    settings = GlobalSettings()
    copy_controls_visible = any(f"S{i}_result" in st.session_state for i in range(1, 6))

    from ui.persistence import load_into_session_state, from_json_bytes

    # Apply pending load BEFORE widgets instantiate
    if "_pending_load_payload" in st.session_state:
        try:
            load_into_session_state(st.session_state["_pending_load_payload"], st.session_state)
            st.session_state.pop("_pending_load_payload", None)
            st.success("Loaded comparison (results cleared; re-run scenarios).")
        except Exception as e:
            st.session_state.pop("_pending_load_payload", None)
            st.error(f"Failed to apply loaded file: {e}")

    tabs = st.tabs(["S1", "S2", "S3", "S4", "S5", "Comparison"])

    for i, tab in enumerate(tabs[:5], start=1):
        with tab:
            scenario_key = f"S{i}"
            # Scenario copy controls (shown only after at least one scenario has been run)
            if copy_controls_visible:
                copy_col, copy_btn_col = st.columns([5, 1])
                with copy_col:
                    copy_from = st.selectbox(
                        "Copy inputs from:",
                        ["(none)", "S1", "S2", "S3", "S4", "S5"],
                        index=0,
                        key=f"{scenario_key}_copy_from",
                    )
                with copy_btn_col:
                    copy_clicked = st.button("Copy", key=f"{scenario_key}_copy_btn", use_container_width=True)

                if copy_clicked:
                    if copy_from != "(none)" and copy_from != scenario_key:
                        # Copy known session_state keys
                        keys_to_copy = [
                            "goal_type",
                            "goal_n",
                            "screen_fail_rate",
                            "discontinuation_rate",
                            "period_type",
                            "simple_scenario",
                            "driver",
                            "fsfv",
                            "lsfv",
                            "sites",
                            "lag_sr_days",
                            "lag_rc_days",
                            "sar_pct",
                            "rr_pct",
                            "uncertainty_enabled",
                            "uncertainty_lower_pct",
                            "uncertainty_upper_pct",
                        ]
                        for k in keys_to_copy:
                            src = f"{copy_from}_{k}"
                            dst = f"{scenario_key}_{k}"
                            if src in st.session_state:
                                st.session_state[dst] = st.session_state[src]

                        # Clear results (force rerun)
                        st.session_state.pop(f"{scenario_key}_result", None)

                        # Also reset editor widgets so Streamlit rebinds cleanly
                        st.session_state.pop(f"{scenario_key}_sar_editor", None)
                        st.session_state.pop(f"{scenario_key}_rr_editor", None)

                        st.success(f"Copied inputs from {copy_from} → {scenario_key}")
                    elif copy_from == scenario_key:
                        st.info("Pick a different scenario to copy from.")
                    else:
                        st.info("Select a scenario to copy from.")

            inputs = render_scenario_inputs(scenario_key)

            if st.button(f"Run {scenario_key}", key=f"run_{scenario_key}", type="primary"):
                try:
                    out = run_simple_scenario(inputs, settings)
                    st.session_state[f"{scenario_key}_result"] = out
                    st.rerun()
                except ValidationError as e:
                    st.error(str(e))
                except Exception as e:
                    st.exception(e)

            if f"{scenario_key}_result" in st.session_state:
                render_results(st.session_state[f"{scenario_key}_result"], scenario_key=scenario_key)

    with tabs[5]:
        st.header("Comparison View")

        from ui.persistence import dump_session_state, to_json_bytes, from_json_bytes

        # ---- Save / Load ----
        st.subheader("Save / Load Comparison")

        save_name = st.text_input("Save name", value="comparison_1", key="save_name")
        payload = dump_session_state(settings, st.session_state)
        payload["name"] = save_name

        st.download_button(
            "Download saved comparison (.json)",
            data=to_json_bytes(payload),
            file_name=f"{save_name}.json",
            mime="application/json",
        )

        uploaded = st.file_uploader(
            "Load saved comparison (.json)",
            type=["json"],
            key="comparison_uploader",
        )
        if uploaded is not None:
            try:
                loaded = from_json_bytes(uploaded.read())
                st.session_state["_pending_load_payload"] = loaded
                st.session_state["comparison_uploader"] = None
                st.rerun()
            except Exception as e:
                st.error(f"Failed to load file: {e}")

        st.divider()

        # ---- Comparison Chart ----
        compare_state = st.selectbox(
            "Compare state",
            ["Screened", "Randomized", "Completed"],
            index=1,
            key="compare_state",
        )

        included = []
        for i in range(1, 6):
            sk = f"S{i}"
            if st.session_state.get(f"{sk}_include", False) and f"{sk}_result" in st.session_state:
                included.append(sk)

        if not included:
            st.info("No included scenarios with results yet. Run at least one scenario and enable 'Include in comparison'.")
        else:
            import pandas as pd
            import altair as alt

            dfs = []
            for sk in included:
                out = st.session_state[f"{sk}_result"]

                if compare_state == "Screened":
                    series = out.states.screened.cumulative
                elif compare_state == "Randomized":
                    series = out.states.randomized.cumulative
                else:
                    series = out.states.completed.cumulative

                df = pd.DataFrame(
                    {"date": list(series.keys()), sk: list(series.values())}
                ).sort_values("date")

                dfs.append(df)

            merged = dfs[0]
            for df in dfs[1:]:
                merged = merged.merge(df, on="date", how="outer")

            merged = merged.sort_values("date")
            merged = merged.fillna(method="ffill").fillna(0.0)

            st.subheader(f"Cumulative {compare_state} over time")

            long_df = merged.melt(id_vars=["date"], value_vars=included, var_name="scenario", value_name="value")

            # Compute per-scenario bands
            lower_vals = []
            upper_vals = []
            enabled_vals = []
            for _, row in long_df.iterrows():
                sk = row["scenario"]
                enabled = st.session_state.get(f"{sk}_uncertainty_enabled", False)
                lower_pct = float(st.session_state.get(f"{sk}_uncertainty_lower_pct", 10.0))
                upper_pct = float(st.session_state.get(f"{sk}_uncertainty_upper_pct", 10.0))
                lower_vals.append(max(0.0, row["value"] * (1.0 - lower_pct / 100.0)))
                upper_vals.append(row["value"] * (1.0 + upper_pct / 100.0))
                enabled_vals.append(enabled)

            long_df["lower"] = lower_vals
            long_df["upper"] = upper_vals
            long_df["uncertainty_enabled"] = enabled_vals

            domain_min = _coerce_to_date(long_df["date"].min())
            latest_lslv = max(
                st.session_state[f"{sk}_result"].timelines.completed_lslv
                for sk in included
            )
            domain_max = _coerce_to_date(latest_lslv + timedelta(days=30))
            compare_range_key = "compare_date_range"
            selected_range = st.session_state.get(compare_range_key, (domain_min, domain_max))
            range_start, range_end = _resolve_date_range(selected_range, domain_min, domain_max)

            base = alt.Chart(long_df).encode(
                x=alt.X(
                    "date:T",
                    title="Date",
                    scale=alt.Scale(domain=[range_start, range_end]),
                    axis=alt.Axis(format=DATE_AXIS_FORMAT),
                ),
                color=alt.Color("scenario:N", title="Scenario"),
            )

            layers = []
            if long_df["uncertainty_enabled"].any():
                layers.append(
                    base.transform_filter(alt.datum.uncertainty_enabled == True)
                    .mark_area(opacity=0.18)
                    .encode(
                        y=alt.Y("lower:Q", title="Cumulative"),
                        y2="upper:Q",
                    )
                )

            layers.append(
                base.mark_line().encode(
                    y=alt.Y("value:Q", title="Cumulative"),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format=DATE_AXIS_FORMAT),
                        alt.Tooltip("scenario:N", title="Scenario"),
                        alt.Tooltip("value:Q", title="Cumulative", format=".1f"),
                    ],
                )
            )

            st.altair_chart(alt.layer(*layers).properties(height=320), width="stretch")
            st.slider(
                "X-axis date range",
                min_value=domain_min,
                max_value=domain_max,
                value=(range_start, range_end),
                key=compare_range_key,
            )


if __name__ == "__main__":
    render()

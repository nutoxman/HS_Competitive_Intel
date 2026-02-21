from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.core.run_simple import run_simple_scenario
from engine.core.targets import ValidationError
from engine.models.settings import GlobalSettings
from ui.components import render_scenario_inputs, render_results




def render():
    st.title("Recruitment Scenario Planner — Simple Mode")

    settings = GlobalSettings()

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
            # Scenario copy controls
            copy_from = st.selectbox(
                "Copy inputs from",
                ["(none)", "S1", "S2", "S3", "S4", "S5"],
                index=0,
                key=f"{scenario_key}_copy_from",
            )
            if st.button("Copy", key=f"{scenario_key}_copy_btn"):
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

            base = alt.Chart(long_df).encode(
                x=alt.X("date:T", title="Date"),
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
                )
            )

            st.altair_chart(alt.layer(*layers).properties(height=320), use_container_width=True)


if __name__ == "__main__":
    render()

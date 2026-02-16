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


st.set_page_config(page_title="Recruitment Scenario Planner", layout="wide")
st.title("Recruitment Scenario Planner — Simple Mode")

settings = GlobalSettings()

tabs = st.tabs(["S1", "S2", "S3", "S4", "S5", "Comparison"])

for i, tab in enumerate(tabs[:5], start=1):
    with tab:
        scenario_key = f"S{i}"
        inputs = render_scenario_inputs(scenario_key)

        if st.button(f"Run {scenario_key}", key=f"run_{scenario_key}", type="primary"):
            try:
                out = run_simple_scenario(inputs, settings)
                st.session_state[f"{scenario_key}_result"] = out
            except ValidationError as e:
                st.error(str(e))
            except Exception as e:
                st.exception(e)

        if f"{scenario_key}_result" in st.session_state:
            render_results(st.session_state[f"{scenario_key}_result"], scenario_key=scenario_key)

with tabs[5]:
    st.header("Comparison View")

    compare_state = st.selectbox(
        "Compare state",
        ["Screened", "Randomized", "Completed"],
        index=1,
        key="compare_state",
    )

    included = []
    for i in range(1, 6):
        k = f"S{i}"
        if st.session_state.get(f"{k}_include", False) and f"{k}_result" in st.session_state:
            included.append(k)

    if not included:
        st.info("No included scenarios with results yet. Run at least one scenario and enable 'Include in comparison'.")
    else:
        # Build merged dataframe of cumulative curves
        import pandas as pd

        dfs = []
        for k in included:
            out = st.session_state[f"{k}_result"]
            if compare_state == "Screened":
                series = out.states.screened.cumulative
            elif compare_state == "Randomized":
                series = out.states.randomized.cumulative
            else:
                series = out.states.completed.cumulative

            df = pd.DataFrame({"date": list(series.keys()), k: list(series.values())}).sort_values("date")
            dfs.append(df)

        # Outer merge on date, then forward fill within each scenario
        merged = dfs[0]
        for df in dfs[1:]:
            merged = merged.merge(df, on="date", how="outer")

        merged = merged.sort_values("date")
        merged = merged.fillna(method="ffill").fillna(0.0)

        st.subheader(f"Cumulative {compare_state} over time")
        st.line_chart(merged.set_index("date")[included])

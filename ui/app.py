from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure repo root on path so `engine` imports work when running via Streamlit
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.core.run_simple import run_simple_scenario
from engine.core.targets import ValidationError
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


st.set_page_config(page_title="Recruitment Scenario Planner", layout="wide")
st.title("Recruitment Scenario Planner — Simple Mode (S1)")

settings = GlobalSettings()

with st.sidebar:
    st.header("Global Settings")
    days_per_month = st.number_input("Days per month", min_value=1.0, value=float(settings.days_per_month))
    week_ending_day = st.selectbox(
        "Week ending day",
        options=[0, 1, 2, 3, 4, 5, 6],
        format_func=lambda x: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][x],
        index=int(settings.week_ending_day),
    )
    max_sites = st.number_input("Max sites guardrail", min_value=1, value=int(settings.max_sites))
    max_duration_days = st.number_input("Max duration guardrail (days)", min_value=1, value=int(settings.max_duration_days))

settings = GlobalSettings(
    days_per_month=float(days_per_month),
    week_ending_day=int(week_ending_day),
    max_sites=int(max_sites),
    max_duration_days=int(max_duration_days),
)

st.subheader("Scenario S1 Inputs")

col1, col2, col3 = st.columns(3)

with col1:
    goal_type = st.selectbox("Goal Type", ["Randomized", "Completed"], index=0)
    goal_n = st.number_input("Goal N", min_value=1, value=100, step=1)
    screen_fail_rate = st.slider("Screen fail rate", min_value=0.0, max_value=0.99, value=0.2, step=0.01)
    discontinuation_rate = st.slider("Discontinuation rate", min_value=0.0, max_value=0.99, value=0.1, step=0.01)

with col2:
    period_type = st.selectbox("Recruitment period type (primary)", ["Screened", "Randomized", "Completed"], index=1)
    driver = st.selectbox("Driver", ["Fixed Sites", "Fixed Timeline"], index=1)
    fsfv = st.date_input("FSFV (inclusive)", value=date(2026, 1, 1))

    if driver == "Fixed Timeline":
        lsfv = st.date_input("LSFV (exclusive)", value=date(2026, 6, 1))
        sites = None
    else:
        lsfv = None
        sites = st.number_input("Sites", min_value=1, value=50, step=1)

with col3:
    lag_sr_days = st.number_input("Lag Screened → Randomized (days)", min_value=0, value=14, step=1)
    lag_rc_days = st.number_input("Lag Randomized → Completed (days)", min_value=0, value=30, step=1)

st.markdown("### SAR ramp (percent of sites active)")
sar_df = pd.DataFrame({"0%": [0], "20%": [20], "40%": [40], "60%": [60], "80%": [80], "100%": [100]})
sar_edit = st.data_editor(sar_df, num_rows="fixed", hide_index=True)
sar_pct = [float(sar_edit.iloc[0][c]) for c in sar_edit.columns]

st.markdown("### RR ramp (subjects per site per month)")
rr_df = pd.DataFrame({"0%": [0.0], "20%": [0.5], "40%": [1.0], "60%": [1.0], "80%": [1.0], "100%": [1.0]})
rr_edit = st.data_editor(rr_df, num_rows="fixed", hide_index=True)
rr_per_site_per_month = [float(rr_edit.iloc[0][c]) for c in rr_edit.columns]

run = st.button("Run Scenario S1", type="primary")

if run:
    try:
        inputs = ScenarioInputs(
            name="S1",
            goal_type=goal_type,
            goal_n=int(goal_n),
            screen_fail_rate=float(screen_fail_rate),
            discontinuation_rate=float(discontinuation_rate),
            period_type=period_type,  # type: ignore
            driver=driver,  # type: ignore
            fsfv=fsfv,
            lsfv=lsfv,
            sites=int(sites) if sites is not None else None,
            lag_sr_days=int(lag_sr_days),
            lag_rc_days=int(lag_rc_days),
            sar_pct=sar_pct,
            rr_per_site_per_month=rr_per_site_per_month,
        )

        out = run_simple_scenario(inputs, settings)

        st.success("Run complete.")

        # --- Summary ---
        st.markdown("## Summary")

        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("Target Screened", round(out.targets.screened))
            st.metric("Target Randomized", round(out.targets.randomized))
            st.metric("Target Completed", round(out.targets.completed))
        with s2:
            if inputs.driver == "Fixed Timeline":
                st.metric("Solved Sites", out.solve.solved_sites)
            else:
                st.metric("Solved LSFV", out.solve.solved_lsfv.isoformat())
        with s3:
            st.write("**Derived timelines**")
            st.write(f"Screened: {out.timelines.screened_fsfv} → {out.timelines.screened_lsfv}")
            st.write(f"Randomized: {out.timelines.randomized_fsfv} → {out.timelines.randomized_lsfv}")
            st.write(f"Completed: {out.timelines.completed_fsfv} → {out.timelines.completed_lslv}")

        # --- Chart data ---
        def to_df(series_dict: dict) -> pd.DataFrame:
            return pd.DataFrame({"date": list(series_dict.keys()), "value": list(series_dict.values())}).sort_values("date")

        df_scr = to_df(out.states.screened.cumulative).rename(columns={"value": "Screened"})
        df_rand = to_df(out.states.randomized.cumulative).rename(columns={"value": "Randomized"})
        df_comp = to_df(out.states.completed.cumulative).rename(columns={"value": "Completed"})

        df = df_scr.merge(df_rand, on="date", how="outer").merge(df_comp, on="date", how="outer").fillna(method="ffill").fillna(0.0)

        st.markdown("## Cumulative recruitment over time")
        st.line_chart(df.set_index("date")[["Screened", "Randomized", "Completed"]])

        # --- Bucket summary (default month, randomized) ---
        st.markdown("### Bucket summary (Monthly, Randomized)")
        bucket_rows = out.buckets["month"]["Randomized"]
        bucket_df = pd.DataFrame(bucket_rows)
        st.dataframe(bucket_df, use_container_width=True)

        # --- Milestones tables ---
        st.markdown("## Incremental (5%) milestones over time")
        sel_state = st.selectbox("State", ["Screened", "Randomized", "Completed"], index=1)
        st.dataframe(pd.DataFrame(out.milestones_time[sel_state]), use_container_width=True)

        st.markdown("## Target milestones (5% of target)")
        st.dataframe(pd.DataFrame(out.milestones_target[sel_state]), use_container_width=True)

    except ValidationError as e:
        st.error(str(e))
    except Exception as e:
        st.exception(e)

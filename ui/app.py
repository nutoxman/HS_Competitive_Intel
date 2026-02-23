from __future__ import annotations

import copy
import sys
from pathlib import Path
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

st.set_page_config(page_title="Recruitment Scenario Planner", layout="wide")

st.markdown(
    """
<style>
  html,
  body,
  div[data-testid="stAppViewContainer"],
  section[data-testid="stSidebar"] {
    font-size: 10pt !important;
  }
  div[data-testid="stDataFrame"] th,
  div[data-testid="stDataFrame"] td,
  div[data-testid="stDataEditor"] th,
  div[data-testid="stDataEditor"] td,
  div[data-testid="stDataEditor"] input,
  div[data-testid="stDataEditor"] textarea {
    text-align: center !important;
  }
  div[data-testid="stDataFrame"] table,
  div[data-testid="stDataEditor"] table {
    margin-left: auto;
    margin-right: auto;
  }
</style>
""",
    unsafe_allow_html=True,
)

st.sidebar.title("Mode")
mode = st.sidebar.radio(
    "Select one",
    [
        "Simple Scenario: Simple Scenario: # of Sites Drives Timeline",
        "Simple Scenario: Timeline Drives # of Sites",
        "Advanced",
    ],
    index=0,
    key="app_mode",
)

SIMPLE_MODES = {
    "Simple Scenario: Simple Scenario: # of Sites Drives Timeline",
    "Simple Scenario: Timeline Drives # of Sites",
}
SIMPLE_SHARED_KEYS = {"save_name", "compare_state"}


def _capture_simple_state(session_state: dict) -> dict:
    snapshot: dict = {}
    for key, value in session_state.items():
        if key.startswith(("S1_", "S2_", "S3_", "S4_", "S5_")) or key in SIMPLE_SHARED_KEYS:
            snapshot[key] = copy.deepcopy(value)
    return snapshot


def _restore_simple_state(session_state: dict, snapshot: dict) -> None:
    for key, value in snapshot.items():
        if key not in session_state:
            session_state[key] = copy.deepcopy(value)


previous_mode = st.session_state.get("_last_app_mode")
if previous_mode in SIMPLE_MODES and mode == "Advanced":
    st.session_state["_simple_state_snapshot"] = _capture_simple_state(st.session_state)
elif previous_mode == "Advanced" and mode in SIMPLE_MODES:
    _restore_simple_state(st.session_state, st.session_state.get("_simple_state_snapshot", {}))

st.session_state["_last_app_mode"] = mode

if mode == "Advanced":
    from ui.app_advanced import render as render_advanced

    render_advanced()
else:
    from ui.app_simple import render as render_simple

    st.session_state["simple_mode_scenario"] = mode
    render_simple()

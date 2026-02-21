from __future__ import annotations

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
    "Select mode",
    [
        "Simple Scenario: Simple Scenario: # of Sites Drives Timeline",
        "Simple Scenario: Timeline Drives # of Sites",
        "Advanced",
    ],
    index=0,
    key="app_mode",
)

if mode == "Advanced":
    from ui.app_advanced import render as render_advanced

    render_advanced()
else:
    from ui.app_simple import render as render_simple

    st.session_state["simple_mode_scenario"] = mode
    render_simple()

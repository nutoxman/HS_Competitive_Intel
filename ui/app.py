from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

st.set_page_config(page_title="Recruitment Scenario Planner", layout="wide")

st.sidebar.title("Mode")
mode = st.sidebar.radio(
    "Select mode",
    ["Simple", "Advanced"],
    index=0,
    key="app_mode",
)

if mode == "Simple":
    from ui.app_simple import render as render_simple

    render_simple()
else:
    from ui.app_advanced import render as render_advanced

    render_advanced()

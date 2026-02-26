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

LEGACY_FIXED_SITES_MODE = "Simple Scenario: Simple Scenario: # of Sites Drives Timeline"
FIXED_SITES_MODE = "Simple Scenario: # of Sites Drives Timeline"
FIXED_TIMELINE_MODE = "Simple Scenario: Timeline Drives # of Sites"
ADVANCED_MODE = "Advanced"
MODE_ALIASES = {
    LEGACY_FIXED_SITES_MODE: FIXED_SITES_MODE,
}

SIMPLE_MODES = {
    FIXED_SITES_MODE,
    FIXED_TIMELINE_MODE,
}
SIMPLE_SHARED_KEYS = {"save_name", "compare_state", "compare_date_range"}
SIMPLE_MODE_SNAPSHOTS_KEY = "_simple_mode_snapshots"
TRANSIENT_WIDGET_KEY_SUFFIXES = ("_btn", "_editor", "_uploader")
RERUN_EPHEMERAL_KEY_SUFFIXES = ("_btn", "_uploader")


def _normalize_mode_label(mode: str | None) -> str | None:
    if mode is None:
        return None
    return MODE_ALIASES.get(mode, mode)


def _is_transient_widget_key(key: str) -> bool:
    return key.endswith(TRANSIENT_WIDGET_KEY_SUFFIXES)


def _purge_transient_widget_keys(session_state: dict) -> None:
    for key in list(session_state.keys()):
        # Keep editor widget state during normal reruns so latest table edits
        # are not discarded before a Run click is processed.
        if key.endswith(RERUN_EPHEMERAL_KEY_SUFFIXES):
            session_state.pop(key, None)

    simple_snapshots = session_state.get(SIMPLE_MODE_SNAPSHOTS_KEY, {})
    if isinstance(simple_snapshots, dict):
        for snapshot in simple_snapshots.values():
            if isinstance(snapshot, dict):
                for key in list(snapshot.keys()):
                    if _is_transient_widget_key(key):
                        snapshot.pop(key, None)

    advanced_snapshot = session_state.get("_advanced_state_snapshot")
    if isinstance(advanced_snapshot, dict):
        for key in list(advanced_snapshot.keys()):
            if _is_transient_widget_key(key):
                advanced_snapshot.pop(key, None)


def _capture_simple_state(session_state: dict) -> dict:
    snapshot: dict = {}
    for key, value in session_state.items():
        if _is_transient_widget_key(key):
            continue
        if key.startswith(("S1_", "S2_", "S3_", "S4_", "S5_")) or key in SIMPLE_SHARED_KEYS:
            snapshot[key] = copy.deepcopy(value)
    return snapshot


def _capture_advanced_state(session_state: dict) -> dict:
    snapshot: dict = {}
    for key, value in session_state.items():
        if _is_transient_widget_key(key):
            continue
        if key.startswith("adv_") or key in {"_adv_pending_load_payload"}:
            snapshot[key] = copy.deepcopy(value)
    return snapshot


def _clear_simple_state(session_state: dict) -> None:
    for key in list(session_state.keys()):
        if key.startswith(("S1_", "S2_", "S3_", "S4_", "S5_")) or key in SIMPLE_SHARED_KEYS:
            session_state.pop(key, None)


def _restore_state(session_state: dict, snapshot: dict) -> None:
    for key, value in snapshot.items():
        if _is_transient_widget_key(key):
            continue
        session_state[key] = copy.deepcopy(value)


_purge_transient_widget_keys(st.session_state)

if "app_mode" in st.session_state:
    st.session_state["app_mode"] = _normalize_mode_label(st.session_state.get("app_mode"))
if "_last_app_mode" in st.session_state:
    st.session_state["_last_app_mode"] = _normalize_mode_label(st.session_state.get("_last_app_mode"))
if "simple_mode_scenario" in st.session_state:
    st.session_state["simple_mode_scenario"] = _normalize_mode_label(st.session_state.get("simple_mode_scenario"))

st.sidebar.title("Mode")
mode = st.sidebar.radio(
    "Select one",
    [
        FIXED_SITES_MODE,
        FIXED_TIMELINE_MODE,
        ADVANCED_MODE,
    ],
    index=0,
    key="app_mode",
)
mode = _normalize_mode_label(mode)
if st.session_state.get("app_mode") != mode:
    st.session_state["app_mode"] = mode

previous_mode = _normalize_mode_label(st.session_state.get("_last_app_mode"))
mode_changed = previous_mode is not None and previous_mode != mode
simple_snapshots = st.session_state.setdefault(SIMPLE_MODE_SNAPSHOTS_KEY, {})
if not isinstance(simple_snapshots, dict):
    simple_snapshots = {}
    st.session_state[SIMPLE_MODE_SNAPSHOTS_KEY] = simple_snapshots
if LEGACY_FIXED_SITES_MODE in simple_snapshots and FIXED_SITES_MODE not in simple_snapshots:
    simple_snapshots[FIXED_SITES_MODE] = simple_snapshots.pop(LEGACY_FIXED_SITES_MODE)

if mode_changed:
    if previous_mode in SIMPLE_MODES:
        simple_snapshots[previous_mode] = _capture_simple_state(st.session_state)
    elif previous_mode == ADVANCED_MODE:
        st.session_state["_advanced_state_snapshot"] = _capture_advanced_state(st.session_state)

    if mode in SIMPLE_MODES:
        _clear_simple_state(st.session_state)
        _restore_state(st.session_state, simple_snapshots.get(mode, {}))
    elif mode == ADVANCED_MODE:
        _restore_state(st.session_state, st.session_state.get("_advanced_state_snapshot", {}))

st.session_state["_last_app_mode"] = mode

if mode == ADVANCED_MODE:
    from ui.app_advanced import render as render_advanced

    render_advanced()
else:
    from ui.app_simple import render as render_simple

    st.session_state["simple_mode_scenario"] = mode
    render_simple()

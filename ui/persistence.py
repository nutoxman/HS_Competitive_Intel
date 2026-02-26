from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from typing import Any

from engine.models.settings import GlobalSettings

SCHEMA_VERSION = 1


def _date_to_str(d: Any) -> Any:
    if isinstance(d, date):
        return d.isoformat()
    return d


def _str_to_date(s: Any) -> Any:
    if isinstance(s, str) and len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return date.fromisoformat(s)
        except Exception:
            return s
    return s


def _convert_dates(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _convert_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_dates(v) for v in obj]
    return _date_to_str(obj)


def _restore_dates(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _restore_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_restore_dates(v) for v in obj]
    return _str_to_date(obj)


def dump_session_state(settings: GlobalSettings, session_state: dict) -> dict:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "settings": asdict(settings),
        "scenarios": {},
    }

    for i in range(1, 6):
        sk = f"S{i}"
        scenario = {}
        keys = [
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
            "include",
            "uncertainty_enabled",
            "uncertainty_lower_pct",
            "uncertainty_upper_pct",
        ]
        for k in keys:
            ss_key = f"{sk}_{k}"
            if ss_key in session_state:
                scenario[k] = _date_to_str(session_state[ss_key])
        payload["scenarios"][sk] = scenario

    return payload


def load_into_session_state(payload: dict, session_state: dict) -> None:
    scenarios = payload.get("scenarios", {})
    for sk, scenario in scenarios.items():
        for k, v in scenario.items():
            parsed = _str_to_date(v)
            if k == "period_type" and parsed == "Completed":
                parsed = "Randomized"
            session_state[f"{sk}_{k}"] = parsed

        # reset editor widgets so Streamlit rebinds
        session_state.pop(f"{sk}_sar_editor", None)
        session_state.pop(f"{sk}_rr_editor", None)

        # clear results (re-run required)
        session_state.pop(f"{sk}_result", None)


def to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def from_json_bytes(b: bytes) -> dict:
    return json.loads(b.decode("utf-8"))


ADV_SCHEMA_VERSION = 1


def dump_advanced_state(session_state: dict) -> dict:
    keys = [
        "adv_screen_fail_rate",
        "adv_discontinuation_rate",
        "adv_period_type",
        "_adv_period_picked",
        "adv_driver",
        "adv_lag_sr_days",
        "adv_lag_rc_days",
        "adv_uncertainty_enabled",
        "adv_uncertainty_lower_pct",
        "adv_uncertainty_upper_pct",
        "adv_global_fsfv",
        "adv_global_lsfv",
        "adv_global_sites",
        "adv_global_sar_pct",
        "adv_global_rr_pct",
        "adv_selected_countries",
        "adv_country_config",
        "adv_map_metric",
        "adv_map_view",
        "adv_map_color_scheme",
        "adv_pie_enabled",
        "adv_pie_scope",
        "adv_pie_metric_family",
        "adv_pie_state",
        "adv_pie_label_mode",
        "adv_pie_country",
        "adv_selected_country",
    ]

    payload: dict[str, Any] = {
        "schema_version": ADV_SCHEMA_VERSION,
        "advanced": {},
    }

    for k in keys:
        if k in session_state:
            payload["advanced"][k] = _convert_dates(session_state[k])

    return payload


def load_advanced_state(payload: dict, session_state: dict) -> None:
    adv = payload.get("advanced", {})
    for k, v in adv.items():
        parsed = _restore_dates(v)
        if k == "adv_period_type" and parsed == "Completed":
            parsed = "Randomized"
        if k == "adv_period_type":
            session_state["_adv_period_picked"] = parsed in {"Screened", "Randomized"}
        session_state[k] = parsed

    period = session_state.get("adv_period_type")
    if session_state.get("_adv_period_picked", False) and period in {"Screened", "Randomized"}:
        session_state["adv_period_type_picker"] = period
    else:
        session_state["adv_period_type_picker"] = "(select)"

    # Clear results and editor state
    session_state.pop("adv_results", None)
    session_state.pop("adv_country_editor", None)
    session_state.pop("adv_pdf_bytes", None)
    session_state.pop("_adv_last_run_signature", None)
    session_state.pop("_adv_results_stale", None)
    session_state["adv_initialized"] = True

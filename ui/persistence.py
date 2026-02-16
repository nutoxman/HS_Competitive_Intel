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
            session_state[f"{sk}_{k}"] = _str_to_date(v)

        # reset editor widgets so Streamlit rebinds
        session_state.pop(f"{sk}_sar_editor", None)
        session_state.pop(f"{sk}_rr_editor", None)

        # clear results (re-run required)
        session_state.pop(f"{sk}_result", None)


def to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def from_json_bytes(b: bytes) -> dict:
    return json.loads(b.decode("utf-8"))

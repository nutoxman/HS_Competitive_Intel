from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "saved_scenarios.db"
VALID_MODES = {"simple", "advanced", "simple_scenario"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is None:
        return DEFAULT_DB_PATH
    return Path(db_path)


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"Unsupported scenario mode: {mode!r}")


def _validate_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise ValueError("Scenario name is required.")
    return normalized


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(mode, name)
        )
        """
    )
    conn.commit()


def list_saved_scenarios(mode: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    _validate_mode(mode)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT name, created_at, updated_at
            FROM saved_scenarios
            WHERE mode = ?
            ORDER BY updated_at DESC, name COLLATE NOCASE ASC
            """,
            (mode,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_saved_scenario(
    *,
    mode: str,
    name: str,
    payload: dict[str, Any],
    db_path: str | Path | None = None,
) -> None:
    _validate_mode(mode)
    scenario_name = _validate_name(name)
    now = _utc_now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False)

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO saved_scenarios (mode, name, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mode, name) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (mode, scenario_name, payload_json, now, now),
        )
        conn.commit()


def load_saved_scenario(mode: str, name: str, db_path: str | Path | None = None) -> dict[str, Any]:
    _validate_mode(mode)
    scenario_name = _validate_name(name)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM saved_scenarios
            WHERE mode = ? AND name = ?
            """,
            (mode, scenario_name),
        ).fetchone()
    if row is None:
        raise KeyError(f"Saved scenario not found: mode={mode!r}, name={scenario_name!r}")
    return json.loads(row["payload_json"])


def delete_saved_scenario(mode: str, name: str, db_path: str | Path | None = None) -> bool:
    _validate_mode(mode)
    scenario_name = _validate_name(name)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            """
            DELETE FROM saved_scenarios
            WHERE mode = ? AND name = ?
            """,
            (mode, scenario_name),
        )
        conn.commit()
        return cur.rowcount > 0

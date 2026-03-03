"""Database utilities and schema for HS tracker."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            company TEXT NOT NULL,
            modality TEXT NOT NULL,
            targets TEXT,
            target_class TEXT,
            dosing_route TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            alias_norm TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS product_ownership_history (
            ownership_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            company TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS trials (
            trial_id TEXT PRIMARY KEY,
            product_id TEXT,
            sponsor_display TEXT,
            responsible_party_type TEXT,
            phase TEXT,
            status TEXT,
            study_start_date TEXT,
            primary_completion_date TEXT,
            completion_date TEXT,
            enrollment INTEGER,
            countries_json TEXT,
            url TEXT,
            first_posted TEXT,
            last_update_posted TEXT,
            results_first_posted TEXT,
            inclusion_flag INTEGER NOT NULL DEFAULT 0,
            exclusion_reason TEXT,
            raw_payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS activity_events (
            event_id TEXT PRIMARY KEY,
            product_id TEXT,
            trial_id TEXT,
            event_date TEXT,
            event_type TEXT NOT NULL,
            event_summary TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT,
            confidence TEXT,
            impact TEXT,
            signal_category TEXT,
            weight INTEGER NOT NULL,
            high_signal INTEGER NOT NULL DEFAULT 0,
            source_snapshot_meta_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE SET NULL,
            FOREIGN KEY(trial_id) REFERENCES trials(trial_id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS trial_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trial_id TEXT NOT NULL,
            status TEXT,
            last_update_posted TEXT,
            results_first_posted TEXT,
            captured_at TEXT NOT NULL,
            payload_json TEXT,
            FOREIGN KEY(trial_id) REFERENCES trials(trial_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            setting_key TEXT PRIMARY KEY,
            setting_value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trials_product ON trials(product_id);
        CREATE INDEX IF NOT EXISTS idx_trials_inclusion ON trials(inclusion_flag);
        CREATE INDEX IF NOT EXISTS idx_events_product ON activity_events(product_id);
        CREATE INDEX IF NOT EXISTS idx_events_date ON activity_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_events_type ON activity_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_alias_product ON product_aliases(product_id);
        """
    )


def set_json_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO settings(setting_key, setting_value_json, updated_at)
        VALUES(?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value_json=excluded.setting_value_json,
            updated_at=excluded.updated_at
        """,
        (key, json.dumps(value), now),
    )


def get_json_setting(conn: sqlite3.Connection, key: str, default: Any) -> Any:
    row = conn.execute(
        "SELECT setting_value_json FROM settings WHERE setting_key = ?",
        (key,),
    ).fetchone()
    if not row:
        return default
    return json.loads(row["setting_value_json"])

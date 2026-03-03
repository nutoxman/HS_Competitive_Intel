"""Quality-control checks for HS tracker data."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from hs_tracker.service import compute_program_metrics


def _valid_iso_date(value: str | None) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def build_qc_report(conn: sqlite3.Connection, as_of: date | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {}

    report["trials_without_product_mapping"] = [
        dict(row)
        for row in conn.execute(
            "SELECT trial_id, sponsor_display, phase, status FROM trials WHERE product_id IS NULL"
        ).fetchall()
    ]

    report["events_without_product_mapping"] = [
        dict(row)
        for row in conn.execute(
            "SELECT event_id, event_type, event_date, source_url FROM activity_events WHERE product_id IS NULL"
        ).fetchall()
    ]

    events = [dict(row) for row in conn.execute("SELECT event_id, event_date FROM activity_events").fetchall()]
    report["event_dates_not_parseable"] = [
        event for event in events if not _valid_iso_date(event.get("event_date"))
    ]

    report["duplicate_events"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                COALESCE(product_id, '') AS product_id,
                event_type,
                COALESCE(event_date, '') AS event_date,
                COALESCE(source_url, '') AS source_url,
                COUNT(*) AS duplicate_count
            FROM activity_events
            GROUP BY COALESCE(product_id, ''), event_type, COALESCE(event_date, ''), COALESCE(source_url, '')
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    ]

    report["programs_trials_but_no_events"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.product_id, p.canonical_name, p.company
            FROM products p
            WHERE EXISTS (SELECT 1 FROM trials t WHERE t.product_id = p.product_id)
              AND NOT EXISTS (SELECT 1 FROM activity_events e WHERE e.product_id = p.product_id)
            """
        ).fetchall()
    ]

    report["programs_events_but_no_trials"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.product_id, p.canonical_name, p.company
            FROM products p
            WHERE EXISTS (SELECT 1 FROM activity_events e WHERE e.product_id = p.product_id)
              AND NOT EXISTS (SELECT 1 FROM trials t WHERE t.product_id = p.product_id)
            """
        ).fetchall()
    ]

    metrics = compute_program_metrics(conn, as_of=as_of)
    report["high_activity_no_included_trials"] = [
        {
            "product_id": row["product_id"],
            "canonical_name": row["canonical_name"],
            "activity_score_12m": row["activity_score_12m"],
        }
        for row in metrics
        if row["activity_score_12m"] > 0 and row["included_trial_count"] == 0
    ]

    report["excluded_trials_incorrectly_included"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT trial_id, phase, exclusion_reason
            FROM trials
            WHERE inclusion_flag = 1
              AND (
                    phase = 'Phase 4'
                    OR exclusion_reason IN ('topical', 'device_only', 'procedural_hybrid', 'academic', 'out_of_window')
                  )
            """
        ).fetchall()
    ]

    report["inconsistent_sponsor_naming"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT lower(trim(sponsor_display)) AS sponsor_norm, COUNT(DISTINCT sponsor_display) AS variants,
                   GROUP_CONCAT(DISTINCT sponsor_display) AS raw_values
            FROM trials
            WHERE sponsor_display IS NOT NULL AND sponsor_display <> ''
            GROUP BY lower(trim(sponsor_display))
            HAVING COUNT(DISTINCT sponsor_display) > 1
            """
        ).fetchall()
    ]

    report["summary"] = {
        key: len(value) for key, value in report.items() if isinstance(value, list)
    }
    return report

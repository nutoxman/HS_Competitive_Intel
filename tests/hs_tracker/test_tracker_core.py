from __future__ import annotations

import sqlite3
from datetime import date

from hs_tracker.db import init_db
from hs_tracker.qc import build_qc_report
from hs_tracker.service import (
    compute_program_metrics,
    ensure_default_settings,
    insert_event,
    resolve_product_id,
    upsert_product,
    upsert_trial,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    ensure_default_settings(conn)
    return conn


def test_alias_resolution_normalizes_codes() -> None:
    conn = _conn()
    pid = upsert_product(
        conn,
        canonical_name="Remibrutinib",
        company="Novartis",
        modality="Small molecule",
        aliases=["LOU064", "LYS006"],
    )

    assert resolve_product_id(conn, ["A study of LYS006 in hidradenitis suppurativa"]) == pid
    assert resolve_product_id(conn, ["Evaluation of lou-064 in HS"]) == pid


def test_activity_score_and_staleness_are_deterministic() -> None:
    conn = _conn()
    pid = upsert_product(
        conn,
        canonical_name="Povorcitinib",
        company="Incyte",
        modality="Small molecule",
    )

    insert_event(
        conn,
        {
            "product_id": pid,
            "event_date": "2025-12-01",
            "event_type": "results_posted",
            "event_summary": "Results posted",
            "source_type": "registry",
            "source_name": "ClinicalTrials.gov",
        },
    )
    insert_event(
        conn,
        {
            "product_id": pid,
            "event_date": "2025-08-10",
            "event_type": "news_analysis",
            "event_summary": "News",
            "source_type": "news",
            "source_name": "BioNews",
        },
    )

    metrics = compute_program_metrics(conn, as_of=date(2026, 3, 3))
    row = next(item for item in metrics if item["product_id"] == pid)

    assert row["activity_score_12m"] == 6
    assert row["last_high_signal_date"] == "2025-12-01"
    assert row["days_since_high_signal"] == (date(2026, 3, 3) - date(2025, 12, 1)).days
    assert row["staleness_flag"] == "Yellow"


def test_quiet_but_advancing_logic() -> None:
    conn = _conn()
    pid = upsert_product(
        conn,
        canonical_name="Sonelokimab",
        company="MoonLake",
        modality="Antibody",
    )

    upsert_trial(
        conn,
        {
            "trial_id": "NCT00000001",
            "product_id": pid,
            "phase": "Phase 3",
            "status": "RECRUITING",
            "study_start_date": "2025-03-01",
            "inclusion_flag": True,
            "countries": ["United Kingdom"],
            "sponsor_display": "MoonLake",
        },
    )

    metrics = compute_program_metrics(conn, as_of=date(2026, 3, 3))
    row = next(item for item in metrics if item["product_id"] == pid)
    assert row["quiet_but_advancing"] is True

    insert_event(
        conn,
        {
            "product_id": pid,
            "event_date": "2026-02-20",
            "event_type": "press_release_pipeline_update",
            "event_summary": "Press release",
            "source_type": "press_release",
            "source_name": "MoonLake",
        },
    )

    metrics = compute_program_metrics(conn, as_of=date(2026, 3, 3))
    row = next(item for item in metrics if item["product_id"] == pid)
    assert row["quiet_but_advancing"] is False


def test_qc_report_flags_unmapped_and_duplicates() -> None:
    conn = _conn()
    pid = upsert_product(
        conn,
        canonical_name="Example",
        company="ExampleCo",
        modality="Other",
    )

    upsert_trial(
        conn,
        {
            "trial_id": "NCT11111111",
            "product_id": None,
            "phase": "Phase 2",
            "status": "COMPLETED",
            "study_start_date": "2024-01-01",
            "inclusion_flag": True,
            "countries": ["France"],
            "sponsor_display": "ExampleCo",
        },
    )

    # Insert duplicate events directly to validate QC duplicate detection.
    conn.execute(
        """
        INSERT INTO activity_events(
            event_id, product_id, trial_id, event_date, event_type, event_summary, source_type,
            source_name, source_url, confidence, impact, signal_category, weight, high_signal,
            source_snapshot_meta_json, created_at, updated_at
        ) VALUES
            ('e1', ?, NULL, '2025-05-01', 'news_analysis', 'dup', 'news', 'src', 'http://x',
             'Medium', 'Low', 'News/Analysis', 1, 0, '{}', '2026-03-03T00:00:00+00:00', '2026-03-03T00:00:00+00:00'),
            ('e2', ?, NULL, '2025-05-01', 'news_analysis', 'dup', 'news', 'src', 'http://x',
             'Medium', 'Low', 'News/Analysis', 1, 0, '{}', '2026-03-03T00:00:00+00:00', '2026-03-03T00:00:00+00:00')
        """,
        (pid, pid),
    )
    conn.execute(
        """
        INSERT INTO activity_events(
            event_id, product_id, trial_id, event_date, event_type, event_summary, source_type,
            source_name, source_url, confidence, impact, signal_category, weight, high_signal,
            source_snapshot_meta_json, created_at, updated_at
        ) VALUES
            ('e3', NULL, NULL, NULL, 'news_analysis', 'unmapped', 'news', 'src', NULL,
             'Medium', 'Low', 'News/Analysis', 1, 0, '{}', '2026-03-03T00:00:00+00:00', '2026-03-03T00:00:00+00:00')
        """
    )

    report = build_qc_report(conn, as_of=date(2026, 3, 3))

    assert len(report["trials_without_product_mapping"]) == 1
    assert len(report["events_without_product_mapping"]) == 1
    assert len(report["duplicate_events"]) == 1
    assert len(report["event_dates_not_parseable"]) == 1


def test_rolling_year_window_filters_program_rollups() -> None:
    conn = _conn()
    pid = upsert_product(
        conn,
        canonical_name="WindowDrug",
        company="WindowCo",
        modality="Small molecule",
    )
    upsert_trial(
        conn,
        {
            "trial_id": "NCT22222222",
            "product_id": pid,
            "phase": "Phase 2",
            "status": "COMPLETED",
            "study_start_date": "2020-01-01",
            "inclusion_flag": True,
            "countries": ["Germany"],
            "sponsor_display": "WindowCo",
        },
    )

    metrics_5y = compute_program_metrics(conn, as_of=date(2026, 3, 3), rolling_years=5)
    metrics_7y = compute_program_metrics(conn, as_of=date(2026, 3, 3), rolling_years=7)

    row_5y = next(item for item in metrics_5y if item["product_id"] == pid)
    row_7y = next(item for item in metrics_7y if item["product_id"] == pid)

    assert row_5y["hs_activity_5y"] is False
    assert row_7y["hs_activity_5y"] is True

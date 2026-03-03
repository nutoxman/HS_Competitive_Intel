"""Core CRUD and metric services for HS tracker."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from hs_tracker.canonicalize import alias_matches_text, normalize_text
from hs_tracker.constants import (
    ACTIVE_TRIAL_STATUSES,
    DEFAULT_EVENT_WEIGHTS,
    EVENT_TYPE_TO_CATEGORY,
    GREEN_DAYS,
    HIGH_SIGNAL_EVENT_TYPES,
    PHASE_ORDER,
    PR_PIPELINE_SOURCE_TYPES,
    YELLOW_DAYS,
)
from hs_tracker.db import get_json_setting, set_json_setting, utc_now_iso


DATE_FIELDS = {
    "study_start_date",
    "primary_completion_date",
    "completion_date",
    "first_posted",
    "last_update_posted",
    "results_first_posted",
    "event_date",
}


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            parsed = datetime.strptime(text[:length], fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1)
            if fmt == "%Y-%m":
                return date(parsed.year, parsed.month, 1)
            return parsed.date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_to_iso(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def ensure_default_settings(conn: sqlite3.Connection) -> None:
    if not conn.execute("SELECT 1 FROM settings WHERE setting_key='event_weights'").fetchone():
        set_json_setting(conn, "event_weights", DEFAULT_EVENT_WEIGHTS)
    if not conn.execute(
        "SELECT 1 FROM settings WHERE setting_key='high_signal_event_types'"
    ).fetchone():
        set_json_setting(conn, "high_signal_event_types", sorted(HIGH_SIGNAL_EVENT_TYPES))


def get_event_weights(conn: sqlite3.Connection) -> dict[str, int]:
    raw = get_json_setting(conn, "event_weights", DEFAULT_EVENT_WEIGHTS)
    return {k: int(v) for k, v in raw.items()}


def get_high_signal_event_types(conn: sqlite3.Connection) -> set[str]:
    raw = get_json_setting(conn, "high_signal_event_types", sorted(HIGH_SIGNAL_EVENT_TYPES))
    return {str(item) for item in raw}


def upsert_product(
    conn: sqlite3.Connection,
    canonical_name: str,
    company: str,
    modality: str,
    aliases: list[str] | None = None,
    product_id: str | None = None,
    targets: str | None = None,
    target_class: str | None = None,
    dosing_route: str | None = None,
    notes: str | None = None,
) -> str:
    pid = product_id or str(uuid4())
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO products(
            product_id, canonical_name, company, modality, targets, target_class, dosing_route, notes,
            created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
            canonical_name=excluded.canonical_name,
            company=excluded.company,
            modality=excluded.modality,
            targets=excluded.targets,
            target_class=excluded.target_class,
            dosing_route=excluded.dosing_route,
            notes=excluded.notes,
            updated_at=excluded.updated_at
        """,
        (
            pid,
            canonical_name.strip(),
            company.strip(),
            modality.strip(),
            targets,
            target_class,
            dosing_route,
            notes,
            now,
            now,
        ),
    )

    alias_values = {canonical_name}
    if aliases:
        alias_values.update(alias for alias in aliases if alias and alias.strip())

    for alias in sorted(alias_values):
        alias_norm = normalize_text(alias)
        existing = conn.execute(
            "SELECT product_id FROM product_aliases WHERE alias_norm = ?",
            (alias_norm,),
        ).fetchone()
        if existing and existing["product_id"] != pid:
            raise ValueError(
                f"Alias '{alias}' is already mapped to a different product_id ({existing['product_id']})."
            )
        conn.execute(
            """
            INSERT INTO product_aliases(product_id, alias, alias_norm, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(alias_norm) DO UPDATE SET
                product_id=excluded.product_id,
                alias=excluded.alias
            """,
            (pid, alias.strip(), alias_norm, now),
        )

    return pid


def record_ownership(
    conn: sqlite3.Connection,
    product_id: str,
    company: str,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO product_ownership_history(product_id, company, start_date, end_date, notes, created_at)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (product_id, company, _date_to_iso(start_date), _date_to_iso(end_date), notes, utc_now_iso()),
    )


def resolve_product_id(conn: sqlite3.Connection, text_candidates: list[str]) -> str | None:
    alias_rows = conn.execute(
        "SELECT product_id, alias FROM product_aliases"
    ).fetchall()
    for text in text_candidates:
        if not text:
            continue
        for row in alias_rows:
            if alias_matches_text(row["alias"], text):
                return str(row["product_id"])
    return None


def upsert_trial(conn: sqlite3.Connection, trial: dict[str, Any]) -> None:
    now = utc_now_iso()
    countries_json = json.dumps(trial.get("countries", []))
    raw_payload_json = json.dumps(trial.get("raw_payload", {}))

    conn.execute(
        """
        INSERT INTO trials(
            trial_id, product_id, sponsor_display, responsible_party_type, phase, status,
            study_start_date, primary_completion_date, completion_date, enrollment,
            countries_json, url, first_posted, last_update_posted, results_first_posted,
            inclusion_flag, exclusion_reason, raw_payload_json, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trial_id) DO UPDATE SET
            product_id=excluded.product_id,
            sponsor_display=excluded.sponsor_display,
            responsible_party_type=excluded.responsible_party_type,
            phase=excluded.phase,
            status=excluded.status,
            study_start_date=excluded.study_start_date,
            primary_completion_date=excluded.primary_completion_date,
            completion_date=excluded.completion_date,
            enrollment=excluded.enrollment,
            countries_json=excluded.countries_json,
            url=excluded.url,
            first_posted=excluded.first_posted,
            last_update_posted=excluded.last_update_posted,
            results_first_posted=excluded.results_first_posted,
            inclusion_flag=excluded.inclusion_flag,
            exclusion_reason=excluded.exclusion_reason,
            raw_payload_json=excluded.raw_payload_json,
            updated_at=excluded.updated_at
        """,
        (
            trial["trial_id"],
            trial.get("product_id"),
            trial.get("sponsor_display"),
            trial.get("responsible_party_type"),
            trial.get("phase"),
            trial.get("status"),
            _date_to_iso(trial.get("study_start_date")),
            _date_to_iso(trial.get("primary_completion_date")),
            _date_to_iso(trial.get("completion_date")),
            trial.get("enrollment"),
            countries_json,
            trial.get("url"),
            _date_to_iso(trial.get("first_posted")),
            _date_to_iso(trial.get("last_update_posted")),
            _date_to_iso(trial.get("results_first_posted")),
            int(bool(trial.get("inclusion_flag"))),
            trial.get("exclusion_reason"),
            raw_payload_json,
            now,
            now,
        ),
    )

    conn.execute(
        """
        INSERT INTO trial_snapshots(
            trial_id, status, last_update_posted, results_first_posted, captured_at, payload_json
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            trial["trial_id"],
            trial.get("status"),
            _date_to_iso(trial.get("last_update_posted")),
            _date_to_iso(trial.get("results_first_posted")),
            now,
            raw_payload_json,
        ),
    )


def get_trial(conn: sqlite3.Connection, trial_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def insert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> str | None:
    event_id = event.get("event_id") or str(uuid4())
    event_date = _date_to_iso(event.get("event_date"))
    weight_map = get_event_weights(conn)
    high_signal_types = get_high_signal_event_types(conn)
    event_type = event["event_type"]
    weight = int(event.get("weight", weight_map.get(event_type, 1)))
    signal_category = event.get("signal_category") or EVENT_TYPE_TO_CATEGORY.get(
        event_type, "News/Analysis"
    )
    high_signal = int(
        bool(
            event.get("high_signal")
            if event.get("high_signal") is not None
            else event_type in high_signal_types
        )
    )

    duplicate = conn.execute(
        """
        SELECT event_id FROM activity_events
        WHERE COALESCE(product_id, '') = COALESCE(?, '')
          AND event_type = ?
          AND COALESCE(event_date, '') = COALESCE(?, '')
          AND COALESCE(source_url, '') = COALESCE(?, '')
        """,
        (event.get("product_id"), event_type, event_date, event.get("source_url")),
    ).fetchone()
    if duplicate:
        return None

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO activity_events(
            event_id, product_id, trial_id, event_date, event_type, event_summary, source_type,
            source_name, source_url, confidence, impact, signal_category, weight, high_signal,
            source_snapshot_meta_json, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event.get("product_id"),
            event.get("trial_id"),
            event_date,
            event_type,
            event.get("event_summary", ""),
            event.get("source_type", "news"),
            event.get("source_name", "Unknown"),
            event.get("source_url"),
            event.get("confidence", "Medium"),
            event.get("impact", "Medium"),
            signal_category,
            weight,
            high_signal,
            json.dumps(event.get("source_snapshot_meta", {})),
            now,
            now,
        ),
    )
    return event_id


def emit_trial_change_events(
    conn: sqlite3.Connection,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> list[str]:
    emitted: list[str] = []

    if not after.get("product_id"):
        return emitted

    if before is None and after.get("first_posted"):
        eid = insert_event(
            conn,
            {
                "product_id": after["product_id"],
                "trial_id": after["trial_id"],
                "event_date": after.get("first_posted"),
                "event_type": "trial_first_posted",
                "event_summary": f"Trial {after['trial_id']} first posted on registry.",
                "source_type": "registry",
                "source_name": "ClinicalTrials.gov",
                "source_url": after.get("url"),
                "confidence": "High",
                "impact": "Medium",
            },
        )
        if eid:
            emitted.append(eid)

    if before is None and after.get("study_start_date"):
        eid = insert_event(
            conn,
            {
                "product_id": after["product_id"],
                "trial_id": after["trial_id"],
                "event_date": after.get("study_start_date"),
                "event_type": "study_start",
                "event_summary": f"Study start captured for {after['trial_id']}.",
                "source_type": "registry",
                "source_name": "ClinicalTrials.gov",
                "source_url": after.get("url"),
                "confidence": "High",
                "impact": "High",
            },
        )
        if eid:
            emitted.append(eid)

    if before and before.get("status") != after.get("status") and after.get("status"):
        change_date = after.get("last_update_posted") or after.get("study_start_date")
        eid = insert_event(
            conn,
            {
                "product_id": after["product_id"],
                "trial_id": after["trial_id"],
                "event_date": change_date,
                "event_type": "trial_status_change",
                "event_summary": (
                    f"Trial {after['trial_id']} status changed "
                    f"from {before.get('status') or 'Unknown'} to {after.get('status')}."
                ),
                "source_type": "registry",
                "source_name": "ClinicalTrials.gov",
                "source_url": after.get("url"),
                "confidence": "High",
                "impact": "High",
            },
        )
        if eid:
            emitted.append(eid)

    if before and before.get("last_update_posted") != after.get("last_update_posted"):
        eid = insert_event(
            conn,
            {
                "product_id": after["product_id"],
                "trial_id": after["trial_id"],
                "event_date": after.get("last_update_posted"),
                "event_type": "trial_registry_update",
                "event_summary": f"Registry update posted for trial {after['trial_id']}.",
                "source_type": "registry",
                "source_name": "ClinicalTrials.gov",
                "source_url": after.get("url"),
                "confidence": "High",
                "impact": "Low",
            },
        )
        if eid:
            emitted.append(eid)

    results_added = (
        after.get("results_first_posted")
        and (before is None or not before.get("results_first_posted"))
    )
    if results_added:
        eid = insert_event(
            conn,
            {
                "product_id": after["product_id"],
                "trial_id": after["trial_id"],
                "event_date": after.get("results_first_posted"),
                "event_type": "results_posted",
                "event_summary": f"Results first posted for trial {after['trial_id']}.",
                "source_type": "registry",
                "source_name": "ClinicalTrials.gov",
                "source_url": after.get("url"),
                "confidence": "High",
                "impact": "High",
            },
        )
        if eid:
            emitted.append(eid)

    return emitted


def _phase_rank(phase: str | None) -> int:
    if not phase:
        return 0
    return PHASE_ORDER.get(phase, 0)


def _highest_phase(phases: list[str]) -> str | None:
    if not phases:
        return None
    return sorted(phases, key=_phase_rank)[-1]


def _status_summary(statuses: list[str]) -> str:
    if not statuses:
        return "No included trials"
    counts = Counter(statuses)
    return ", ".join(f"{name} ({count})" for name, count in counts.most_common())


def _staleness_label(days_since: int | None, has_events: bool) -> str:
    if not has_events:
        return "Red (No Signals)"
    if days_since is None:
        return "Red"
    if days_since < GREEN_DAYS:
        return "Green"
    if days_since <= YELLOW_DAYS:
        return "Yellow"
    return "Red"


def _days_between(start: date, end: date | None) -> int | None:
    if not end:
        return None
    return (start - end).days


def list_products_with_aliases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            p.*, 
            COALESCE(
                json_group_array(a.alias) FILTER (WHERE a.alias IS NOT NULL),
                json('[]')
            ) AS aliases_json
        FROM products p
        LEFT JOIN product_aliases a ON p.product_id = a.product_id
        GROUP BY p.product_id
        ORDER BY p.company, p.canonical_name
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        aliases = _json_loads(item.pop("aliases_json"), [])
        unique_aliases = sorted({alias for alias in aliases if alias != item["canonical_name"]})
        item["aliases"] = unique_aliases
        item["all_names_display"] = ", ".join([item["canonical_name"], *unique_aliases])
        result.append(item)
    return result


def _load_trials(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM trials").fetchall()
    trials: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["countries"] = _json_loads(item.get("countries_json"), [])
        trials.append(item)
    return trials


def _load_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM activity_events").fetchall()
    return [dict(row) for row in rows]


def compute_program_metrics(
    conn: sqlite3.Connection,
    as_of: date | None = None,
    rolling_years: int | None = None,
) -> list[dict[str, Any]]:
    run_date = as_of or date.today()
    score_cutoff = run_date - timedelta(days=365)
    quiet_cutoff = run_date - timedelta(days=180)
    trial_cutoff = run_date - timedelta(days=365 * rolling_years) if rolling_years else None

    products = list_products_with_aliases(conn)
    trials = _load_trials(conn)
    events = _load_events(conn)

    trials_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        pid = trial.get("product_id")
        if pid:
            trials_by_product[str(pid)].append(trial)

    events_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        pid = event.get("product_id")
        if pid:
            events_by_product[str(pid)].append(event)

    output: list[dict[str, Any]] = []
    for product in products:
        pid = str(product["product_id"])
        product_trials = trials_by_product.get(pid, [])
        product_events = events_by_product.get(pid, [])

        included_trials = []
        for trial in product_trials:
            if int(trial["inclusion_flag"]) != 1:
                continue
            if trial_cutoff is None:
                included_trials.append(trial)
                continue
            start_date = _parse_date(trial.get("study_start_date"))
            if start_date and start_date >= trial_cutoff:
                included_trials.append(trial)
        included_statuses = [trial["status"] for trial in included_trials if trial.get("status")]
        included_countries = sorted(
            {
                country
                for trial in included_trials
                for country in _json_loads(trial.get("countries_json"), [])
                if country
            }
        )
        highest_phase = _highest_phase(
            [trial["phase"] for trial in included_trials if trial.get("phase")]
        )
        hs_activity_5y = bool(included_trials)

        event_dates = [
            _parse_date(event.get("event_date")) for event in product_events if event.get("event_date")
        ]
        event_dates = [d for d in event_dates if d]
        last_event_date = max(event_dates) if event_dates else None

        high_event_dates = [
            _parse_date(event.get("event_date"))
            for event in product_events
            if int(event.get("high_signal", 0)) == 1 and event.get("event_date")
        ]
        high_event_dates = [d for d in high_event_dates if d]
        last_high_signal_date = max(high_event_dates) if high_event_dates else None

        activity_score = 0
        for event in product_events:
            event_date = _parse_date(event.get("event_date"))
            if event_date and event_date >= score_cutoff:
                activity_score += int(event.get("weight", 0) or 0)

        days_since_high = _days_between(run_date, last_high_signal_date)
        days_since_event = _days_between(run_date, last_event_date)
        staleness_base = days_since_high if days_since_high is not None else days_since_event

        has_active_included_trial = any(
            (trial.get("status") or "") in ACTIVE_TRIAL_STATUSES for trial in included_trials
        )
        has_recent_pr_pipeline = any(
            (_parse_date(event.get("event_date")) or date.min) >= quiet_cutoff
            and event.get("source_type") in PR_PIPELINE_SOURCE_TYPES
            for event in product_events
        )

        output.append(
            {
                **product,
                "highest_phase_hs": highest_phase,
                "status_summary": _status_summary(included_statuses),
                "activity_score_12m": activity_score,
                "last_event_date": last_event_date.isoformat() if last_event_date else None,
                "last_high_signal_date": (
                    last_high_signal_date.isoformat() if last_high_signal_date else None
                ),
                "days_since_high_signal": days_since_high,
                "staleness_flag": _staleness_label(staleness_base, has_events=bool(product_events)),
                "quiet_but_advancing": bool(has_active_included_trial and not has_recent_pr_pipeline),
                "hs_activity_5y": hs_activity_5y,
                "stale_no_recent_signal": (
                    _staleness_label(staleness_base, has_events=bool(product_events)).startswith("Red")
                ),
                "geographies": included_countries,
                "included_trial_count": len(included_trials),
                "event_count": len(product_events),
            }
        )

    return output


def get_program_detail(conn: sqlite3.Connection, product_id: str) -> dict[str, Any] | None:
    products = list_products_with_aliases(conn)
    product = next((item for item in products if item["product_id"] == product_id), None)
    if not product:
        return None

    trials = [trial for trial in _load_trials(conn) if trial.get("product_id") == product_id]
    for trial in trials:
        trial["countries"] = _json_loads(trial.get("countries_json"), [])

    events = [event for event in _load_events(conn) if event.get("product_id") == product_id]
    events.sort(key=lambda row: row.get("event_date") or "", reverse=True)

    sources = []
    seen = set()
    for event in events:
        key = (event.get("source_name"), event.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "source_name": event.get("source_name"),
                "source_type": event.get("source_type"),
                "source_url": event.get("source_url"),
            }
        )

    return {
        "product": product,
        "trials": sorted(trials, key=lambda row: row.get("study_start_date") or "", reverse=True),
        "events": events,
        "sources": sources,
    }


def list_trials(
    conn: sqlite3.Connection,
    included_only: bool = False,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM trials WHERE inclusion_flag = 1" if included_only else "SELECT * FROM trials"
    ).fetchall()
    trials: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["countries"] = _json_loads(item.get("countries_json"), [])
        trials.append(item)
    return trials


def add_manual_event(
    conn: sqlite3.Connection,
    product_id: str,
    event_date: str,
    event_type: str,
    event_summary: str,
    source_type: str,
    source_name: str,
    source_url: str | None,
    confidence: str,
    impact: str,
    weight: int | None = None,
    high_signal: bool | None = None,
) -> str | None:
    return insert_event(
        conn,
        {
            "product_id": product_id,
            "event_date": event_date,
            "event_type": event_type,
            "event_summary": event_summary,
            "source_type": source_type,
            "source_name": source_name,
            "source_url": source_url,
            "confidence": confidence,
            "impact": impact,
            "weight": weight,
            "high_signal": high_signal,
        },
    )


def get_filter_values(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = compute_program_metrics(conn)
    companies = sorted({row["company"] for row in rows if row.get("company")})
    modalities = sorted({row["modality"] for row in rows if row.get("modality")})
    target_classes = sorted({row["target_class"] for row in rows if row.get("target_class")})
    phases = sorted({row["highest_phase_hs"] for row in rows if row.get("highest_phase_hs")})
    staleness = sorted({row["staleness_flag"] for row in rows if row.get("staleness_flag")})
    return {
        "companies": companies,
        "modalities": modalities,
        "target_classes": target_classes,
        "phases": phases,
        "staleness": staleness,
    }

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from engine.models.settings import GlobalSettings


BucketType = Literal["year", "quarter", "month", "week"]


def _bucket_key(d: date, bucket_type: BucketType, settings: GlobalSettings):
    if bucket_type == "year":
        return (d.year,)
    if bucket_type == "quarter":
        q = (d.month - 1) // 3 + 1
        return (d.year, q)
    if bucket_type == "month":
        return (d.year, d.month)
    if bucket_type == "week":
        # Align to week ending day
        offset = (settings.week_ending_day - d.weekday()) % 7
        week_end = d + timedelta(days=offset)
        return (week_end,)
    raise ValueError(f"Unsupported bucket_type: {bucket_type}")


def build_bucket_summary(
    *,
    incident: dict[date, float],
    cumulative: dict[date, float],
    active_sites: dict[date, float],
    activation_pct: dict[date, float],
    bucket_type: BucketType,
    settings: GlobalSettings,
) -> list[dict]:
    """
    Returns list of bucket summaries:
        - bucket_id
        - incremental
        - cumulative_to_date
        - avg_active_sites
        - avg_activation_pct
    """
    buckets = defaultdict(list)

    for d in sorted(incident.keys()):
        key = _bucket_key(d, bucket_type, settings)
        buckets[key].append(d)

    results = []

    for key, days in sorted(buckets.items()):
        inc = sum(incident[d] for d in days)
        last_day = max(days)
        cum = cumulative.get(last_day, 0.0)
        avg_sites = sum(active_sites.get(d, 0.0) for d in days) / len(days)
        avg_pct = sum(activation_pct.get(d, 0.0) for d in days) / len(days)

        results.append(
            {
                "bucket": key,
                "incremental": inc,
                "cumulative_to_date": cum,
                "avg_active_sites": avg_sites,
                "avg_activation_pct": avg_pct,
            }
        )

    return results

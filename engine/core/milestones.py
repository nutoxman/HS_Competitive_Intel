from __future__ import annotations

from datetime import date, timedelta


def incremental_time_milestones(
    fsfv: date,
    lsfv: date,
    cumulative: dict[date, float],
) -> list[dict]:
    """
    Incremental (5%) milestones over time.
    For pct in 0..100 step 5:
        - milestone date
        - days elapsed
        - cumulative value
    """
    duration = (lsfv - fsfv).days
    if duration <= 0:
        return []

    results = []
    for pct in range(0, 101, 5):
        if duration == 1:
            offset = 0
        else:
            offset = int((pct / 100.0) * (duration - 1))

        milestone_date = fsfv + timedelta(days=offset)
        value = cumulative.get(milestone_date, 0.0)

        results.append(
            {
                "pct": pct,
                "date": milestone_date,
                "days_elapsed": offset,
                "cumulative": value,
            }
        )

    return results


def target_milestones(
    cumulative: dict[date, float],
    target_value: float,
) -> list[dict]:
    """
    For pct in 5..100 step 5:
        - threshold = pct × target
        - first date cumulative >= threshold
    """
    if not cumulative:
        return []

    sorted_dates = sorted(cumulative.keys())
    results = []

    for pct in range(5, 101, 5):
        threshold = target_value * (pct / 100.0)
        achieved_date = None
        achieved_value = None

        for d in sorted_dates:
            if cumulative[d] >= threshold:
                achieved_date = d
                achieved_value = cumulative[d]
                break

        results.append(
            {
                "pct": pct,
                "threshold": threshold,
                "date": achieved_date,
                "cumulative": achieved_value,
            }
        )

    return results

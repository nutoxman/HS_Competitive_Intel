from __future__ import annotations

from datetime import date, timedelta


def shift_series(incident: dict[date, float], days: int) -> dict[date, float]:
    """
    Shift an incident series by N days.
    Positive days shifts later (to the right), negative shifts earlier.
    """
    if days == 0:
        return dict(incident)
    out: dict[date, float] = {}
    delta = timedelta(days=days)
    for d, v in incident.items():
        out[d + delta] = out.get(d + delta, 0.0) + float(v)
    return out


def scale_series(incident: dict[date, float], factor: float) -> dict[date, float]:
    out: dict[date, float] = {}
    for d, v in incident.items():
        out[d] = float(v) * factor
    return out


def cumulative_from_incident(incident: dict[date, float]) -> dict[date, float]:
    """
    Build cumulative series by date. Dates sorted ascending.
    Cumulative is defined over all dates present in the incident keys.
    """
    out: dict[date, float] = {}
    total = 0.0
    for d in sorted(incident.keys()):
        total += float(incident[d])
        out[d] = total
    return out

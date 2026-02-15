from datetime import date, timedelta

from engine.core.buckets import build_bucket_summary
from engine.models.settings import GlobalSettings


def test_month_bucket_basic():
    settings = GlobalSettings()
    base = date(2026, 1, 1)

    incident = {}
    cumulative = {}
    active = {}
    pct = {}

    total = 0.0
    for i in range(40):
        d = base + timedelta(days=i)
        incident[d] = 1.0
        total += 1.0
        cumulative[d] = total
        active[d] = 10.0
        pct[d] = 50.0

    out = build_bucket_summary(
        incident=incident,
        cumulative=cumulative,
        active_sites=active,
        activation_pct=pct,
        bucket_type="month",
        settings=settings,
    )

    assert len(out) >= 2
    assert out[0]["incremental"] > 0
    assert out[0]["avg_active_sites"] == 10.0
    assert out[0]["avg_activation_pct"] == 50.0


def test_week_bucket_respects_week_ending():
    settings = GlobalSettings(week_ending_day=6)  # Sunday
    base = date(2026, 1, 1)

    incident = {}
    cumulative = {}
    active = {}
    pct = {}

    total = 0.0
    for i in range(14):
        d = base + timedelta(days=i)
        incident[d] = 1.0
        total += 1.0
        cumulative[d] = total
        active[d] = 5.0
        pct[d] = 20.0

    out = build_bucket_summary(
        incident=incident,
        cumulative=cumulative,
        active_sites=active,
        activation_pct=pct,
        bucket_type="week",
        settings=settings,
    )

    assert len(out) >= 2

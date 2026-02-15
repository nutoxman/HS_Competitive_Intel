from datetime import date, timedelta

from engine.core.milestones import incremental_time_milestones, target_milestones


def test_incremental_time_milestones_basic():
    fsfv = date(2026, 1, 1)
    lsfv = date(2026, 1, 11)  # 10 days
    cumulative = {fsfv + timedelta(days=i): float(i) for i in range(10)}

    out = incremental_time_milestones(fsfv, lsfv, cumulative)

    assert out[0]["pct"] == 0
    assert out[-1]["pct"] == 100
    assert len(out) == 21


def test_target_milestones_basic():
    cumulative = {}
    base = date(2026, 1, 1)
    for i in range(10):
        cumulative[base + timedelta(days=i)] = float(i)

    out = target_milestones(cumulative, target_value=9)

    # 100% threshold should be achieved at last day
    assert out[-1]["date"] == base + timedelta(days=9)

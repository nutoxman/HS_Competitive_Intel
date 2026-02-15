from datetime import date

import pytest

from engine.core.primary import build_primary_daily
from engine.models.settings import GlobalSettings
from engine.core.targets import ValidationError


def test_primary_length_and_bounds():
    settings = GlobalSettings(days_per_month=30.0)
    fsfv = date(2026, 1, 1)
    lsfv = date(2026, 1, 11)  # 10 days
    sites = 10
    sar = [0, 20, 40, 60, 80, 100]
    rr = [0, 1, 1, 1, 1, 1]  # 1 subj/site/month

    out = build_primary_daily(fsfv, lsfv, sites, sar, rr, settings)
    assert len(out.new_primary) == 10
    assert min(out.activation_pct.values()) >= 0
    assert max(out.activation_pct.values()) <= 100
    assert min(out.active_sites.values()) >= 0


def test_primary_throughput_multiplier_scales_incident_only():
    settings = GlobalSettings(days_per_month=30.0)
    fsfv = date(2026, 1, 1)
    lsfv = date(2026, 1, 6)  # 5 days
    sites = 10
    sar = [100, 100, 100, 100, 100, 100]
    rr = [3, 3, 3, 3, 3, 3]  # 3 subj/site/month => 0.1 per day per site if days_per_month=30

    base = build_primary_daily(fsfv, lsfv, sites, sar, rr, settings, throughput_multiplier=1.0)
    hi = build_primary_daily(fsfv, lsfv, sites, sar, rr, settings, throughput_multiplier=1.5)

    # Active sites unchanged
    assert base.active_sites == hi.active_sites
    assert base.activation_pct == hi.activation_pct

    # Incident scaled
    for d in base.new_primary:
        assert hi.new_primary[d] == pytest.approx(base.new_primary[d] * 1.5)


def test_negative_multiplier_clamped_to_zero():
    settings = GlobalSettings(days_per_month=30.0)
    fsfv = date(2026, 1, 1)
    lsfv = date(2026, 1, 3)  # 2 days
    sites = 10
    sar = [100, 100, 100, 100, 100, 100]
    rr = [3, 3, 3, 3, 3, 3]

    out = build_primary_daily(fsfv, lsfv, sites, sar, rr, settings, throughput_multiplier=-1.0)
    assert all(v == 0.0 for v in out.new_primary.values())


def test_invalid_sar_bounds_raises():
    settings = GlobalSettings()
    with pytest.raises(ValidationError):
        build_primary_daily(
            date(2026, 1, 1),
            date(2026, 1, 2),
            10,
            sar_pct=[0, 20, 40, 60, 80, 120],  # invalid
            rr_per_site_per_month=[1, 1, 1, 1, 1, 1],
            settings=settings,
        )

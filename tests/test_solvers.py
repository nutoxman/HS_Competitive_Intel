from datetime import date

from engine.core.targets import derive_targets
from engine.core.solvers import solve_lsfv_fixed_sites, solve_sites_fixed_timeline
from engine.models.settings import GlobalSettings


def test_solve_lsfv_fixed_sites_reaches_target():
    settings = GlobalSettings(days_per_month=30.0, max_duration_days=365)
    targets = derive_targets("Randomized", 10, 0.0, 0.0)  # primary Randomized target=10

    res = solve_lsfv_fixed_sites(
        fsfv=date(2026, 1, 1),
        sites=10,
        period_type="Randomized",
        targets=targets,
        screen_fail_rate=0.0,
        discontinuation_rate=0.0,
        lag_sr_days=0,
        lag_rc_days=0,
        sar_pct=[100, 100, 100, 100, 100, 100],
        rr_per_site_per_month=[3, 3, 3, 3, 3, 3],  # 0.1/day/site if days_per_month=30
        settings=settings,
    )

    assert res.reached is True
    assert res.solved_lsfv is not None
    assert res.solved_lsfv > date(2026, 1, 1)


def test_solve_sites_fixed_timeline_reaches_target():
    settings = GlobalSettings(days_per_month=30.0, max_sites=500)
    targets = derive_targets("Randomized", 10, 0.0, 0.0)

    res = solve_sites_fixed_timeline(
        fsfv=date(2026, 1, 1),
        lsfv=date(2026, 2, 1),
        period_type="Randomized",
        targets=targets,
        screen_fail_rate=0.0,
        discontinuation_rate=0.0,
        lag_sr_days=0,
        lag_rc_days=0,
        sar_pct=[100, 100, 100, 100, 100, 100],
        rr_per_site_per_month=[3, 3, 3, 3, 3, 3],
        settings=settings,
    )

    assert res.reached is True
    assert res.solved_sites is not None
    assert res.solved_sites >= 1

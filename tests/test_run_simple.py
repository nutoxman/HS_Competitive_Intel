from datetime import date

from engine.core.run_simple import run_simple_scenario
from engine.models.scenario import ScenarioInputs
from engine.models.settings import GlobalSettings


def test_run_simple_fixed_timeline_smoke():
    settings = GlobalSettings(days_per_month=30.0)
    inputs = ScenarioInputs(
        name="S1",
        goal_type="Randomized",
        goal_n=10,
        screen_fail_rate=0.0,
        discontinuation_rate=0.0,
        period_type="Randomized",
        driver="Fixed Timeline",
        fsfv=date(2026, 1, 1),
        lsfv=date(2026, 2, 1),
        sites=None,
        lag_sr_days=2,
        lag_rc_days=3,
        sar_pct=[100, 100, 100, 100, 100, 100],
        rr_per_site_per_month=[3, 3, 3, 3, 3, 3],
    )

    out = run_simple_scenario(inputs, settings)
    assert out.solve.solved_sites is not None
    assert out.targets.randomized == 10.0
    assert "Randomized" in out.milestones_time
    assert "month" in out.buckets

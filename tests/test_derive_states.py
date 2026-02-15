from datetime import date

import pytest

from engine.core.derive_states import derive_states_from_primary
from engine.core.targets import ValidationError


def test_period_randomized_shift_scale():
    # Primary randomized: 10 subjects on Jan 10
    primary = {date(2026, 1, 10): 10.0}

    out = derive_states_from_primary(
        period_type="Randomized",
        primary_new=primary,
        screen_fail_rate=0.2,          # 1/(1-0.2)=1.25 => screened incident 12.5
        discontinuation_rate=0.1,      # *(1-0.1)=0.9 => completed incident 9
        lag_sr_days=2,
        lag_rc_days=3,
    )

    assert out.randomized.incident[date(2026, 1, 10)] == pytest.approx(10.0)
    assert out.screened.incident[date(2026, 1, 8)] == pytest.approx(12.5)
    assert out.completed.incident[date(2026, 1, 13)] == pytest.approx(9.0)


def test_period_screened_shift_scale():
    primary = {date(2026, 1, 1): 100.0}
    out = derive_states_from_primary(
        period_type="Screened",
        primary_new=primary,
        screen_fail_rate=0.2,      # randomized = 80
        discontinuation_rate=0.1,  # completed = 72
        lag_sr_days=5,
        lag_rc_days=7,
    )
    assert out.screened.incident[date(2026, 1, 1)] == pytest.approx(100.0)
    assert out.randomized.incident[date(2026, 1, 6)] == pytest.approx(80.0)
    assert out.completed.incident[date(2026, 1, 13)] == pytest.approx(72.0)


def test_period_completed_shift_scale():
    primary = {date(2026, 2, 1): 50.0}
    out = derive_states_from_primary(
        period_type="Completed",
        primary_new=primary,
        screen_fail_rate=0.2,
        discontinuation_rate=0.1,  # randomized = 50/0.9 = 55.555...
        lag_sr_days=4,
        lag_rc_days=6,
    )
    assert out.completed.incident[date(2026, 2, 1)] == pytest.approx(50.0)
    assert out.randomized.incident[date(2026, 1, 26)] == pytest.approx(55.5555555555)
    assert out.screened.incident[date(2026, 1, 22)] == pytest.approx(69.4444444444)


def test_invalid_rates_raise():
    primary = {date(2026, 1, 1): 1.0}
    with pytest.raises(ValidationError):
        derive_states_from_primary("Randomized", primary, 1.0, 0.1, 1, 1)
    with pytest.raises(ValidationError):
        derive_states_from_primary("Randomized", primary, 0.1, 1.0, 1, 1)

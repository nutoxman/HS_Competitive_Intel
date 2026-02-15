import pytest

from engine.core.targets import ValidationError, derive_targets


def test_targets_from_randomized():
    t = derive_targets("Randomized", 100, screen_fail_rate=0.2, discontinuation_rate=0.1)
    assert t.randomized == 100.0
    assert t.screened == pytest.approx(125.0)  # 100 / 0.8
    assert t.completed == pytest.approx(90.0)  # 100 * 0.9


def test_targets_from_completed():
    t = derive_targets("Completed", 100, screen_fail_rate=0.2, discontinuation_rate=0.1)
    assert t.completed == 100.0
    assert t.randomized == pytest.approx(111.1111111111)  # 100 / 0.9
    assert t.screened == pytest.approx(138.8888888888)  # randomized / 0.8


@pytest.mark.parametrize("bad_rate", [-0.1, 1.0, 1.5])
def test_invalid_rates_raise(bad_rate):
    with pytest.raises(ValidationError):
        derive_targets("Randomized", 100, screen_fail_rate=bad_rate, discontinuation_rate=0.1)

    with pytest.raises(ValidationError):
        derive_targets("Randomized", 100, screen_fail_rate=0.1, discontinuation_rate=bad_rate)


@pytest.mark.parametrize("bad_n", [0, -1, 1.2, "100"])
def test_invalid_goal_n_raises(bad_n):
    with pytest.raises(ValidationError):
        derive_targets("Randomized", bad_n, screen_fail_rate=0.1, discontinuation_rate=0.1)


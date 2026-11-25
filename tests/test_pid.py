"""The PID controller."""

import pytest

from custom_components.ember.pid import PID


def test_proportional_only_on_first_update() -> None:
    pid = PID(kp=50, ki=0.01, kd=2000)
    assert pid.update(20, 19, 0) == 50
    assert pid.integral == 0


def test_output_is_clamped() -> None:
    pid = PID(kp=60, ki=0, kd=0)
    assert pid.update(20, 15, 0) == 100
    assert pid.update(20, 25, 1) == 0


def test_integral_accumulates_over_time() -> None:
    pid = PID(kp=0, ki=0.01, kd=0)
    pid.update(20, 19, 0)
    assert pid.update(20, 19, 300) == pytest.approx(3)
    assert pid.update(20, 19, 600) == pytest.approx(6)


def test_no_windup_while_saturated() -> None:
    pid = PID(kp=200, ki=0.01, kd=0)
    pid.update(20, 18, 0)
    pid.update(20, 18, 300)
    assert pid.integral == 0


def test_integral_unwinds_when_error_reverses_at_saturation() -> None:
    pid = PID(kp=0, ki=0.01, kd=0, integral=50)
    pid.update(20, 21, 0)
    pid.update(20, 21, 300)
    assert pid.integral == pytest.approx(47)


def test_derivative_on_measurement() -> None:
    pid = PID(kp=0, ki=0, kd=3000, integral=50)
    pid.update(20, 19, 0)
    # Rising 0.1 K in 300 s brakes by 1 %.
    assert pid.update(20, 19.1, 300) == pytest.approx(49)
    # A setpoint change alone gives no derivative kick.
    assert pid.update(25, 19.1, 600) == pytest.approx(50)


def test_long_gap_is_capped() -> None:
    pid = PID(kp=0, ki=0.01, kd=0)
    pid.update(20, 19, 0)
    pid.update(20, 19, 36000)
    assert pid.integral == pytest.approx(9)


def test_pause_skips_the_paused_time() -> None:
    pid = PID(kp=0, ki=0.01, kd=0)
    pid.update(20, 19, 0)
    pid.pause()
    pid.update(20, 19, 600)
    assert pid.integral == 0


def test_restored_integral_is_clamped() -> None:
    assert PID(1, 1, 1, integral=150).integral == 100


def test_no_windup_while_warming_up_towards_the_target() -> None:
    pid = PID(kp=60, ki=0.01, kd=0, integral=15)
    for step, measurement in enumerate((17.6, 18.0, 18.4, 18.8, 19.2, 19.4)):
        pid.update(20, measurement, step * 300)
    assert pid.integral == 15


def test_no_unwinding_while_cooling_back_after_an_overshoot() -> None:
    pid = PID(kp=30, ki=0.01, kd=0, integral=30)
    for step, measurement in enumerate((21.0, 20.9, 20.8, 20.6)):
        pid.update(20, measurement, step * 300)
    assert pid.integral == 30


def test_integrates_near_the_target_while_approaching() -> None:
    pid = PID(kp=0, ki=0.01, kd=0)
    pid.update(20, 19.6, 0)
    pid.update(20, 19.8, 300)
    assert pid.integral == pytest.approx(0.6)


def test_integrates_when_stuck_away_from_the_target() -> None:
    pid = PID(kp=0, ki=0.01, kd=0)
    pid.update(20, 19.3, 0)
    pid.update(20, 19.3, 300)
    assert pid.integral == pytest.approx(2.1)

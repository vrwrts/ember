"""A PID controller with an output from 0 to 100 %."""

from __future__ import annotations

from .const import INTEGRAL_BAND, PID_MAX_DT

OUTPUT_MIN = 0.0
OUTPUT_MAX = 100.0


class PID:
    """PID on temperature error, with derivative on measurement."""

    def __init__(self, kp: float, ki: float, kd: float, integral: float = 0.0) -> None:
        """Initialise, optionally with an integral restored from before a restart."""
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = min(max(integral, OUTPUT_MIN), OUTPUT_MAX)
        self._last_measurement: float | None = None
        self._last_time: float | None = None

    def update(self, setpoint: float, measurement: float, now: float) -> float:
        """Return the output for a new measurement taken at `now` (seconds)."""
        error = setpoint - measurement
        derivative = 0.0
        dt = 0.0
        if self._last_time is not None and self._last_measurement is not None:
            dt = min(max(now - self._last_time, 0.0), PID_MAX_DT)
            if dt > 0:
                # On measurement rather than error, so a setpoint change gives no kick.
                derivative = -(measurement - self._last_measurement) / dt
        self._last_time = now
        self._last_measurement = measurement

        proportional = self.kp * error
        unclamped = proportional + self.integral + self.kd * derivative
        # Conditional integration: don't wind up further while the output is
        # already saturated in the direction the error pushes it.
        saturated_high = unclamped >= OUTPUT_MAX and error > 0
        saturated_low = unclamped <= OUTPUT_MIN and error < 0
        # Away from the target, only integrate while the room isn't already
        # moving towards it. Integrating through a warm-up or a cool-down
        # winds the integral up for an overshoot, then a dip as it unwinds.
        approaching = error * derivative < 0
        far = abs(error) > INTEGRAL_BAND
        if dt > 0 and not (saturated_high or saturated_low or (far and approaching)):
            self.integral = min(
                max(self.integral + self.ki * error * dt, OUTPUT_MIN), OUTPUT_MAX
            )
        output = proportional + self.integral + self.kd * derivative
        return min(max(output, OUTPUT_MIN), OUTPUT_MAX)

    def pause(self) -> None:
        """Forget the time and measurement, so time spent paused isn't integrated."""
        self._last_time = None
        self._last_measurement = None

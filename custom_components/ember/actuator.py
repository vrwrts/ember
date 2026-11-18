"""What each thermostat type sends to its devices."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
import time as monotonic_time
from typing import Any

from homeassistant.components.climate import ATTR_HVAC_ACTION, HVACAction, HVACMode
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    DEMAND_THRESHOLD,
    NUMBER_TOLERANCE,
    SETTLE_WINDOW,
    TEMP_TOLERANCE,
    VALVE_DEADBAND,
)

_LOGGER = logging.getLogger(__name__)

# How many of our recent contexts to remember; a few cycles' worth of writes.
OWN_CONTEXTS = 32


def _usable(state: State | None) -> bool:
    return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


class Actuator:
    """Sends commands to a thermostat's devices and recognises its own echoes."""

    def __init__(self, hass: HomeAssistant, entity_ids: list[str]) -> None:
        """Initialise."""
        self.hass = hass
        self.entity_ids = entity_ids
        self._ours: deque[str] = deque(maxlen=OWN_CONTEXTS)
        # What we last asked of each entity, and when.
        self._sent: dict[str, tuple[Any, float]] = {}

    async def async_update(self, heating: bool, output: float | None, target: float) -> None:
        """Bring the devices in line with the thermostat."""
        raise NotImplementedError

    async def async_hand_back(self, target: float, heating: bool, manual: bool) -> None:
        """Leave the devices able to regulate on their own while Ember isn't running."""

    def suspend(self) -> None:
        """Stop anything the actuator runs by itself, such as a switch cycle."""

    def calling_for_heat(self) -> bool:
        """Whether the devices are heating right now, judged by their own state."""
        raise NotImplementedError

    def _value(self, state: State) -> Any:
        return state.state

    def _close(self, value: Any, expected: Any) -> bool:
        return value == expected

    def is_manual_change(self, event: Event[EventStateChangedData], manual: bool) -> bool:
        """Whether a state change on one of our entities was made by something else.

        Under manual control any outside change counts, so it restarts the timer
        even when it happens to match what Ember last sent.
        """
        old, new = event.data["old_state"], event.data["new_state"]
        if not (_usable(old) and _usable(new)) or event.context.id in self._ours:
            return False
        value = self._value(new)
        if value == self._value(old):
            return False
        if manual:
            return True
        if (sent := self._sent.get(event.data["entity_id"])) is None:
            return False
        expected, at = sent
        if monotonic_time.monotonic() - at < SETTLE_WINDOW:
            return False
        return not self._close(value, expected)

    async def _call(
        self, domain: str, service: str, entity_id: str, expected: Any, **data: Any
    ) -> None:
        context = Context()
        self._ours.append(context.id)
        self._sent[entity_id] = (expected, monotonic_time.monotonic())
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_id, **data},
                blocking=True,
                context=context,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Calling %s.%s for %s failed: %s", domain, service, entity_id, err)


class SwitchActuator(Actuator):
    """Switches on for a share of each cycle (time-proportional control)."""

    def __init__(
        self, hass: HomeAssistant, switches: list[str], cycle: float, min_time: float
    ) -> None:
        """Initialise with the cycle and minimum on/off time in seconds."""
        super().__init__(hass, switches)
        self.cycle = cycle
        self.min_time = min_time
        self._output = 0.0
        self._unsub_cycle: CALLBACK_TYPE | None = None
        self._unsub_off: CALLBACK_TYPE | None = None

    async def async_update(self, heating: bool, output: float | None, target: float) -> None:
        """Take the new output: from the next cycle, or now if heating starts or stops."""
        self._output = output if heating and output else 0.0
        if self._output <= 0:
            self.suspend()
            await self._async_set(False)
        elif self._unsub_cycle is None:
            self._unsub_cycle = async_track_time_interval(
                self.hass, self._async_cycle, timedelta(seconds=self.cycle), name="ember cycle"
            )
            await self._async_cycle()

    async def _async_cycle(self, *_: Any) -> None:
        on = self._output / 100 * self.cycle
        if on < self.min_time:
            on = 0
        elif self.cycle - on < self.min_time:
            on = self.cycle
        self._cancel_off()
        await self._async_set(on > 0)
        if 0 < on < self.cycle:
            self._unsub_off = async_call_later(self.hass, on, self._async_off)

    async def _async_off(self, *_: Any) -> None:
        self._unsub_off = None
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        for entity_id in self.entity_ids:
            state = self.hass.states.get(entity_id)
            if not _usable(state) or (state.state == STATE_ON) == on:
                continue
            await self._call(
                "switch", "turn_on" if on else "turn_off", entity_id, "on" if on else "off"
            )

    def _cancel_off(self) -> None:
        if self._unsub_off:
            self._unsub_off()
            self._unsub_off = None

    def suspend(self) -> None:
        """Stop the cycle."""
        self._cancel_off()
        if self._unsub_cycle:
            self._unsub_cycle()
            self._unsub_cycle = None

    async def async_hand_back(self, target: float, heating: bool, manual: bool) -> None:
        """Turn off: a plain switch can't regulate, so leaving it on isn't safe."""
        self.suspend()
        await self._async_set(False)

    def calling_for_heat(self) -> bool:
        """Any switch on."""
        return any(
            (state := self.hass.states.get(e)) is not None and state.state == STATE_ON
            for e in self.entity_ids
        )


class _ClimateMixin:
    hass: HomeAssistant

    def _climate_value(self, state: State) -> tuple[str, float | None]:
        return state.state, _float(state.attributes.get(ATTR_TEMPERATURE))

    def _climate_close(
        self, value: tuple[str, float | None], expected: tuple[str, float | None]
    ) -> bool:
        mode, temperature = value
        expected_mode, expected_temperature = expected
        if mode != expected_mode:
            return False
        if mode == HVACMode.OFF or expected_temperature is None or temperature is None:
            return True
        return abs(temperature - expected_temperature) <= TEMP_TOLERANCE

    def _clamp(self, state: State, temperature: float) -> float:
        low = _float(state.attributes.get("min_temp"))
        high = _float(state.attributes.get("max_temp"))
        if low is not None:
            temperature = max(temperature, low)
        if high is not None:
            temperature = min(temperature, high)
        return temperature


class ValveActuator(_ClimateMixin, Actuator):
    """Drives a TRV's valve through its opening and closing degree entities.

    The TRV is kept in heat at its highest setpoint, so its own regulation
    always wants to open and the opening degree decides how far it goes.
    """

    def __init__(self, hass: HomeAssistant, climate: str, opening: str, closing: str) -> None:
        """Initialise."""
        super().__init__(hass, [climate, opening, closing])
        self.climate = climate
        self.opening = opening
        self.closing = closing

    def _value(self, state: State) -> Any:
        if state.entity_id == self.climate:
            return self._climate_value(state)
        return _float(state.state)

    def _close(self, value: Any, expected: Any) -> bool:
        if isinstance(expected, tuple):
            return self._climate_close(value, expected)
        return value is not None and abs(value - expected) <= NUMBER_TOLERANCE

    async def async_update(self, heating: bool, output: float | None, target: float) -> None:
        """Close the valve and turn the TRV off, or pin the TRV and set the valve."""
        await self._async_apply(heating, output or 0.0, force=False)

    async def async_set_position(self, percent: float) -> None:
        """Set the valve as asked by the user, past the deadband."""
        await self._async_apply(percent > 0, percent, force=True)

    async def _async_apply(self, heating: bool, opening: float, force: bool) -> None:
        state = self.hass.states.get(self.climate)
        if not _usable(state):
            return
        if not heating:
            await self._async_write(self.opening, 0, force)
            await self._async_write(self.closing, 100, force)
            if state.state != HVACMode.OFF:
                await self._call(
                    "climate", "set_hvac_mode", self.climate, (HVACMode.OFF, None),
                    hvac_mode=HVACMode.OFF,
                )
            return
        pinned = self._clamp(state, float("inf"))
        if pinned != float("inf") and not self._climate_close(
            self._climate_value(state), (HVACMode.HEAT, pinned)
        ):
            await self._call(
                "climate", "set_temperature", self.climate, (HVACMode.HEAT, pinned),
                temperature=pinned, hvac_mode=HVACMode.HEAT,
            )
        await self._async_write(self.opening, opening, force)
        await self._async_write(self.closing, 100 - opening, force)

    async def _async_write(self, entity_id: str, percent: float, force: bool = False) -> None:
        state = self.hass.states.get(entity_id)
        if not _usable(state):
            return
        low = _float(state.attributes.get("min")) or 0.0
        high = _float(state.attributes.get("max")) or 100.0
        step = _float(state.attributes.get("step")) or 1.0
        value = low + (high - low) * percent / 100
        value = min(max(round(value / step) * step, low), high)
        current = _float(state.state)
        if current is not None and abs(value - current) < NUMBER_TOLERANCE:
            return
        if (
            not force
            and current is not None
            and percent not in (0, 100)
            and abs(value - current) / (high - low) * 100 < VALVE_DEADBAND
        ):
            return
        await self._call("number", "set_value", entity_id, value, value=value)

    async def async_hand_back(self, target: float, heating: bool, manual: bool) -> None:
        """Reset both degrees to their maximum and give the TRV Ember's target."""
        await self._async_write(self.opening, 100, force=True)
        await self._async_write(self.closing, 100, force=True)
        state = self.hass.states.get(self.climate)
        if manual or not _usable(state):
            return
        mode = HVACMode.HEAT if heating else HVACMode.OFF
        temperature = self._clamp(state, target)
        await self._call(
            "climate", "set_temperature", self.climate, (mode, temperature),
            temperature=temperature, hvac_mode=mode,
        )

    def opening_percent(self) -> float | None:
        """How far the valve is open, from its opening degree entity."""
        state = self.hass.states.get(self.opening)
        if not _usable(state) or (value := _float(state.state)) is None:
            return None
        low = _float(state.attributes.get("min")) or 0.0
        high = _float(state.attributes.get("max")) or 100.0
        return (value - low) / (high - low) * 100

    def calling_for_heat(self) -> bool:
        """The TRV is on and its valve open beyond the demand threshold."""
        climate = self.hass.states.get(self.climate)
        if not _usable(climate) or climate.state == HVACMode.OFF:
            return False
        opening = self.opening_percent()
        return opening is not None and opening > DEMAND_THRESHOLD


class PassThroughActuator(_ClimateMixin, Actuator):
    """Forwards the target and mode to climate entities that regulate themselves."""

    def __init__(self, hass: HomeAssistant, climates: list[str]) -> None:
        """Initialise."""
        super().__init__(hass, climates)

    def _value(self, state: State) -> Any:
        return self._climate_value(state)

    def _close(self, value: Any, expected: Any) -> bool:
        return self._climate_close(value, expected)

    async def async_update(self, heating: bool, output: float | None, target: float) -> None:
        """Send the target and mode to each device that doesn't have them already."""
        for entity_id in self.entity_ids:
            state = self.hass.states.get(entity_id)
            if not _usable(state):
                continue
            if not heating:
                if state.state != HVACMode.OFF:
                    await self._call(
                        "climate", "set_hvac_mode", entity_id, (HVACMode.OFF, None),
                        hvac_mode=HVACMode.OFF,
                    )
                continue
            # Clamped per device, as their ranges can differ.
            temperature = self._clamp(state, target)
            if not self._climate_close(self._climate_value(state), (HVACMode.HEAT, temperature)):
                await self._call(
                    "climate", "set_temperature", entity_id, (HVACMode.HEAT, temperature),
                    temperature=temperature, hvac_mode=HVACMode.HEAT,
                )

    def calling_for_heat(self) -> bool:
        """Any device reports it is heating."""
        return any(
            (state := self.hass.states.get(e)) is not None
            and state.attributes.get(ATTR_HVAC_ACTION) == HVACAction.HEATING
            for e in self.entity_ids
        )


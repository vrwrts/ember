"""One thermostat: works out the target and drives its devices."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import time as monotonic_time
from typing import Any

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    STATE_HOME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .actuator import Actuator, PassThroughActuator, SwitchActuator, ValveActuator
from .const import (
    AWAY_SUFFIX,
    CONF_CENTRAL_HEATING,
    CONF_CLOSE_DELAY,
    CONF_CLOSING,
    CONF_CYCLE,
    CONF_ENTITY,
    CONF_FALLBACK_OUTPUT,
    CONF_HEATERS,
    CONF_INTERVAL,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_MIN_SWITCH_TIME,
    CONF_OPEN_DELAY,
    CONF_OPENING,
    CONF_SENSOR,
    CONF_SENSOR_TIMEOUT,
    CONF_TIMEOUT,
    CONF_USE_CENTRAL_CONTROL,
    CONF_USE_CENTRAL_PRESETS,
    CONF_WINDOW,
    DEFAULT_PRESET,
    DOMAIN,
    HAND_BACK_TIMEOUT,
    PRESETS,
    SECTION_CONTROL,
    SECTION_MANUAL,
    SECTION_PRESENCE,
    SECTION_PRESETS,
    SECTION_SAFETY,
    SECTION_WINDOW,
)
from .pid import PID

_LOGGER = logging.getLogger(__name__)

TYPE_SWITCH = "switch"
TYPE_VALVE = "valve"
TYPE_PASS_THROUGH = "pass_through"


class Thermostat:
    """Controller behind one Ember climate entity."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialise from the central settings and the subentry."""
        self.hass = hass
        self.entry = entry
        self.subentry_id = subentry.subentry_id
        self.title = subentry.title
        data = subentry.data
        central = entry.options
        self.presets: dict[str, float] = (
            central[SECTION_PRESETS] if data[CONF_USE_CENTRAL_PRESETS] else data[SECTION_PRESETS]
        )
        self.control: dict[str, float] = (
            central[SECTION_CONTROL] if data[CONF_USE_CENTRAL_CONTROL] else data[SECTION_CONTROL]
        )
        self.presence_entity: str | None = central[SECTION_PRESENCE].get(CONF_ENTITY)
        self.safety = central[SECTION_SAFETY]
        self.window_options = central[SECTION_WINDOW]
        self.manual_timeout = timedelta(minutes=float(central[SECTION_MANUAL][CONF_TIMEOUT]))
        self.sensor: str = data[CONF_SENSOR]
        self.window: str | None = data.get(CONF_WINDOW)
        self.central_heating: bool = data[CONF_CENTRAL_HEATING]

        heaters: list[str] = data[CONF_HEATERS]
        self.actuator: Actuator
        if data.get(CONF_OPENING):
            self.kind = TYPE_VALVE
            self.actuator = ValveActuator(hass, heaters[0], data[CONF_OPENING], data[CONF_CLOSING])
        elif heaters[0].startswith("climate."):
            self.kind = TYPE_PASS_THROUGH
            self.actuator = PassThroughActuator(hass, heaters)
        else:
            self.kind = TYPE_SWITCH
            self.actuator = SwitchActuator(
                hass,
                heaters,
                float(self.control[CONF_CYCLE]) * 60,
                float(self.control[CONF_MIN_SWITCH_TIME]),
            )

        self.hvac_mode = HVACMode.HEAT
        self.preset: str | None = DEFAULT_PRESET
        self.manual_target: float | None = None
        self.manual_until: datetime | None = None
        self.output: float | None = None
        self.window_open = False
        self.stale = False
        self.pid = PID(
            float(self.control[CONF_KP]), float(self.control[CONF_KI]), float(self.control[CONF_KD])
        )
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsub_window: CALLBACK_TYPE | None = None
        self._unsub_manual: CALLBACK_TYPE | None = None
        self._unsub_stop: CALLBACK_TYPE | None = None
        self._stopped = True

    # Stored state

    def restore(self, data: dict[str, Any]) -> None:
        """Take the state stored before a restart."""
        if data.get("hvac_mode") in (HVACMode.OFF, HVACMode.HEAT):
            self.hvac_mode = HVACMode(data["hvac_mode"])
        if data.get("preset") in (*PRESETS, None):
            self.preset = data.get("preset")
        self.manual_target = data.get("manual_target")
        if self.preset is None and self.manual_target is None:
            self.preset = DEFAULT_PRESET
        self.pid.integral = min(max(float(data.get("integral") or 0), 0), 100)
        if until := data.get("manual_until"):
            self.manual_until = dt_util.parse_datetime(until)

    def stored(self) -> dict[str, Any]:
        """State to keep across restarts."""
        return {
            "hvac_mode": self.hvac_mode,
            "preset": self.preset,
            "manual_target": self.manual_target,
            "integral": self.pid.integral,
            "manual_until": self.manual_until.isoformat() if self.manual_until else None,
        }

    # Lifecycle

    async def async_start(self) -> None:
        """Start listening and take control."""
        self._stopped = False
        watch = self._unsubs.append
        watch(async_track_state_change_event(self.hass, self.sensor, self._handle_sensor))
        watch(
            async_track_state_change_event(
                self.hass, self.actuator.entity_ids, self._handle_device
            )
        )
        if self.presence_entity:
            watch(
                async_track_state_change_event(
                    self.hass, self.presence_entity, self._handle_presence
                )
            )
        if self.window:
            watch(async_track_state_change_event(self.hass, self.window, self._handle_window))
            self.window_open = self._window_state_open()
        watch(
            async_track_time_interval(
                self.hass,
                self._async_tick,
                timedelta(seconds=float(self.control[CONF_INTERVAL])),
                name=f"{DOMAIN} {self.title}",
            )
        )
        self._unsub_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_on_stop
        )
        if self.manual_until is not None:
            if self.manual_until > dt_util.utcnow():
                self._schedule_manual_end()
            else:
                self.manual_until = None
        self.hass.async_create_task(self.async_control(), eager_start=False)

    @callback
    def stop(self) -> None:
        """Stop listening; leaves the devices as they are."""
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in (self._unsub_window, self._unsub_manual, self._unsub_stop):
            if unsub:
                unsub()
        self._unsub_window = self._unsub_manual = self._unsub_stop = None
        self.actuator.suspend()
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    async def _async_on_stop(self, _event: Event) -> None:
        self._unsub_stop = None
        await self.async_hand_back()

    async def async_hand_back(self) -> None:
        """Give the devices back their own regulation, for while Ember isn't running."""
        self.actuator.suspend()
        try:
            async with asyncio.timeout(HAND_BACK_TIMEOUT):
                await self.actuator.async_hand_back(
                    self.target, self.hvac_mode == HVACMode.HEAT, self.manual
                )
        except TimeoutError:
            _LOGGER.warning("%s: handing back control timed out", self.title)

    # Listeners for entities

    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call `listener` whenever something shown on the entities changes."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # Derived state

    @property
    def present(self) -> bool:
        """Whether someone is home. Unknown counts as home, so heating never drops by mistake."""
        if not self.presence_entity:
            return True
        state = self.hass.states.get(self.presence_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True
        if self.presence_entity.startswith("zone."):
            try:
                return float(state.state) > 0
            except ValueError:
                return True
        return state.state in (STATE_ON, STATE_HOME)

    @property
    def target(self) -> float:
        """The temperature to reach."""
        if self.preset is None and self.manual_target is not None:
            return self.manual_target
        preset = self.preset or DEFAULT_PRESET
        return float(self.presets[preset if self.present else f"{preset}{AWAY_SUFFIX}"])

    @property
    def current_temperature(self) -> float | None:
        """The room temperature in °C, or None if the sensor has no usable reading."""
        state = self.hass.states.get(self.sensor)
        if state is None:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS)
        if unit != UnitOfTemperature.CELSIUS and unit in TemperatureConverter.VALID_UNITS:
            value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        return value

    def _sensor_stale(self) -> bool:
        state = self.hass.states.get(self.sensor)
        if self.current_temperature is None or state is None:
            return True
        timeout = timedelta(minutes=float(self.safety[CONF_SENSOR_TIMEOUT]))
        return dt_util.utcnow() - state.last_reported > timeout

    @property
    def manual(self) -> bool:
        """Whether the devices are under manual control."""
        return self.manual_until is not None

    @property
    def heating(self) -> bool:
        """Whether the devices are heating right now."""
        return self.actuator.calling_for_heat()

    @property
    def _issue_id(self) -> str:
        return f"stale_sensor_{self.subentry_id}"

    # Changes from the climate entity

    async def async_set_hvac_mode(self, mode: HVACMode) -> None:
        """Set off or heat."""
        self.hvac_mode = mode
        await self._async_user_change()

    async def async_set_preset(self, preset: str | None) -> None:
        """Set a preset; None keeps the current target as a manual temperature."""
        if preset is None:
            self.manual_target = self.target
        self.preset = preset
        await self._async_user_change()

    async def async_set_temperature(self, temperature: float) -> None:
        """Set a temperature by hand, which clears the preset."""
        self.manual_target = temperature
        self.preset = None
        await self._async_user_change()

    async def _async_user_change(self) -> None:
        self._clear_manual()
        await self.async_control()

    async def async_resume(self) -> None:
        """End manual control and take over straight away."""
        self._clear_manual()
        await self.async_control()

    # Control

    async def _async_tick(self, _now: datetime) -> None:
        await self.async_control()

    async def async_control(self) -> None:
        """Work out the output and send it to the devices."""
        async with self._lock:
            if self._stopped:
                return
            if self.manual:
                self._notify()
                return
            heat = self.hvac_mode == HVACMode.HEAT
            target = self.target
            if self.kind == TYPE_PASS_THROUGH:
                await self.actuator.async_update(heat and not self.window_open, None, target)
                self._notify()
                return
            self.stale = heat and self._sensor_stale()
            self._update_issue()
            output = 0.0
            if heat and not self.window_open:
                if self.stale or (current := self.current_temperature) is None:
                    output = float(self.safety[CONF_FALLBACK_OUTPUT])
                    self.pid.pause()
                else:
                    output = self.pid.update(target, current, monotonic_time.monotonic())
            else:
                self.pid.pause()
            self.output = output if heat else None
            await self.actuator.async_update(heat, output, target)
            self._notify()

    def _update_issue(self) -> None:
        if self.stale:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                config_entry_id=self.entry.entry_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="stale_sensor",
                translation_placeholders={"thermostat": self.title, "sensor": self.sensor},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    # Events

    @callback
    def _handle_sensor(self, _event: Event[EventStateChangedData]) -> None:
        # Readings feed the PID on the next tick; only leaving safety acts now.
        if self.stale and not self._sensor_stale():
            self.hass.async_create_task(self.async_control(), eager_start=False)
        self._notify()

    @callback
    def _handle_presence(self, _event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self.async_control(), eager_start=False)

    @callback
    def _handle_device(self, event: Event[EventStateChangedData]) -> None:
        if self.actuator.is_manual_change(event, self.manual):
            self._mark_manual()
        elif (old := event.data["old_state"]) is None or old.state == STATE_UNAVAILABLE:
            # A device that appears or comes back, such as after Zigbee starts
            # later than Ember, gets the current state straight away.
            self.hass.async_create_task(self.async_control(), eager_start=False)
        self._notify()

    def _window_state_open(self) -> bool:
        # Unavailable counts as closed, so a dead contact sensor doesn't stop the heating.
        state = self.hass.states.get(self.window) if self.window else None
        return state is not None and state.state == STATE_ON

    @callback
    def _handle_window(self, _event: Event[EventStateChangedData]) -> None:
        is_open = self._window_state_open()
        if self._unsub_window:
            self._unsub_window()
            self._unsub_window = None
        if is_open == self.window_open:
            return
        delay = float(self.window_options[CONF_OPEN_DELAY if is_open else CONF_CLOSE_DELAY])

        @callback
        def apply(*_: Any) -> None:
            self._unsub_window = None
            self.window_open = is_open
            self.hass.async_create_task(self.async_control(), eager_start=False)

        if delay:
            self._unsub_window = async_call_later(self.hass, delay, apply)
        else:
            apply()

    # Manual control

    @callback
    def _mark_manual(self) -> None:
        if not self.manual:
            _LOGGER.debug("%s: under manual control", self.title)
        self.manual_until = dt_util.utcnow() + self.manual_timeout
        self.actuator.suspend()
        self._schedule_manual_end()

    def _schedule_manual_end(self) -> None:
        if self._unsub_manual:
            self._unsub_manual()

        @callback
        def end(_now: datetime) -> None:
            self._unsub_manual = None
            self.hass.async_create_task(self.async_resume(), eager_start=False)

        assert self.manual_until is not None
        self._unsub_manual = async_track_point_in_utc_time(self.hass, end, self.manual_until)

    def _clear_manual(self) -> None:
        if self._unsub_manual:
            self._unsub_manual()
            self._unsub_manual = None
        if self.manual:
            _LOGGER.debug("%s: back under Ember", self.title)
        self.manual_until = None

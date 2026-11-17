"""Window open detection."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import PASS_THROUGH, SWITCH, Devices, add_thermostat, state

WINDOW = "binary_sensor.window"


async def _wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_open_window_stops_heating_after_delay(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(WINDOW, "off")
    handle = await add_thermostat(hass, SWITCH, window_sensor=WINDOW)
    assert state(hass, "switch.heater").state == "on"

    hass.states.async_set(WINDOW, "on")
    await _wait(hass, freezer, 10)
    assert state(hass, "switch.heater").state == "on"

    await _wait(hass, freezer, 25)
    assert state(hass, "switch.heater").state == "off"
    assert state(hass).state == "heat"
    assert state(hass).attributes["window_open"] is True
    assert state(hass).attributes["hvac_action"] == "idle"
    integral = handle.thermostat.pid.integral

    await _wait(hass, freezer, 3600)
    assert handle.thermostat.pid.integral == integral

    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    assert state(hass, "switch.heater").state == "on"
    assert state(hass).attributes["window_open"] is False


async def test_window_closing_within_delay_does_nothing(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(WINDOW, "off")
    await add_thermostat(hass, SWITCH, window_sensor=WINDOW)
    hass.states.async_set(WINDOW, "on")
    await _wait(hass, freezer, 10)
    hass.states.async_set(WINDOW, "off")
    await _wait(hass, freezer, 60)
    assert devices.heater.calls == ["on"]


async def test_unavailable_window_counts_as_closed(
    hass: HomeAssistant, devices: Devices
) -> None:
    hass.states.async_set(WINDOW, "unavailable")
    await add_thermostat(hass, SWITCH, window_sensor=WINDOW)
    assert state(hass, "switch.heater").state == "on"


async def test_open_window_turns_pass_through_off(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set(WINDOW, "off")
    await add_thermostat(hass, PASS_THROUGH, window_sensor=WINDOW)
    hass.states.async_set(WINDOW, "on")
    await _wait(hass, freezer, 31)
    assert state(hass, "climate.trv").state == "off"
    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    assert state(hass, "climate.trv").state == "heat"

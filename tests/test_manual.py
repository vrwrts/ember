"""Manual control: changes made on the devices themselves."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import (
    CLIMATE,
    PASS_THROUGH,
    SWITCH,
    VALVE,
    Devices,
    add_thermostat,
    call,
    central,
    state,
)

OPTIONS = central(control={"kp": 50, "ki": 0, "kd": 0})


async def _wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_trv_knob_starts_manual_control_until_timeout(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    await _wait(hass, freezer, 60)
    devices.trv.external(native_target_temperature=22)
    await hass.async_block_till_done()
    assert handle.thermostat.manual
    assert state(hass).attributes["manual_control"] is True
    assert state(hass).attributes["manual_until"] is not None

    # Ember leaves the TRV alone on its ticks.
    await _wait(hass, freezer, 301)
    assert state(hass, "climate.trv").attributes["temperature"] == 22

    await _wait(hass, freezer, 3600)
    assert not handle.thermostat.manual
    assert state(hass, "climate.trv").attributes["temperature"] == 35


async def test_echo_within_settle_window_is_not_manual(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    await _wait(hass, freezer, 5)
    devices.trv.external(native_target_temperature=30)
    await hass.async_block_till_done()
    assert not handle.thermostat.manual


async def test_attribute_only_report_is_not_manual(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    await _wait(hass, freezer, 60)
    devices.trv.external(hvac_action="heating")
    await hass.async_block_till_done()
    assert not handle.thermostat.manual


async def test_another_change_restarts_the_timer(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, SWITCH, options=OPTIONS)
    await _wait(hass, freezer, 60)
    devices.heater.external(is_on=False)
    await hass.async_block_till_done()
    first = handle.thermostat.manual_until
    await _wait(hass, freezer, 1800)
    devices.heater.external(is_on=True)
    await hass.async_block_till_done()
    assert handle.thermostat.manual_until > first
    await _wait(hass, freezer, 1800)
    assert handle.thermostat.manual


async def test_switch_cycle_stops_under_manual_control(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    await add_thermostat(hass, SWITCH, options=OPTIONS)
    await _wait(hass, freezer, 60)
    devices.heater.external(is_on=False)
    await hass.async_block_till_done()
    devices.heater.calls.clear()
    await _wait(hass, freezer, 1200)
    assert devices.heater.calls == []


async def test_change_on_ember_ends_manual_control(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, PASS_THROUGH)
    await _wait(hass, freezer, 60)
    devices.trv.external(native_target_temperature=24)
    await hass.async_block_till_done()
    assert handle.thermostat.manual

    await call(hass, "set_preset_mode", preset_mode="comfort")
    assert not handle.thermostat.manual
    assert state(hass, "climate.trv").attributes["temperature"] == 20


async def test_resume_action(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, PASS_THROUGH)
    await _wait(hass, freezer, 60)
    devices.trv.external(hvac_mode="off")
    await hass.async_block_till_done()
    assert handle.thermostat.manual

    await hass.services.async_call("ember", "resume", {"entity_id": CLIMATE}, blocking=True)
    await hass.async_block_till_done()
    assert not handle.thermostat.manual
    assert state(hass, "climate.trv").state == "heat"

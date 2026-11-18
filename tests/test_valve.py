"""Valve thermostats: direct TRV valve control."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import (
    PASS_THROUGH,
    SWITCH,
    VALVE,
    Devices,
    add_thermostat,
    call,
    central,
    set_temperature,
    state,
)

P_ONLY = central(control={"kp": 50, "ki": 0, "kd": 0})


async def test_valve_follows_output_and_trv_is_pinned(
    hass: HomeAssistant, devices: Devices
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    trv = state(hass, "climate.trv")
    assert trv.state == "heat"
    assert trv.attributes["temperature"] == 35
    assert float(state(hass, "number.opening").state) == 50.0
    assert float(state(hass, "number.closing").state) == 50.0
    assert state(hass).attributes["hvac_action"] == "heating"


async def test_small_changes_are_not_written(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    devices.opening.calls.clear()
    set_temperature(hass, 16.04)
    freezer.tick(timedelta(seconds=301))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert devices.opening.calls == []

    set_temperature(hass, 16.5)
    freezer.tick(timedelta(seconds=301))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert devices.opening.calls == [25]
    assert devices.closing.calls[-1] == 75


async def _step(hass: HomeAssistant, freezer: FrozenDateTimeFactory, steps: int = 1) -> None:
    for _ in range(steps):
        freezer.tick(timedelta(seconds=301))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_sustained_small_change_is_written(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    devices.opening.calls.clear()
    set_temperature(hass, 16.04)
    # The first step starts the wait, and 20 minutes later the 48 goes through.
    await _step(hass, freezer, 4)
    assert devices.opening.calls == []
    await _step(hass, freezer)
    assert devices.opening.calls == [48]
    assert devices.closing.calls[-1] == 52


async def test_small_change_that_turns_round_waits_again(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    devices.opening.calls.clear()
    set_temperature(hass, 16.04)
    await _step(hass, freezer, 3)
    set_temperature(hass, 15.96)
    await _step(hass, freezer, 4)
    assert devices.opening.calls == []
    await _step(hass, freezer)
    assert devices.opening.calls == [52]


async def test_manual_control_restarts_the_wait(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=P_ONLY)
    devices.opening.calls.clear()
    set_temperature(hass, 16.04)
    await _step(hass, freezer, 2)
    devices.trv.external(native_target_temperature=22)
    await hass.async_block_till_done()
    assert handle.thermostat.manual
    while handle.thermostat.manual:
        await _step(hass, freezer)
    assert devices.opening.calls == []


async def test_full_close_is_always_written(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    set_temperature(hass, 16.98)
    await add_thermostat(hass, VALVE, options=P_ONLY)
    assert float(state(hass, "number.opening").state) == 1.0
    set_temperature(hass, 18)
    freezer.tick(timedelta(seconds=301))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 0.0
    assert float(state(hass, "number.closing").state) == 100.0
    assert state(hass).attributes["hvac_action"] == "idle"


async def test_off_closes_valve_and_trv(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert float(state(hass, "number.opening").state) == 0.0
    assert float(state(hass, "number.closing").state) == 100.0
    assert state(hass, "climate.trv").state == "off"

    await call(hass, "set_hvac_mode", hvac_mode="heat")
    assert state(hass, "climate.trv").state == "heat"
    assert float(state(hass, "number.opening").state) == 50.0


async def test_scaled_to_number_range(hass: HomeAssistant, devices: Devices) -> None:
    for number in (devices.opening, devices.closing):
        number._attr_native_max_value = 255
        number.async_write_ha_state()
    await add_thermostat(hass, VALVE, options=P_ONLY)
    assert float(state(hass, "number.opening").state) == 128.0
    assert float(state(hass, "number.closing").state) == 128.0


async def test_late_device_is_taken_over(hass: HomeAssistant, devices: Devices) -> None:
    hass.states.async_set("climate.trv", "unavailable")
    await add_thermostat(hass, VALVE, options=P_ONLY)
    devices.trv.async_write_ha_state()
    await hass.async_block_till_done()
    assert state(hass, "climate.trv").attributes["temperature"] == 35


VALVE_ENTITY = "valve.living_room_valve"


async def _set_valve(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(
        "valve", service, {"entity_id": VALVE_ENTITY, **data}, blocking=True
    )
    await hass.async_block_till_done()


async def test_valve_entity_shows_opening_degree(
    hass: HomeAssistant, devices: Devices
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    assert state(hass, VALVE_ENTITY).state == "open"
    assert state(hass, VALVE_ENTITY).attributes["current_position"] == 50

    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert state(hass, VALVE_ENTITY).state == "closed"
    assert state(hass, VALVE_ENTITY).attributes["current_position"] == 0


async def test_setting_valve_starts_manual_control(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=P_ONLY)
    # 52 is within the deadband of Ember's 50, but a position set by hand is written.
    await _set_valve(hass, "set_valve_position", position=52)
    assert float(state(hass, "number.opening").state) == 52.0
    assert float(state(hass, "number.closing").state) == 48.0
    assert state(hass, VALVE_ENTITY).attributes["current_position"] == 52
    assert handle.thermostat.manual
    assert state(hass).attributes["manual_control"] is True

    await _set_valve(hass, "set_valve_position", position=80)
    freezer.tick(timedelta(seconds=301))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 80.0

    freezer.tick(timedelta(minutes=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not handle.thermostat.manual
    assert float(state(hass, "number.opening").state) == 50.0


async def test_closing_valve_turns_trv_off_and_opening_turns_it_on(
    hass: HomeAssistant, devices: Devices
) -> None:
    await add_thermostat(hass, VALVE, options=P_ONLY)
    await _set_valve(hass, "close_valve")
    assert float(state(hass, "number.opening").state) == 0.0
    assert float(state(hass, "number.closing").state) == 100.0
    assert state(hass, "climate.trv").state == "off"

    await _set_valve(hass, "open_valve")
    assert float(state(hass, "number.opening").state) == 100.0
    assert float(state(hass, "number.closing").state) == 0.0
    assert state(hass, "climate.trv").state == "heat"
    assert state(hass, "climate.trv").attributes["temperature"] == 35


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_only_valve_thermostats_have_a_valve_entity(
    hass: HomeAssistant, devices: Devices
) -> None:
    await add_thermostat(hass, VALVE, title="Valve")
    await add_thermostat(hass, SWITCH, title="Switch")
    await add_thermostat(hass, PASS_THROUGH, title="Pass")
    assert hass.states.async_entity_ids("valve") == ["valve.valve_valve"]
    assert [e for e in hass.states.async_entity_ids("sensor") if e.endswith("_output")] == [
        "sensor.switch_output"
    ]
    assert [e for e in hass.states.async_entity_ids("sensor") if e.endswith("_integral")] == [
        "sensor.valve_integral",
        "sensor.switch_integral",
    ]

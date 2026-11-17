"""Valve thermostats: direct TRV valve control."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import VALVE, Devices, add_thermostat, call, central, set_temperature, state

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

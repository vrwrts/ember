"""Switch thermostats: time-proportional control."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import SWITCH, Devices, add_thermostat, call, central, set_temperature, state


async def test_switch_runs_share_of_cycle(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    # Kp only: 1 K below target gives 50 %, so 5 of 10 minutes on.
    options = central(control={"kp": 50, "ki": 0, "kd": 0})
    handle = await add_thermostat(hass, SWITCH, options=options)
    assert handle.thermostat.target == 17
    assert handle.thermostat.output == 50
    assert state(hass, "switch.heater").state == "on"
    assert state(hass).attributes["hvac_action"] == "heating"
    assert state(hass).attributes["output"] == 50

    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "switch.heater").state == "off"
    assert state(hass).attributes["hvac_action"] == "idle"

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "switch.heater").state == "on"


async def test_short_on_time_is_skipped(hass: HomeAssistant, devices: Devices) -> None:
    # 2 % of 10 minutes is 12 s, under the 30 s minimum.
    options = central(control={"kp": 20, "ki": 0, "kd": 0})
    set_temperature(hass, 16.9)
    handle = await add_thermostat(hass, SWITCH, options=options)
    assert handle.thermostat.output == pytest.approx(2)
    assert devices.heater.calls == []


async def test_off_turns_switch_off(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, SWITCH)
    assert state(hass, "switch.heater").state == "on"
    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert state(hass, "switch.heater").state == "off"
    assert state(hass).state == "off"
    assert "output" not in state(hass).attributes


async def test_warm_room_stays_off(hass: HomeAssistant, devices: Devices) -> None:
    set_temperature(hass, 19)
    handle = await add_thermostat(hass, SWITCH)
    assert handle.thermostat.output == 0
    assert devices.heater.calls == []


async def test_multiple_switches(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, {"heaters": ["switch.heater", "switch.plug"]})
    assert state(hass, "switch.heater").state == "on"
    assert state(hass, "switch.plug").state == "on"


OUTPUT = "sensor.living_room_output"


async def test_output_sensor(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(
        hass, SWITCH, options=central(control={"kp": 50, "ki": 0, "kd": 0})
    )
    assert state(hass, OUTPUT).state == "50.0"
    assert state(hass, OUTPUT).attributes["unit_of_measurement"] == "%"

    # Past the settle window, so the change counts as manual.
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    devices.heater.external(is_on=False)
    await hass.async_block_till_done()
    assert handle.thermostat.manual
    assert state(hass, OUTPUT).state == "unknown"

    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert not handle.thermostat.manual
    assert state(hass, OUTPUT).state == "0.0"

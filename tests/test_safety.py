"""Stale temperature sensor."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import async_fire_time_changed

from .conftest import VALVE, Devices, add_thermostat, central, set_temperature, state

OPTIONS = central(control={"kp": 50, "ki": 0, "kd": 0})


async def test_unavailable_sensor_uses_fallback(hass: HomeAssistant, devices: Devices) -> None:
    set_temperature(hass, "unavailable")
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    assert handle.thermostat.output == 20
    assert float(state(hass, "number.opening").state) == 20
    issue = ir.async_get(hass).async_get_issue("ember", f"stale_sensor_{handle.subentry_id}")
    assert issue is not None

    set_temperature(hass, 16)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 50
    assert ir.async_get(hass).async_get_issue("ember", f"stale_sensor_{handle.subentry_id}") is None


async def test_silent_sensor_times_out(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    assert handle.thermostat.output == 50
    freezer.tick(timedelta(minutes=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert handle.thermostat.output == 20
    assert handle.thermostat.stale


async def test_off_raises_no_issue(hass: HomeAssistant, devices: Devices) -> None:
    set_temperature(hass, "unavailable")
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": "climate.living_room", "hvac_mode": "off"},
        blocking=True,
    )
    assert ir.async_get(hass).async_get_issue("ember", f"stale_sensor_{handle.subentry_id}") is None

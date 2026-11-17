"""Pass-through thermostats: the TRV regulates on Ember's target."""

from homeassistant.core import HomeAssistant

from .conftest import PASS_THROUGH, Devices, add_thermostat, call, state


async def test_target_and_mode_are_forwarded(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, PASS_THROUGH)
    assert state(hass, "climate.trv").attributes["temperature"] == 17
    assert handle.thermostat.output is None
    assert "output" not in state(hass).attributes
    # The room sensor is shown, not the TRV's own reading.
    assert state(hass).attributes["current_temperature"] == 16

    await call(hass, "set_temperature", temperature=21.5)
    assert state(hass, "climate.trv").attributes["temperature"] == 21.5
    assert state(hass).attributes["preset_mode"] == "none"

    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert state(hass, "climate.trv").state == "off"


async def test_unchanged_target_is_not_resent(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    devices.trv.calls.clear()
    await call(hass, "set_preset_mode", preset_mode="eco")
    assert devices.trv.calls == []


async def test_hvac_action_is_mirrored(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    assert state(hass).attributes["hvac_action"] == "idle"
    devices.trv.external(hvac_action="heating")
    await hass.async_block_till_done()
    assert state(hass).attributes["hvac_action"] == "heating"


async def test_several_devices_in_one_thermostat(hass: HomeAssistant, devices: Devices) -> None:
    devices.trv2._attr_min_temp = 18
    devices.trv2.async_write_ha_state()
    await add_thermostat(hass, {"heaters": ["climate.trv", "climate.trv2"]})
    # Each device gets the target, clamped to its own range.
    assert state(hass, "climate.trv").attributes["temperature"] == 17
    assert state(hass, "climate.trv2").attributes["temperature"] == 18
    assert state(hass, "binary_sensor.central_heating_demand").state == "off"

    devices.trv2.external(hvac_action="heating")
    await hass.async_block_till_done()
    assert state(hass).attributes["hvac_action"] == "heating"
    assert state(hass, "binary_sensor.central_heating_demand").state == "on"

    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert state(hass, "climate.trv").state == "off"
    assert state(hass, "climate.trv2").state == "off"

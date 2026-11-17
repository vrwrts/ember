"""Central heating demand entities."""

from homeassistant.core import HomeAssistant

from .conftest import PASS_THROUGH, SWITCH, VALVE, Devices, add_thermostat, call, state

DEMAND = "binary_sensor.ember_heating_demand"
COUNT = "sensor.ember_thermostats_calling_for_heat"


async def test_switch_is_not_counted_by_default(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, SWITCH)
    assert state(hass, "switch.heater").state == "on"
    assert state(hass, DEMAND).state == "off"
    assert state(hass, COUNT).state == "0"


async def test_counted_thermostats(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, VALVE)
    assert state(hass, DEMAND).state == "on"
    assert state(hass, COUNT).state == "1"

    await add_thermostat(hass, {"heaters": ["switch.plug"]}, "Bathroom", central_heating=True)
    assert state(hass, COUNT).state == "2"

    await call(hass, "set_hvac_mode", hvac_mode="off")
    assert state(hass, COUNT).state == "1"
    await call(hass, "set_hvac_mode", "climate.bathroom", hvac_mode="off")
    assert state(hass, DEMAND).state == "off"
    assert state(hass, COUNT).state == "0"


async def test_pass_through_follows_device_action(
    hass: HomeAssistant, devices: Devices
) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    assert state(hass, DEMAND).state == "off"
    devices.trv.external(hvac_action="heating")
    await hass.async_block_till_done()
    assert state(hass, DEMAND).state == "on"

"""State across restarts, and handing control back."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import mock_restore_cache_with_extra_data

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


def _restore(hass: HomeAssistant, **extra: object) -> None:
    data = {
        "hvac_mode": "heat",
        "preset": "comfort",
        "manual_target": None,
        "integral": 0,
        "manual_until": None,
        **extra,
    }
    mock_restore_cache_with_extra_data(hass, [(State(CLIMATE, data["hvac_mode"]), data)])


async def test_state_is_restored(hass: HomeAssistant, devices: Devices) -> None:
    _restore(hass, hvac_mode="off", preset=None, manual_target=21.5, integral=42)
    handle = await add_thermostat(hass, SWITCH)
    assert state(hass).state == "off"
    assert state(hass).attributes["temperature"] == 21.5
    assert state(hass).attributes["preset_mode"] == "none"
    assert handle.thermostat.pid.integral == 42


async def test_manual_control_survives_restart(hass: HomeAssistant, devices: Devices) -> None:
    until = dt_util.utcnow() + timedelta(minutes=30)
    _restore(hass, manual_until=until.isoformat())
    handle = await add_thermostat(hass, SWITCH)
    assert handle.thermostat.manual_until == until
    assert devices.heater.calls == []


async def test_expired_manual_control_is_dropped(hass: HomeAssistant, devices: Devices) -> None:
    _restore(hass, manual_until=(dt_util.utcnow() - timedelta(minutes=1)).isoformat())
    handle = await add_thermostat(hass, SWITCH)
    assert not handle.thermostat.manual
    assert devices.heater.calls == ["on"]


async def test_stop_hands_valve_back(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, VALVE, options=central(control={"kp": 50, "ki": 0, "kd": 0}))
    assert state(hass, "climate.trv").attributes["temperature"] == 35
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100
    assert float(state(hass, "number.closing").state) == 100
    assert state(hass, "climate.trv").attributes["temperature"] == 17
    assert state(hass, "climate.trv").state == "heat"


async def test_stop_hands_valve_back_when_off(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, VALVE)
    await call(hass, "set_hvac_mode", hvac_mode="off")
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100
    assert state(hass, "climate.trv").state == "off"


async def test_stop_under_manual_control_keeps_users_setpoint(
    hass: HomeAssistant, devices: Devices
) -> None:
    handle = await add_thermostat(hass, VALVE)
    devices.trv.external(native_target_temperature=22)
    handle.thermostat._mark_manual()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100
    assert state(hass, "climate.trv").attributes["temperature"] == 22


async def test_stop_turns_switches_off(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, SWITCH)
    assert state(hass, "switch.heater").state == "on"
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert state(hass, "switch.heater").state == "off"


async def test_stop_leaves_pass_through_alone(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    devices.trv.calls.clear()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert devices.trv.calls == []


async def test_reload_does_not_hand_back(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, VALVE)
    devices.opening.calls.clear()
    assert await hass.config_entries.async_reload(handle.entry.entry_id)
    await hass.async_block_till_done()
    assert 100 not in devices.opening.calls


async def test_disable_and_remove_hand_back(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, VALVE)
    await hass.config_entries.async_set_disabled_by(
        handle.entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100

    await hass.config_entries.async_set_disabled_by(handle.entry.entry_id, None)
    await hass.async_block_till_done()
    assert state(hass, "climate.trv").attributes["temperature"] == 35
    await hass.config_entries.async_remove(handle.entry.entry_id)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100
    assert state(hass, "climate.trv").attributes["temperature"] == 17


async def test_removing_a_thermostat_hands_it_back(
    hass: HomeAssistant, devices: Devices
) -> None:
    handle = await add_thermostat(hass, VALVE)
    await add_thermostat(hass, SWITCH, "Bathroom")
    hass.config_entries.async_remove_subentry(handle.entry, handle.subentry_id)
    await hass.async_block_till_done()
    assert float(state(hass, "number.opening").state) == 100
    assert state(hass, "climate.trv").attributes["temperature"] == 17
    assert hass.states.get(CLIMATE) is None

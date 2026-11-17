"""Presets, away temperatures and overrides."""

import pytest

from homeassistant.core import HomeAssistant

from .conftest import PASS_THROUGH, Devices, add_thermostat, call, central, state

PRESENCE = central(presence={"entity": "person.anna"})


def trv_target(hass: HomeAssistant) -> float:
    return state(hass, "climate.trv").attributes["temperature"]


async def test_presets_and_icons(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    attributes = state(hass).attributes
    assert attributes["preset_modes"] == ["none", "frost", "eco", "comfort", "boost"]
    assert attributes["preset_mode"] == "eco"
    for preset, expected in (("frost", 7), ("comfort", 20), ("boost", 23), ("eco", 17)):
        await call(hass, "set_preset_mode", preset_mode=preset)
        assert state(hass).attributes["temperature"] == expected
        assert trv_target(hass) == expected


@pytest.mark.parametrize(
    ("entity_id", "home", "away"),
    [
        ("person.anna", "home", "not_home"),
        ("zone.home", "2", "0"),
        ("binary_sensor.occupied", "on", "off"),
    ],
)
async def test_away_temperature_follows_presence(
    hass: HomeAssistant, devices: Devices, entity_id: str, home: str, away: str
) -> None:
    hass.states.async_set(entity_id, home)
    await add_thermostat(hass, PASS_THROUGH, options=central(presence={"entity": entity_id}))
    assert trv_target(hass) == 17

    hass.states.async_set(entity_id, away)
    await hass.async_block_till_done()
    assert trv_target(hass) == 15
    assert state(hass).attributes["preset_mode"] == "eco"

    hass.states.async_set(entity_id, home)
    await hass.async_block_till_done()
    assert trv_target(hass) == 17


async def test_unknown_presence_counts_as_home(hass: HomeAssistant, devices: Devices) -> None:
    hass.states.async_set("person.anna", "unavailable")
    await add_thermostat(hass, PASS_THROUGH, options=PRESENCE)
    assert trv_target(hass) == 17


async def test_manual_temperature_ignores_presence(
    hass: HomeAssistant, devices: Devices
) -> None:
    hass.states.async_set("person.anna", "home")
    await add_thermostat(hass, PASS_THROUGH, options=PRESENCE)
    await call(hass, "set_temperature", temperature=21)
    hass.states.async_set("person.anna", "not_home")
    await hass.async_block_till_done()
    assert trv_target(hass) == 21
    assert state(hass).attributes["preset_mode"] == "none"


async def test_preset_none_keeps_current_target(hass: HomeAssistant, devices: Devices) -> None:
    await add_thermostat(hass, PASS_THROUGH)
    await call(hass, "set_preset_mode", preset_mode="comfort")
    await call(hass, "set_preset_mode", preset_mode="none")
    assert state(hass).attributes["temperature"] == 20


async def test_own_presets_override_central(hass: HomeAssistant, devices: Devices) -> None:
    own = {**central()["presets"], "eco": 21.5}
    await add_thermostat(hass, PASS_THROUGH, use_central_presets=False, presets=own)
    assert trv_target(hass) == 21.5

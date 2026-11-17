"""Config, options and thermostat subentry flows."""

from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ember.const import DEFAULT_CENTRAL, DOMAIN, SUBENTRY_THERMOSTAT

from .conftest import SENSOR, SWITCH, VALVE, Devices, add_thermostat


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ember"
    assert result["options"] == DEFAULT_CENTRAL
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, SWITCH)
    entry = handle.entry
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert {str(key) for key in result["data_schema"].schema} == {
        "presence", "presets", "control", "safety", "window", "manual_control"
    }
    new = {key: dict(value) for key, value in entry.options.items()}
    new["presence"] = {"entity": "person.anna"}
    new["presets"]["eco"] = 21
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # Saving reloads the entry, so the thermostat runs with the new settings.
    assert handle.thermostat.presence_entity == "person.anna"
    assert handle.thermostat.target == 21


async def _start(hass: HomeAssistant, devices: Devices) -> tuple[Any, dict[str, Any]]:
    handle = await add_thermostat(hass, SWITCH)
    result = await hass.config_entries.subentries.async_init(
        (handle.entry.entry_id, SUBENTRY_THERMOSTAT), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return handle, result


@pytest.mark.parametrize(
    ("values", "errors"),
    [
        ({"heaters": []}, {"heaters": "no_heaters"}),
        ({"heaters": ["switch.plug", "climate.trv"]}, {"heaters": "mixed_heaters"}),
        ({"heaters": ["climate.trv"], "opening_degree": "number.opening"}, {"base": "valve_pair"}),
        (
            {
                "heaters": ["switch.plug"],
                "opening_degree": "number.opening",
                "closing_degree": "number.closing",
            },
            {"base": "valve_needs_climate"},
        ),
        (
            {
                "heaters": ["climate.trv", "climate.other"],
                "opening_degree": "number.opening",
                "closing_degree": "number.closing",
            },
            {"base": "valve_needs_climate"},
        ),
    ],
)
async def test_validation(
    hass: HomeAssistant, devices: Devices, values: dict[str, Any], errors: dict[str, str]
) -> None:
    _, result = await _start(hass, devices)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Study", "temperature_sensor": SENSOR, **values}
    )
    assert result["errors"] == errors


async def test_add_switch_thermostat(hass: HomeAssistant, devices: Devices) -> None:
    handle, result = await _start(hass, devices)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Study", "temperature_sensor": SENSOR, "heaters": ["switch.plug"]},
    )
    assert result["step_id"] == "settings"
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults == {
        "central_heating": False,
        "use_central_presets": True,
        "use_central_control": True,
    }
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], defaults)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    subentry = list(handle.entry.subentries.values())[-1]
    assert subentry.title == "Study"
    assert subentry.data == {
        "temperature_sensor": SENSOR,
        "heaters": ["switch.plug"],
        "central_heating": False,
        "use_central_presets": True,
        "use_central_control": True,
    }
    assert hass.states.get("climate.study") is not None


async def test_add_valve_thermostat_with_overrides(
    hass: HomeAssistant, devices: Devices
) -> None:
    handle, result = await _start(hass, devices)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Study", "temperature_sensor": SENSOR, **VALVE}
    )
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults["central_heating"] is True
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**defaults, "use_central_presets": False}
    )
    assert result["step_id"] == "overrides"
    assert {str(k) for k in result["data_schema"].schema} == {"presets"}
    presets = {**DEFAULT_CENTRAL["presets"], "eco": 21.5}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"presets": presets}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    subentry = list(handle.entry.subentries.values())[-1]
    assert subentry.data["presets"] == presets
    assert "control" not in subentry.data
    assert handle.entry.runtime_data[subentry.subentry_id].target == 21.5


async def test_reconfigure_back_to_central(hass: HomeAssistant, devices: Devices) -> None:
    own = {**DEFAULT_CENTRAL["control"], "kp": 10}
    handle = await add_thermostat(
        hass, SWITCH, window_sensor="binary_sensor.window", use_central_control=False, control=own
    )
    result = await hass.config_entries.subentries.async_init(
        (handle.entry.entry_id, SUBENTRY_THERMOSTAT),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": handle.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Lounge", "temperature_sensor": SENSOR, "heaters": ["switch.heater"]},
    )
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults["use_central_control"] is False
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**defaults, "use_central_control": True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    subentry = handle.entry.subentries[handle.subentry_id]
    assert subentry.title == "Lounge"
    assert "control" not in subentry.data
    # Clearing the window sensor field removes it.
    assert "window_sensor" not in subentry.data
    assert handle.thermostat.pid.kp == DEFAULT_CENTRAL["control"]["kp"]

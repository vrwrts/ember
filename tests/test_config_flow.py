"""Config, options and thermostat subentry flows."""

from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ember.const import DEFAULT_CENTRAL, DOMAIN, PRESETS, SUBENTRY_THERMOSTAT

from .conftest import SENSOR, SWITCH, VALVE, Devices, add_thermostat, central


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ember"
    assert result["options"] == DEFAULT_CENTRAL
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


def _preset_form(presets: dict[str, float]) -> dict[str, dict[str, float]]:
    return {p: {"home": presets[p], "away": presets[f"{p}_away"]} for p in PRESETS}


async def test_options_menu(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, SWITCH)
    result = await hass.config_entries.options.async_init(handle.entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "presence",
        "presets",
        "control",
        "safety",
        "window",
        "manual_control",
        "central_heating",
        "save",
    ]


async def _open_page(hass: HomeAssistant, flow_id: str, page: str) -> dict[str, Any]:
    result = await hass.config_entries.options.async_configure(flow_id, {"next_step_id": page})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == page
    return result


async def _submit_page(hass: HomeAssistant, flow_id: str, values: dict[str, Any]) -> None:
    result = await hass.config_entries.options.async_configure(flow_id, values)
    # Back to the menu, not done.
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"


async def _save(hass: HomeAssistant, flow_id: str) -> None:
    result = await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_presets_page(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, SWITCH)
    entry = handle.entry
    flow_id = (await hass.config_entries.options.async_init(entry.entry_id))["flow_id"]
    result = await _open_page(hass, flow_id, "presets")
    assert [str(k) for k in result["data_schema"].schema] == list(PRESETS)

    form = _preset_form(DEFAULT_CENTRAL["presets"])
    form["eco"] = {"home": 18, "away": 14}
    await _submit_page(hass, flow_id, form)
    # Nothing is written until Save.
    assert entry.options["presets"] == DEFAULT_CENTRAL["presets"]

    # Reopening the page shows the change made in this flow.
    result = await _open_page(hass, flow_id, "presets")
    eco = next(v for k, v in result["data_schema"].schema.items() if str(k) == "eco")
    assert {str(k): k.default() for k in eco.schema.schema} == {"home": 18, "away": 14}
    await _submit_page(hass, flow_id, form)

    await _save(hass, flow_id)
    # Stored flat, as before, and the other pages are kept.
    assert entry.options["presets"] == {
        **DEFAULT_CENTRAL["presets"], "eco": 18, "eco_away": 14
    }
    assert entry.options["control"] == DEFAULT_CENTRAL["control"]
    # Saving reloads the entry, so the thermostat runs with the new settings.
    assert handle.thermostat.target == 18


async def test_several_pages_then_save(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, SWITCH)
    flow_id = (await hass.config_entries.options.async_init(handle.entry.entry_id))["flow_id"]
    await _open_page(hass, flow_id, "presence")
    await _submit_page(hass, flow_id, {"entity": "person.anna"})
    await _open_page(hass, flow_id, "manual_control")
    await _submit_page(hass, flow_id, {"timeout": 15})
    await _save(hass, flow_id)
    assert handle.entry.options["presence"] == {"entity": "person.anna"}
    assert handle.entry.options["manual_control"] == {"timeout": 15}
    assert handle.entry.options["presets"] == DEFAULT_CENTRAL["presets"]
    assert handle.thermostat.presence_entity == "person.anna"


async def test_clearing_presence(hass: HomeAssistant, devices: Devices) -> None:
    handle = await add_thermostat(hass, SWITCH, options=central(presence={"entity": "person.anna"}))
    flow_id = (await hass.config_entries.options.async_init(handle.entry.entry_id))["flow_id"]
    await _open_page(hass, flow_id, "presence")
    await _submit_page(hass, flow_id, {})
    await _save(hass, flow_id)
    assert handle.entry.options["presence"] == {}


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
        result["flow_id"],
        {**defaults, "use_central_presets": False, "use_central_control": False},
    )
    assert result["step_id"] == "presets"
    assert [str(k) for k in result["data_schema"].schema] == list(PRESETS)
    form = _preset_form(DEFAULT_CENTRAL["presets"])
    form["eco"]["home"] = 21.5
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], form)

    assert result["step_id"] == "control"
    control = {**DEFAULT_CENTRAL["control"], "kp": 30}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], control)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    subentry = list(handle.entry.subentries.values())[-1]
    assert subentry.data["presets"] == {**DEFAULT_CENTRAL["presets"], "eco": 21.5}
    assert subentry.data["control"] == control
    thermostat = handle.entry.runtime_data[subentry.subentry_id]
    assert thermostat.target == 21.5
    assert thermostat.pid.kp == 30


async def test_own_control_only(hass: HomeAssistant, devices: Devices) -> None:
    _, result = await _start(hass, devices)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Study", "temperature_sensor": SENSOR, "heaters": ["switch.plug"]},
    )
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**defaults, "use_central_control": False}
    )
    assert result["step_id"] == "control"


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

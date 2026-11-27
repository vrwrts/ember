"""The central heating subentry, its checklist and the migration that adds it."""

import orjson
import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ember.const import DOMAIN, SUBENTRY_CENTRAL_HEATING

from .conftest import SWITCH, VALVE, Devices, add_thermostat, central, state, thermostat_data

DEMAND = "binary_sensor.central_heating_demand"
COUNT = "sensor.central_heating_thermostats_calling_for_heat"


def _central_heating_id(entry: MockConfigEntry) -> str:
    return entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING)[0].subentry_id


async def test_new_entry_has_central_heating(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    entry = result["result"]
    [subentry] = entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING)
    assert subentry.title == "Central heating"
    assert entry.minor_version == 3


async def test_demand_entities_belong_to_the_subentry(
    hass: HomeAssistant, devices: Devices
) -> None:
    handle = await add_thermostat(hass, VALVE)
    subentry_id = _central_heating_id(handle.entry)
    entity = er.async_get(hass).async_get(DEMAND)
    assert entity is not None
    assert entity.config_subentry_id == subentry_id
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert device.name == "Central heating"
    assert device.identifiers == {(DOMAIN, subentry_id)}
    assert state(hass, DEMAND).attributes["friendly_name"] == "Central heating Demand"


async def _checklist(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "central_heating"}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def _tick_and_save(hass: HomeAssistant, result: dict, ticked: list[str]) -> None:
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"thermostats": ticked}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_checklist_sets_each_thermostats_toggle(
    hass: HomeAssistant, devices: Devices
) -> None:
    valve = await add_thermostat(hass, VALVE)
    switch = await add_thermostat(hass, SWITCH, "Bathroom")
    assert state(hass, COUNT).state == "1"

    result = await _checklist(hass, valve.entry)
    [field] = result["data_schema"].schema
    # Ticked: the thermostats that count now.
    assert field.default() == [valve.subentry_id]
    await _tick_and_save(hass, result, [switch.subentry_id])

    subentries = valve.entry.subentries
    assert subentries[valve.subentry_id].data["central_heating"] is False
    assert subentries[switch.subentry_id].data["central_heating"] is True
    # The switch heats in the 16 °C test room; the valve no longer counts.
    assert state(hass, COUNT).state == "1"
    assert switch.thermostat.central_heating
    assert not valve.thermostat.central_heating


async def test_unticking_everything(hass: HomeAssistant, devices: Devices) -> None:
    valve = await add_thermostat(hass, VALVE)
    result = await _checklist(hass, valve.entry)
    await _tick_and_save(hass, result, [])
    assert valve.entry.subentries[valve.subentry_id].data["central_heating"] is False
    assert state(hass, DEMAND).state == "off"


async def test_checklist_is_kept_until_save(hass: HomeAssistant, devices: Devices) -> None:
    valve = await add_thermostat(hass, VALVE)
    result = await _checklist(hass, valve.entry)
    await hass.config_entries.options.async_configure(result["flow_id"], {"thermostats": []})
    assert valve.entry.subentries[valve.subentry_id].data["central_heating"] is True


def _menu(entry: MockConfigEntry) -> list[str]:
    return list(entry.supported_subentry_types)


async def test_no_checklist_page_without_thermostats(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ember",
        minor_version=2,
        options=central(),
        subentries_data=[
            {
                "data": {},
                "subentry_type": SUBENTRY_CENTRAL_HEATING,
                "title": "Central heating",
                "unique_id": SUBENTRY_CENTRAL_HEATING,
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "central_heating" not in result["menu_options"]


async def test_add_button_only_without_central_heating(
    hass: HomeAssistant, devices: Devices
) -> None:
    handle = await add_thermostat(hass, VALVE)
    entry = handle.entry
    assert _menu(entry) == ["thermostat"]

    hass.config_entries.async_remove_subentry(entry, _central_heating_id(entry))
    await hass.async_block_till_done()
    assert hass.states.get(DEMAND) is None
    assert _menu(entry) == ["thermostat", "central_heating"]
    # The frontend gets the entry again with the new types.
    assert b"central_heating" in orjson.dumps(entry.as_json_fragment)
    # With no central heating, the settings have no checklist page.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "central_heating" not in result["menu_options"]
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    await hass.async_block_till_done()

    # Deleting it stays deleted across a reload.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert not entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CENTRAL_HEATING), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert state(hass, DEMAND).state == "on"
    assert _menu(entry) == ["thermostat"]


async def test_migration_keeps_entity_ids(
    hass: HomeAssistant, devices: Devices, caplog: pytest.LogCaptureFixture
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ember",
        minor_version=1,
        options=central(),
        subentries_data=[
            {
                "data": thermostat_data(VALVE),
                "subentry_type": "thermostat",
                "title": "Living room",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    # How 1.1.0 left things: an "Ember" device on the entry itself.
    devices_registry = dr.async_get(hass)
    old = devices_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Ember"
    )
    entities = er.async_get(hass)
    for platform, key, entity_id in (
        ("binary_sensor", "heating_demand", "binary_sensor.ember_heating_demand"),
        ("sensor", "calling_for_heat", "sensor.ember_thermostats_calling_for_heat"),
    ):
        entities.async_get_or_create(
            platform,
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            device_id=old.id,
            suggested_object_id=entity_id.split(".")[1],
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 3
    subentry_id = _central_heating_id(entry)
    assert devices_registry.async_get(old.id) is None
    for entity_id in ("binary_sensor.ember_heating_demand",
                      "sensor.ember_thermostats_calling_for_heat"):
        entity = entities.async_get(entity_id)
        assert entity is not None
        assert entity.config_subentry_id == subentry_id
        device = devices_registry.async_get(entity.device_id)
        assert device is not None
        assert device.identifiers == {(DOMAIN, subentry_id)}
    assert state(hass, "binary_sensor.ember_heating_demand").state == "on"
    assert "deprecated" not in caplog.text

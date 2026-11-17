"""Ember: heating control from central presets and an external sensor."""

from __future__ import annotations

import asyncio

import probatio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, SERVICE_RESUME, SUBENTRY_THERMOSTAT
from .thermostat import Thermostat

type EmberConfigEntry = ConfigEntry[dict[str, Thermostat]]

PLATFORMS = [Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Thermostats of an unloaded entry, kept until we know whether it's being
# removed, so removal can hand their devices back.
DATA_UNLOADED: HassKey[dict[str, dict[str, Thermostat]]] = HassKey(f"{DOMAIN}_unloaded")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""

    async def resume(call: ServiceCall) -> None:
        selection = TargetSelection(call.data)
        if not selection.has_any_target:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="resume_needs_target"
            )
        selected = async_extract_referenced_entity_ids(hass, selection, expand_group=False)
        registry = er.async_get(hass)
        subentries = {
            entry.config_subentry_id
            for entity_id in selected.referenced | selected.indirectly_referenced
            if (entry := registry.async_get(entity_id)) is not None and entry.platform == DOMAIN
        }
        await asyncio.gather(
            *(
                thermostat.async_resume()
                for entry in hass.config_entries.async_loaded_entries(DOMAIN)
                for subentry_id, thermostat in entry.runtime_data.items()
                if subentry_id in subentries
            )
        )

    hass.services.async_register(
        DOMAIN, SERVICE_RESUME, resume, probatio.Schema(cv.ENTITY_SERVICE_FIELDS)
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EmberConfigEntry) -> bool:
    """Create a thermostat per subentry and set up the entities."""
    hass.data.setdefault(DATA_UNLOADED, {}).pop(entry.entry_id, None)
    entry.runtime_data = {
        subentry.subentry_id: Thermostat(hass, entry, subentry)
        for subentry in entry.get_subentries_of_type(SUBENTRY_THERMOSTAT)
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Adding, changing or removing a thermostat updates the entry without reloading it.
    entry.async_on_unload(entry.add_update_listener(_async_update))
    return True


async def _async_update(hass: HomeAssistant, entry: EmberConfigEntry) -> None:
    removed = [t for sid, t in entry.runtime_data.items() if sid not in entry.subentries]
    await asyncio.gather(*(t.async_hand_back() for t in removed))
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EmberConfigEntry) -> bool:
    """Stop every thermostat; hand the devices back if Ember is being disabled."""
    if entry.disabled_by is not None:
        await asyncio.gather(*(t.async_hand_back() for t in entry.runtime_data.values()))
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data.setdefault(DATA_UNLOADED, {})[entry.entry_id] = entry.runtime_data
    return True


async def async_remove_entry(hass: HomeAssistant, entry: EmberConfigEntry) -> None:
    """Hand the devices back when Ember is removed."""
    if thermostats := hass.data.get(DATA_UNLOADED, {}).pop(entry.entry_id, None):
        await asyncio.gather(*(t.async_hand_back() for t in thermostats.values()))

"""Ember: heating control from central presets and an external sensor."""

from __future__ import annotations

import asyncio
import logging

import probatio

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import (
    CENTRAL_HEATING_SUBENTRY,
    DEFAULT_CENTRAL,
    DOMAIN,
    SECTION_SUPPLY,
    SERVICE_RESUME,
    SUBENTRY_CENTRAL_HEATING,
    SUBENTRY_THERMOSTAT,
)
from .thermostat import Thermostat

_LOGGER = logging.getLogger(__name__)

type EmberConfigEntry = ConfigEntry[dict[str, Thermostat]]

PLATFORMS = [Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.SENSOR, Platform.VALVE]

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


async def async_migrate_entry(hass: HomeAssistant, entry: EmberConfigEntry) -> bool:
    """Bring entries from older versions up to date."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        if not entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
            hass.config_entries.async_add_subentry(
                entry, ConfigSubentry(**CENTRAL_HEATING_SUBENTRY)
            )
        # The demand entities lived on a device of the entry itself. Detach them
        # before removing it, so they keep their entity ids and move to the
        # subentry's device on setup.
        devices = dr.async_get(hass)
        if device := devices.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        ):
            entities = er.async_get(hass)
            for entity in er.async_entries_for_device(entities, device.id, True):
                entities.async_update_entity(entity.entity_id, device_id=None)
            devices.async_remove_device(device.id)
        hass.config_entries.async_update_entry(entry, minor_version=2)
        _reset_subentry_types(entry)
    if entry.minor_version < 3:
        hass.config_entries.async_update_entry(
            entry,
            options={SECTION_SUPPLY: DEFAULT_CENTRAL[SECTION_SUPPLY], **entry.options},
            minor_version=3,
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


def _reset_subentry_types(entry: EmberConfigEntry) -> None:
    """Make HA ask again which subentry types to offer.

    HA caches ConfigEntry.supported_subentry_types until restart, but the
    central heating type is only offered while there is none. This is the only
    place that touches that private cache.
    """
    if not hasattr(entry, "_supported_subentry_types"):
        _LOGGER.warning(
            "Home Assistant changed how it caches subentry types; the Add central "
            "heating button may be out of date until a restart"
        )
        return
    object.__setattr__(entry, "_supported_subentry_types", None)


async def _async_update(hass: HomeAssistant, entry: EmberConfigEntry) -> None:
    # The reload below changes the entry's state, which sends the frontend the
    # entry again, now with the fresh subentry types.
    _reset_subentry_types(entry)
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

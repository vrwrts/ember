"""Shared base for the central heating demand entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import EmberConfigEntry
from .const import DOMAIN


class DemandEntity(Entity):
    """Counts thermostats in central heating that are heating right now."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: EmberConfigEntry, key: str) -> None:
        """Initialise."""
        self.entry = entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Ember")

    @property
    def calling(self) -> int:
        """How many counted thermostats call for heat."""
        return sum(
            t.central_heating and t.heating for t in self.entry.runtime_data.values()
        )

    async def async_added_to_hass(self) -> None:
        """Follow every thermostat."""
        for thermostat in self.entry.runtime_data.values():
            self.async_on_remove(thermostat.add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        self._refresh()
        if self.hass is not None:
            self.async_write_ha_state()

    def _refresh(self) -> None:
        raise NotImplementedError

"""The valve of each valve thermostat, which can be set by hand."""

from __future__ import annotations

from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmberConfigEntry
from .actuator import ValveActuator
from .const import DOMAIN
from .thermostat import TYPE_VALVE, Thermostat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmberConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a valve entity to each valve thermostat."""
    for subentry_id, thermostat in entry.runtime_data.items():
        if thermostat.kind == TYPE_VALVE:
            async_add_entities([EmberValve(thermostat)], config_subentry_id=subentry_id)


class EmberValve(ValveEntity):
    """Shows the TRV's opening; setting it puts the thermostat under manual control."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "valve"
    _attr_reports_position = True
    _attr_supported_features = (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE | ValveEntityFeature.SET_POSITION
    )

    def __init__(self, thermostat: Thermostat) -> None:
        """Initialise."""
        assert isinstance(thermostat.actuator, ValveActuator)
        self.thermostat = thermostat
        self.actuator = thermostat.actuator
        self._attr_unique_id = f"{thermostat.subentry_id}_valve"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, thermostat.subentry_id)})
        self._refresh()

    async def async_added_to_hass(self) -> None:
        """Follow the thermostat."""
        self.async_on_remove(self.thermostat.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        opening = self.actuator.opening_percent()
        self._attr_current_valve_position = None if opening is None else round(opening)

    async def async_open_valve(self) -> None:
        """Open fully."""
        await self.thermostat.async_set_valve_position(100)

    async def async_close_valve(self) -> None:
        """Close and turn the TRV off."""
        await self.thermostat.async_set_valve_position(0)

    async def async_set_valve_position(self, position: int) -> None:
        """Open to `position` percent."""
        await self.thermostat.async_set_valve_position(position)

"""How many thermostats in central heating call for heat, and each switch thermostat's output."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmberConfigEntry
from .const import DOMAIN, SUBENTRY_CENTRAL_HEATING
from .demand import DemandEntity
from .thermostat import TYPE_SWITCH, Thermostat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmberConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the central heating's demand count and each switch thermostat's output."""
    for subentry in entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
        async_add_entities(
            [CallingForHeat(entry, subentry, "calling_for_heat")],
            config_subentry_id=subentry.subentry_id,
        )
    for subentry_id, thermostat in entry.runtime_data.items():
        if thermostat.kind == TYPE_SWITCH:
            async_add_entities([Output(thermostat)], config_subentry_id=subentry_id)


class CallingForHeat(DemandEntity, SensorEntity):
    """Number of thermostats in central heating that call for heat."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def _refresh(self) -> None:
        self._attr_native_value = self.calling


class Output(SensorEntity):
    """A switch thermostat's output: the share of each cycle the switches are on."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "output"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, thermostat: Thermostat) -> None:
        """Initialise."""
        self.thermostat = thermostat
        self._attr_unique_id = f"{thermostat.subentry_id}_output"
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
        # Under manual control Ember isn't driving the switches, so it has no output.
        t = self.thermostat
        self._attr_native_value = None if t.manual else round(t.output or 0.0, 1)

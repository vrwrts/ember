"""Central heating demand: on while any counted thermostat heats."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmberConfigEntry
from .const import SUBENTRY_CENTRAL_HEATING
from .demand import DemandEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmberConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the demand sensor to the central heating, if there is one."""
    for subentry in entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
        async_add_entities(
            [HeatingDemand(entry, subentry, "heating_demand")],
            config_subentry_id=subentry.subentry_id,
        )


class HeatingDemand(DemandEntity, BinarySensorEntity):
    """On while any thermostat in central heating calls for heat."""

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def _refresh(self) -> None:
        self._attr_is_on = self.calling > 0

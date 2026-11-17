"""How many thermostats in central heating call for heat."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
    """Add the count of calling thermostats to the central heating, if there is one."""
    for subentry in entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
        async_add_entities(
            [CallingForHeat(entry, subentry, "calling_for_heat")],
            config_subentry_id=subentry.subentry_id,
        )


class CallingForHeat(DemandEntity, SensorEntity):
    """Number of thermostats in central heating that call for heat."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def _refresh(self) -> None:
        self._attr_native_value = self.calling

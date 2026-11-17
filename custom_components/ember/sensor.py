"""How many thermostats in central heating call for heat."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmberConfigEntry
from .demand import DemandEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmberConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the count of thermostats calling for heat."""
    async_add_entities([CallingForHeat(entry, "calling_for_heat")])


class CallingForHeat(DemandEntity, SensorEntity):
    """Number of thermostats in central heating that call for heat."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def _refresh(self) -> None:
        self._attr_native_value = self.calling

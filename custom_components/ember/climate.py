"""The climate entity of each Ember thermostat."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity

from . import EmberConfigEntry
from .const import DOMAIN, MAX_TEMP, MIN_TEMP, PRESETS, TEMP_STEP
from .thermostat import Thermostat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EmberConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one climate entity per thermostat subentry."""
    for subentry_id, thermostat in entry.runtime_data.items():
        async_add_entities([EmberClimate(thermostat)], config_subentry_id=subentry_id)


class EmberClimate(ClimateEntity, RestoreEntity):
    """Shows and controls one thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_translation_key = "thermostat"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_NONE, *PRESETS]
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, thermostat: Thermostat) -> None:
        """Initialise."""
        self.thermostat = thermostat
        self._attr_unique_id = thermostat.subentry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, thermostat.subentry_id)}, name=thermostat.title
        )
        self._refresh()

    async def async_added_to_hass(self) -> None:
        """Restore the last state and start the thermostat."""
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None:
            self.thermostat.restore(extra.as_dict())
        self.async_on_remove(self.thermostat.add_listener(self._handle_update))
        self.async_on_remove(self.thermostat.stop)
        await self.thermostat.async_start()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """The thermostat's state to restore after a restart."""
        return RestoredExtraData(self.thermostat.stored())

    @callback
    def _handle_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        t = self.thermostat
        self._attr_hvac_mode = t.hvac_mode
        self._attr_preset_mode = t.preset or PRESET_NONE
        self._attr_native_target_temperature = t.target
        self._attr_native_current_temperature = t.current_temperature
        if t.hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
        else:
            self._attr_hvac_action = HVACAction.HEATING if t.heating else HVACAction.IDLE
        attributes: dict[str, Any] = {
            "manual_control": t.manual,
            "manual_until": t.manual_until.isoformat() if t.manual_until else None,
            "window_open": t.window_open,
        }
        if t.output is not None:
            attributes["output"] = round(t.output, 1)
        self._attr_extra_state_attributes = attributes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set off or heat."""
        await self.thermostat.async_set_hvac_mode(hvac_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a preset, or none to keep the current temperature."""
        await self.thermostat.async_set_preset(None if preset_mode == PRESET_NONE else preset_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a temperature by hand."""
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            self.thermostat.hvac_mode = HVACMode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.thermostat.async_set_temperature(float(temperature))
        elif hvac_mode is not None:
            await self.thermostat.async_set_hvac_mode(HVACMode(hvac_mode))

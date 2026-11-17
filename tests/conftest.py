"""Fixtures for Ember tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry, setup_test_component_platform

from custom_components.ember.const import (
    CENTRAL_HEATING_SUBENTRY,
    CONF_CENTRAL_HEATING,
    CONF_HEATERS,
    CONF_SENSOR,
    CONF_USE_CENTRAL_CONTROL,
    CONF_USE_CENTRAL_PRESETS,
    DEFAULT_CENTRAL,
    DOMAIN,
    SUBENTRY_THERMOSTAT,
)
from custom_components.ember.thermostat import Thermostat

SENSOR = "sensor.room"


class _External:
    """Changes made outside Home Assistant, with a context that isn't Ember's."""

    def external(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            setattr(self, f"_attr_{key}", value)
        self.async_set_context(Context())
        self.async_write_ha_state()


class MockSwitch(_External, SwitchEntity):
    """A switch that records its calls."""

    _attr_should_poll = False

    def __init__(self, name: str) -> None:
        """Initialise."""
        self._attr_name = name
        self._attr_unique_id = name
        self._attr_is_on = False
        self.calls: list[str] = []

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        self.calls.append("on")
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        self.calls.append("off")
        self._attr_is_on = False
        self.async_write_ha_state()


class MockTRV(_External, ClimateEntity):
    """A TRV that applies what it is sent."""

    _attr_should_poll = False
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 4
    _attr_max_temp = 35
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, name: str) -> None:
        """Initialise."""
        self._attr_name = name
        self._attr_unique_id = name
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_action = HVACAction.IDLE
        self._attr_native_target_temperature = 18
        self.calls: list[dict[str, Any]] = []

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set temperature and maybe mode."""
        self.calls.append(kwargs)
        self._attr_native_target_temperature = kwargs[ATTR_TEMPERATURE]
        if "hvac_mode" in kwargs:
            self._attr_hvac_mode = kwargs["hvac_mode"]
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set mode."""
        self.calls.append({"hvac_mode": hvac_mode})
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()


class MockNumber(_External, NumberEntity):
    """A valve degree entity."""

    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1

    def __init__(self, name: str, value: float = 100) -> None:
        """Initialise."""
        self._attr_name = name
        self._attr_unique_id = name
        self._attr_native_value = value
        self.calls: list[float] = []

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self.calls.append(value)
        self._attr_native_value = value
        self.async_write_ha_state()


@dataclass
class Devices:
    """Every mock device, by role."""

    heater: MockSwitch
    plug: MockSwitch
    trv: MockTRV
    trv2: MockTRV
    opening: MockNumber
    closing: MockNumber


@pytest.fixture
async def devices(hass: HomeAssistant) -> Devices:
    """Set up the mock devices and a room sensor at 16 °C, 1 K below Eco."""
    d = Devices(
        MockSwitch("heater"),
        MockSwitch("plug"),
        MockTRV("trv"),
        MockTRV("trv2"),
        MockNumber("opening"),
        MockNumber("closing"),
    )
    setup_test_component_platform(hass, "switch", [d.heater, d.plug])
    setup_test_component_platform(hass, "climate", [d.trv, d.trv2])
    setup_test_component_platform(hass, "number", [d.opening, d.closing])
    for domain in ("switch", "climate", "number"):
        assert await async_setup_component(hass, domain, {domain: {"platform": "test"}})
    set_temperature(hass, 16)
    await hass.async_block_till_done()
    return d


def set_temperature(hass: HomeAssistant, value: float | str) -> None:
    """Report a room temperature."""
    hass.states.async_set(
        SENSOR, str(value), {"unit_of_measurement": "°C", "device_class": "temperature"}
    )


SWITCH = {CONF_HEATERS: ["switch.heater"]}
VALVE = {
    CONF_HEATERS: ["climate.trv"],
    "opening_degree": "number.opening",
    "closing_degree": "number.closing",
}
PASS_THROUGH = {CONF_HEATERS: ["climate.trv"]}


def thermostat_data(heaters: dict[str, Any], **data: Any) -> dict[str, Any]:
    """A subentry's data with the usual defaults."""
    return {
        CONF_SENSOR: SENSOR,
        CONF_CENTRAL_HEATING: heaters[CONF_HEATERS][0].startswith("climate."),
        CONF_USE_CENTRAL_PRESETS: True,
        CONF_USE_CENTRAL_CONTROL: True,
        **heaters,
        **data,
    }


def central(**sections: dict[str, Any]) -> dict[str, Any]:
    """The central options with some values replaced."""
    options = deepcopy(DEFAULT_CENTRAL)
    for name, values in sections.items():
        options[name] = {**options[name], **values}
    return options


@dataclass
class Handle:
    """A thermostat subentry; looks up the running Thermostat, which a reload replaces."""

    entry: MockConfigEntry
    subentry_id: str

    @property
    def thermostat(self) -> Thermostat:
        """The running thermostat."""
        return self.entry.runtime_data[self.subentry_id]


async def add_thermostat(
    hass: HomeAssistant,
    heaters: dict[str, Any],
    title: str = "Living room",
    options: dict[str, Any] | None = None,
    **data: Any,
) -> Handle:
    """Add a thermostat to the Ember entry, creating and loading the entry if needed."""
    subentry_data = thermostat_data(heaters, **data)
    if entries := hass.config_entries.async_entries(DOMAIN):
        entry = entries[0]
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(subentry_data),
                subentry_type=SUBENTRY_THERMOSTAT,
                title=title,
                unique_id=None,
            ),
        )
    else:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Ember",
            minor_version=2,
            options=options or central(),
            subentries_data=[
                CENTRAL_HEATING_SUBENTRY,
                {
                    "data": subentry_data,
                    "subentry_type": SUBENTRY_THERMOSTAT,
                    "title": title,
                    "unique_id": None,
                }
            ],
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return Handle(entry, entry.get_subentries_of_type(SUBENTRY_THERMOSTAT)[-1].subentry_id)


CLIMATE = "climate.living_room"


def state(hass: HomeAssistant, entity_id: str = CLIMATE) -> State:
    """A state that must exist."""
    result = hass.states.get(entity_id)
    assert result is not None, entity_id
    return result


async def call(hass: HomeAssistant, service: str, entity_id: str = CLIMATE, **data: Any) -> None:
    """Call a climate service and wait for what it causes."""
    await hass.services.async_call(
        "climate", service, {"entity_id": entity_id, **data}, blocking=True
    )
    await hass.async_block_till_done()

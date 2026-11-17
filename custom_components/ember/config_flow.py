"""Config, options and thermostat subentry flows for Ember."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    AWAY_SUFFIX,
    CENTRAL_HEATING_SUBENTRY,
    CONF_CENTRAL_HEATING,
    CONF_CLOSE_DELAY,
    CONF_CLOSING,
    CONF_CYCLE,
    CONF_ENTITY,
    CONF_FALLBACK_OUTPUT,
    CONF_HEATERS,
    CONF_INTERVAL,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_MIN_SWITCH_TIME,
    CONF_OPEN_DELAY,
    CONF_OPENING,
    CONF_SENSOR,
    CONF_SENSOR_TIMEOUT,
    CONF_THERMOSTATS,
    CONF_TIMEOUT,
    CONF_USE_CENTRAL_CONTROL,
    CONF_USE_CENTRAL_PRESETS,
    CONF_WINDOW,
    DEFAULT_CENTRAL,
    DOMAIN,
    MAX_TEMP,
    MIN_TEMP,
    PRESETS,
    SECTION_CONTROL,
    SECTION_MANUAL,
    SECTION_PRESENCE,
    SECTION_PRESETS,
    SECTION_SAFETY,
    SECTION_WINDOW,
    SUBENTRY_CENTRAL_HEATING,
    SUBENTRY_THERMOSTAT,
    TEMP_STEP,
)

PRESENCE_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        filter=[
            {"domain": "person"},
            {"domain": "zone"},
            {"domain": "binary_sensor", "device_class": ["occupancy", "presence"]},
        ]
    )
)
SENSOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="temperature")
)
HEATERS_SELECTOR = EntitySelector(EntitySelectorConfig(domain=["switch", "climate"], multiple=True))
NUMBER_SELECTOR = EntitySelector(EntitySelectorConfig(domain="number"))
WINDOW_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain="binary_sensor", device_class=["window", "door", "opening"]
    )
)


def _number(low: float, high: float, unit: str | None, step: float | str = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low, max=high, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX
        )
    )


TEMPERATURE = _number(MIN_TEMP, MAX_TEMP, "°C", TEMP_STEP)


def _optional_entity(key: str, values: dict[str, Any]) -> probatio.Optional:
    # Suggested rather than default, so the field can be cleared.
    return probatio.Optional(key, description={"suggested_value": values.get(key)})


# Form-only keys: presets are stored flat (comfort, comfort_away) but shown
# as a section per preset with a home and an away field.
FORM_HOME = "home"
FORM_AWAY = "away"


def _presets_schema(p: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(preset): section(
                probatio.Schema(
                    {
                        probatio.Required(FORM_HOME, default=p[preset]): TEMPERATURE,
                        probatio.Required(
                            FORM_AWAY, default=p[f"{preset}{AWAY_SUFFIX}"]
                        ): TEMPERATURE,
                    }
                )
            )
            for preset in PRESETS
        }
    )


def _presets_from_form(user_input: dict[str, Any]) -> dict[str, float]:
    presets: dict[str, float] = {}
    for preset in PRESETS:
        presets[preset] = user_input[preset][FORM_HOME]
        presets[f"{preset}{AWAY_SUFFIX}"] = user_input[preset][FORM_AWAY]
    return presets


def _control_schema(c: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(CONF_KP, default=c[CONF_KP]): _number(0, 1000, "%/K", "any"),
            probatio.Required(CONF_KI, default=c[CONF_KI]): _number(0, 10, "%/(K·s)", "any"),
            probatio.Required(CONF_KD, default=c[CONF_KD]): _number(0, 100000, "%·s/K", "any"),
            probatio.Required(CONF_INTERVAL, default=c[CONF_INTERVAL]): _number(30, 3600, "s"),
            probatio.Required(CONF_CYCLE, default=c[CONF_CYCLE]): _number(1, 120, "min"),
            probatio.Required(
                CONF_MIN_SWITCH_TIME, default=c[CONF_MIN_SWITCH_TIME]
            ): _number(0, 600, "s"),
        }
    )


def _presence_schema(p: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema({_optional_entity(CONF_ENTITY, p): PRESENCE_SELECTOR})


def _safety_schema(s: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(CONF_SENSOR_TIMEOUT, default=s[CONF_SENSOR_TIMEOUT]): _number(
                5, 1440, "min"
            ),
            probatio.Required(CONF_FALLBACK_OUTPUT, default=s[CONF_FALLBACK_OUTPUT]): _number(
                0, 100, "%"
            ),
        }
    )


def _window_schema(w: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(CONF_OPEN_DELAY, default=w[CONF_OPEN_DELAY]): _number(0, 3600, "s"),
            probatio.Required(CONF_CLOSE_DELAY, default=w[CONF_CLOSE_DELAY]): _number(
                0, 3600, "s"
            ),
        }
    )


def _manual_schema(m: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {probatio.Required(CONF_TIMEOUT, default=m[CONF_TIMEOUT]): _number(1, 1440, "min")}
    )


# The pages of the central settings, in menu order. Step ids match the options keys.
PAGES: dict[str, Callable[[dict[str, Any]], probatio.Schema]] = {
    SECTION_PRESENCE: _presence_schema,
    SECTION_PRESETS: _presets_schema,
    SECTION_CONTROL: _control_schema,
    SECTION_SAFETY: _safety_schema,
    SECTION_WINDOW: _window_schema,
    SECTION_MANUAL: _manual_schema,
}


def _thermostat_schema(values: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(
                CONF_NAME, description={"suggested_value": values.get(CONF_NAME)}
            ): TextSelector(),
            probatio.Required(
                CONF_SENSOR, description={"suggested_value": values.get(CONF_SENSOR)}
            ): SENSOR_SELECTOR,
            probatio.Required(
                CONF_HEATERS, description={"suggested_value": values.get(CONF_HEATERS)}
            ): HEATERS_SELECTOR,
            _optional_entity(CONF_OPENING, values): NUMBER_SELECTOR,
            _optional_entity(CONF_CLOSING, values): NUMBER_SELECTOR,
            _optional_entity(CONF_WINDOW, values): WINDOW_SELECTOR,
        }
    )


def _settings_schema(values: dict[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(key, default=values[key]): BooleanSelector()
            for key in (CONF_CENTRAL_HEATING, CONF_USE_CENTRAL_PRESETS, CONF_USE_CENTRAL_CONTROL)
        }
    )


def _validate(data: dict[str, Any]) -> dict[str, str]:
    heaters: list[str] = data.get(CONF_HEATERS) or []
    domains = {h.split(".")[0] for h in heaters}
    if not heaters:
        return {CONF_HEATERS: "no_heaters"}
    if len(domains) > 1:
        return {CONF_HEATERS: "mixed_heaters"}
    if bool(data.get(CONF_OPENING)) != bool(data.get(CONF_CLOSING)):
        return {"base": "valve_pair"}
    if data.get(CONF_OPENING) and (domains != {"climate"} or len(heaters) != 1):
        return {"base": "valve_needs_climate"}
    return {}


class EmberConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the Ember entry that holds the central settings."""

    VERSION = 1
    # 2 added the central heating subentry.
    MINOR_VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry with defaults; thermostats are added to it afterwards."""
        return self.async_create_entry(
            title="Ember",
            data={},
            options=deepcopy(DEFAULT_CENTRAL),
            subentries=[deepcopy(CENTRAL_HEATING_SUBENTRY)],
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EmberOptionsFlow:
        """Return the options flow."""
        return EmberOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Thermostats, and the central heating while there is none.

        There can only be one central heating, so its Add button is offered only
        after it was deleted. HA caches this; `__init__.py` resets the cache.
        """
        types: dict[str, type[ConfigSubentryFlow]] = {SUBENTRY_THERMOSTAT: ThermostatSubentryFlow}
        if not config_entry.get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
            types[SUBENTRY_CENTRAL_HEATING] = CentralHeatingSubentryFlow
        return types


class EmberOptionsFlow(OptionsFlow):
    """Edit the central settings, one page per group. The entry's update listener reloads it."""

    def __init__(self) -> None:
        """Initialise."""
        # Changes from every page, written together by the save step.
        self._options: dict[str, Any] | None = None
        # Thermostat subentry id to whether it counts for central heating.
        self._central_heating: dict[str, bool] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu of settings pages, and save."""
        if self._options is None:
            self._options = deepcopy(dict(self.config_entry.options))
            self._central_heating = {
                s.subentry_id: s.data[CONF_CENTRAL_HEATING] for s in self._thermostats()
            }
        pages = list(PAGES)
        if self._thermostats() and self.config_entry.get_subentries_of_type(
            SUBENTRY_CENTRAL_HEATING
        ):
            pages.append(SUBENTRY_CENTRAL_HEATING)
        return self.async_show_menu(step_id="init", menu_options=[*pages, "save"])

    def _thermostats(self) -> list[ConfigSubentry]:
        return self.config_entry.get_subentries_of_type(SUBENTRY_THERMOSTAT)

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Write the changes from all pages."""
        assert self._options is not None
        for subentry in self._thermostats():
            counts = self._central_heating.get(subentry.subentry_id)
            if counts is not None and subentry.data[CONF_CENTRAL_HEATING] != counts:
                self.hass.config_entries.async_update_subentry(
                    self.config_entry,
                    subentry,
                    data={**subentry.data, CONF_CENTRAL_HEATING: counts},
                )
        return self.async_create_entry(data=self._options)

    async def async_step_central_heating(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tick the thermostats that count; this sets their own toggle."""
        thermostats = self._thermostats()
        if user_input is not None:
            chosen = set(user_input.get(CONF_THERMOSTATS, []))
            self._central_heating = {s.subentry_id: s.subentry_id in chosen for s in thermostats}
            return await self.async_step_init()
        selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=s.subentry_id, label=s.title) for s in thermostats
                ],
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )
        counted = [sid for sid, counts in self._central_heating.items() if counts]
        return self.async_show_form(
            step_id=SUBENTRY_CENTRAL_HEATING,
            data_schema=probatio.Schema(
                {probatio.Optional(CONF_THERMOSTATS, default=counted): selector}
            ),
        )

    async def _async_step_page(
        self, page: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        assert self._options is not None
        if user_input is not None:
            values = _presets_from_form(user_input) if page == SECTION_PRESETS else user_input
            self._options[page] = values
            # Back to the menu, so more pages can be changed before saving.
            return await self.async_step_init()
        return self.async_show_form(
            step_id=page, data_schema=PAGES[page](dict(self._options[page]))
        )

    async def async_step_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Presence entity."""
        return await self._async_step_page(SECTION_PRESENCE, user_input)

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Home and away temperature of each preset."""
        return await self._async_step_page(SECTION_PRESETS, user_input)

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """PID and cycle settings."""
        return await self._async_step_page(SECTION_CONTROL, user_input)

    async def async_step_safety(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Stale sensor timeout and fallback."""
        return await self._async_step_page(SECTION_SAFETY, user_input)

    async def async_step_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Window delays."""
        return await self._async_step_page(SECTION_WINDOW, user_input)

    async def async_step_manual_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual control timeout."""
        return await self._async_step_page(SECTION_MANUAL, user_input)


class ThermostatSubentryFlow(ConfigSubentryFlow):
    """Add or change a thermostat."""

    def __init__(self) -> None:
        """Initialise."""
        self._data: dict[str, Any] = {}
        self._title = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for name, sensor, heaters and which central settings to use."""
        return await self._async_step_main("user", {}, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a thermostat."""
        subentry = self._get_reconfigure_subentry()
        values = {CONF_NAME: subentry.title, **subentry.data}
        return await self._async_step_main("reconfigure", values, user_input)

    async def _async_step_main(
        self, step_id: str, values: dict[str, Any], user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            if not (errors := _validate(data)):
                self._title = data.pop(CONF_NAME)
                # Keep the rest of an existing thermostat's settings as the starting point.
                self._data = {**{k: v for k, v in values.items() if k != CONF_NAME}, **data}
                for key in (CONF_OPENING, CONF_CLOSING, CONF_WINDOW):
                    if key not in data:
                        self._data.pop(key, None)
                return await self.async_step_settings()
            values = user_input
        return self.async_show_form(
            step_id=step_id, data_schema=_thermostat_schema(values), errors=errors
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask whether it counts for central heating and uses the central settings."""
        if user_input is not None:
            self._data.update(user_input)
            return await self._async_next(None)
        defaults = {
            # Valves and TRVs usually sit on a boiler or heat pump, switches
            # usually drive electric heaters.
            CONF_CENTRAL_HEATING: self._data[CONF_HEATERS][0].startswith("climate."),
            CONF_USE_CENTRAL_PRESETS: True,
            CONF_USE_CENTRAL_CONTROL: True,
        }
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema({**defaults, **self._data})
        )

    async def _async_next(self, after: str | None) -> SubentryFlowResult:
        # The pages for this thermostat's own settings come in order: presets, then control.
        if after is None and not self._data[CONF_USE_CENTRAL_PRESETS]:
            return await self.async_step_presets()
        if after != SECTION_CONTROL and not self._data[CONF_USE_CENTRAL_CONTROL]:
            return await self.async_step_control()
        return self._finish()

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for this thermostat's own preset temperatures."""
        if user_input is not None:
            self._data[SECTION_PRESETS] = _presets_from_form(user_input)
            return await self._async_next(SECTION_PRESETS)
        presets = self._data.get(SECTION_PRESETS) or self._get_entry().options[SECTION_PRESETS]
        return self.async_show_form(step_id="presets", data_schema=_presets_schema(presets))

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for this thermostat's own PID and cycle settings."""
        if user_input is not None:
            self._data[SECTION_CONTROL] = user_input
            return await self._async_next(SECTION_CONTROL)
        control = self._data.get(SECTION_CONTROL) or self._get_entry().options[SECTION_CONTROL]
        return self.async_show_form(step_id="control", data_schema=_control_schema(control))

    def _finish(self) -> SubentryFlowResult:
        data = dict(self._data)
        if data[CONF_USE_CENTRAL_PRESETS]:
            data.pop(SECTION_PRESETS, None)
        if data[CONF_USE_CENTRAL_CONTROL]:
            data.pop(SECTION_CONTROL, None)
        if self.source == "user":
            return self.async_create_entry(title=self._title, data=data)
        return self.async_update_and_abort(
            self._get_entry(), self._get_reconfigure_subentry(), title=self._title, data=data
        )


class CentralHeatingSubentryFlow(ConfigSubentryFlow):
    """Add the central heating back after it was deleted."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create it; there is only one, so a second is refused."""
        if self._get_entry().get_subentries_of_type(SUBENTRY_CENTRAL_HEATING):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=CENTRAL_HEATING_SUBENTRY["title"],
            data={},
            unique_id=CENTRAL_HEATING_SUBENTRY["unique_id"],
        )

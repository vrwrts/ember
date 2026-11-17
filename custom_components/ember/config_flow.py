"""Config, options and thermostat subentry flows for Ember."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
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
    TextSelector,
)

from .const import (
    AWAY_SUFFIX,
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


def _presets_schema(p: dict[str, Any]) -> probatio.Schema:
    keys = [k for preset in PRESETS for k in (preset, f"{preset}{AWAY_SUFFIX}")]
    return probatio.Schema({probatio.Required(k, default=p[k]): TEMPERATURE for k in keys})


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


def _central_schema(options: dict[str, Any]) -> probatio.Schema:
    s = options[SECTION_SAFETY]
    w = options[SECTION_WINDOW]
    m = options[SECTION_MANUAL]
    return probatio.Schema(
        {
            probatio.Required(SECTION_PRESENCE): section(
                probatio.Schema(
                    {_optional_entity(CONF_ENTITY, options[SECTION_PRESENCE]): PRESENCE_SELECTOR}
                )
            ),
            probatio.Required(SECTION_PRESETS): section(_presets_schema(options[SECTION_PRESETS])),
            probatio.Required(SECTION_CONTROL): section(
                _control_schema(options[SECTION_CONTROL]), {"collapsed": True}
            ),
            probatio.Required(SECTION_SAFETY): section(
                probatio.Schema(
                    {
                        probatio.Required(
                            CONF_SENSOR_TIMEOUT, default=s[CONF_SENSOR_TIMEOUT]
                        ): _number(5, 1440, "min"),
                        probatio.Required(
                            CONF_FALLBACK_OUTPUT, default=s[CONF_FALLBACK_OUTPUT]
                        ): _number(0, 100, "%"),
                    }
                ),
                {"collapsed": True},
            ),
            probatio.Required(SECTION_WINDOW): section(
                probatio.Schema(
                    {
                        probatio.Required(CONF_OPEN_DELAY, default=w[CONF_OPEN_DELAY]): _number(
                            0, 3600, "s"
                        ),
                        probatio.Required(CONF_CLOSE_DELAY, default=w[CONF_CLOSE_DELAY]): _number(
                            0, 3600, "s"
                        ),
                    }
                ),
                {"collapsed": True},
            ),
            probatio.Required(SECTION_MANUAL): section(
                probatio.Schema(
                    {
                        probatio.Required(CONF_TIMEOUT, default=m[CONF_TIMEOUT]): _number(
                            1, 1440, "min"
                        )
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry with defaults; thermostats are added to it afterwards."""
        return self.async_create_entry(title="Ember", data={}, options=deepcopy(DEFAULT_CENTRAL))

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
        """Thermostats are subentries."""
        return {SUBENTRY_THERMOSTAT: ThermostatSubentryFlow}


class EmberOptionsFlow(OptionsFlow):
    """Edit the central settings. The entry's update listener reloads it."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the central settings, grouped in sections."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_central_schema(dict(self.config_entry.options))
        )


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
            if user_input[CONF_USE_CENTRAL_PRESETS] and user_input[CONF_USE_CENTRAL_CONTROL]:
                return self._finish()
            return await self.async_step_overrides()
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

    async def async_step_overrides(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for this thermostat's own presets and/or control settings."""
        if user_input is not None:
            self._data.update(user_input)
            return self._finish()
        central = self._get_entry().options
        fields: dict[Any, Any] = {}
        if not self._data[CONF_USE_CENTRAL_PRESETS]:
            fields[probatio.Required(SECTION_PRESETS)] = section(
                _presets_schema(self._data.get(SECTION_PRESETS) or central[SECTION_PRESETS])
            )
        if not self._data[CONF_USE_CENTRAL_CONTROL]:
            fields[probatio.Required(SECTION_CONTROL)] = section(
                _control_schema(self._data.get(SECTION_CONTROL) or central[SECTION_CONTROL])
            )
        return self.async_show_form(step_id="overrides", data_schema=probatio.Schema(fields))

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

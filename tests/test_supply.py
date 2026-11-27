"""Supply temperature compensation."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.ember.const import DOMAIN

from .conftest import SWITCH, VALVE, Devices, add_thermostat, central, state, thermostat_data

SUPPLY = "sensor.supply"
# Room at 16 °C, 1 K below Eco: 50 % at the reference supply.
OPTIONS = central(
    control={"kp": 50, "ki": 0, "kd": 0}, supply={"entity": SUPPLY, "reference": 60}
)


def _supply(hass: HomeAssistant, value: float | str, unit: str = "°C") -> None:
    hass.states.async_set(SUPPLY, str(value), {"unit_of_measurement": unit})


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=301))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _opening(hass: HomeAssistant) -> float:
    return float(state(hass, "number.opening").state)


async def test_hotter_supply_opens_the_valve_less(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    _supply(hass, 60)
    await add_thermostat(hass, VALVE, options=OPTIONS)
    assert _opening(hass) == 50

    # 88 K above the room instead of 44 K: half the opening gives the same heat.
    _supply(hass, 104)
    await _tick(hass, freezer)
    assert _opening(hass) == 25

    _supply(hass, 38)
    await _tick(hass, freezer)
    assert _opening(hass) == 100


async def test_supply_in_fahrenheit(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    _supply(hass, 219.2, "°F")
    await add_thermostat(hass, VALVE, options=OPTIONS)
    assert _opening(hass) == 25


async def test_unusable_supply_is_ignored(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    _supply(hass, 104)
    await add_thermostat(hass, VALVE, options=OPTIONS)
    _supply(hass, "unavailable")
    await _tick(hass, freezer)
    assert _opening(hass) == 50


async def test_cold_supply_does_not_wind_up(
    hass: HomeAssistant, devices: Devices, freezer: FrozenDateTimeFactory
) -> None:
    # The fire is out: the valve is fully open and the integral holds.
    _supply(hass, 17)
    handle = await add_thermostat(
        hass, VALVE, options=central(supply={"entity": SUPPLY, "reference": 60})
    )
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    assert _opening(hass) == 100
    assert handle.thermostat.pid.integral == 0


async def test_switch_share_follows_the_supply(
    hass: HomeAssistant, devices: Devices
) -> None:
    _supply(hass, 104)
    handle = await add_thermostat(hass, SWITCH, options=OPTIONS)
    assert handle.thermostat.output == 25


async def test_without_a_supply_sensor_nothing_changes(
    hass: HomeAssistant, devices: Devices
) -> None:
    _supply(hass, 104)
    await add_thermostat(hass, VALVE, options=central(control={"kp": 50, "ki": 0, "kd": 0}))
    assert _opening(hass) == 50


async def test_migration_adds_the_supply_settings(hass: HomeAssistant, devices: Devices) -> None:
    options = central()
    del options["supply"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ember",
        minor_version=2,
        options=options,
        subentries_data=[
            {
                "data": thermostat_data(VALVE),
                "subentry_type": "thermostat",
                "title": "Living room",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 3
    assert entry.options["supply"] == {"reference": 55}


async def test_supply_jump_acts_straight_away(hass: HomeAssistant, devices: Devices) -> None:
    _supply(hass, 60)
    await add_thermostat(hass, VALVE, options=OPTIONS)
    _supply(hass, 104)
    await hass.async_block_till_done()
    assert _opening(hass) == 25


async def test_small_supply_change_waits_for_the_next_tick(
    hass: HomeAssistant, devices: Devices
) -> None:
    _supply(hass, 60)
    handle = await add_thermostat(hass, VALVE, options=OPTIONS)
    _supply(hass, 62)
    await hass.async_block_till_done()
    assert handle.thermostat.output == 50

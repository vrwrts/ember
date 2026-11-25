"""Constants for Ember."""

from typing import Final

DOMAIN: Final = "ember"

SUBENTRY_THERMOSTAT: Final = "thermostat"
SUBENTRY_CENTRAL_HEATING: Final = "central_heating"

# Holds the heating demand entities. Created with the entry, and by migration
# for entries from before it existed.
CENTRAL_HEATING_SUBENTRY: Final = {
    "data": {},
    "subentry_type": SUBENTRY_CENTRAL_HEATING,
    "title": "Central heating",
    "unique_id": SUBENTRY_CENTRAL_HEATING,
}

CONF_THERMOSTATS: Final = "thermostats"

PRESET_FROST: Final = "frost"
PRESET_ECO: Final = "eco"
PRESET_COMFORT: Final = "comfort"
PRESET_BOOST: Final = "boost"
PRESETS: Final = (PRESET_FROST, PRESET_ECO, PRESET_COMFORT, PRESET_BOOST)
# What a new thermostat starts on.
DEFAULT_PRESET: Final = PRESET_ECO
AWAY_SUFFIX: Final = "_away"

SECTION_PRESENCE: Final = "presence"
CONF_ENTITY: Final = "entity"

SECTION_PRESETS: Final = "presets"

SECTION_CONTROL: Final = "control"
CONF_KP: Final = "kp"
CONF_KI: Final = "ki"
CONF_KD: Final = "kd"
CONF_INTERVAL: Final = "interval"
CONF_CYCLE: Final = "cycle"
CONF_MIN_SWITCH_TIME: Final = "min_switch_time"

SECTION_SAFETY: Final = "safety"
CONF_SENSOR_TIMEOUT: Final = "sensor_timeout"
CONF_FALLBACK_OUTPUT: Final = "fallback_output"

SECTION_WINDOW: Final = "window"
CONF_OPEN_DELAY: Final = "open_delay"
CONF_CLOSE_DELAY: Final = "close_delay"

SECTION_MANUAL: Final = "manual_control"
CONF_TIMEOUT: Final = "timeout"

CONF_AREA: Final = "area"
CONF_SENSOR: Final = "temperature_sensor"
CONF_HEATERS: Final = "heaters"
CONF_OPENING: Final = "opening_degree"
CONF_CLOSING: Final = "closing_degree"
CONF_WINDOW: Final = "window_sensor"
CONF_CENTRAL_HEATING: Final = "central_heating"
CONF_USE_CENTRAL_PRESETS: Final = "use_central_presets"
CONF_USE_CENTRAL_CONTROL: Final = "use_central_control"

DEFAULT_PRESETS: Final = {
    PRESET_FROST: 7.0,
    f"{PRESET_FROST}{AWAY_SUFFIX}": 7.0,
    PRESET_ECO: 17.0,
    f"{PRESET_ECO}{AWAY_SUFFIX}": 15.0,
    PRESET_COMFORT: 20.0,
    f"{PRESET_COMFORT}{AWAY_SUFFIX}": 17.0,
    PRESET_BOOST: 23.0,
    f"{PRESET_BOOST}{AWAY_SUFFIX}": 19.0,
}

# Gains in % output per kelvin, starting from Better Thermostat's PID defaults.
DEFAULT_CONTROL: Final = {
    CONF_KP: 60.0,
    CONF_KI: 0.01,
    CONF_KD: 2000.0,
    CONF_INTERVAL: 300,
    CONF_CYCLE: 10,
    CONF_MIN_SWITCH_TIME: 30,
}

# The Ember entry's options: settings every thermostat shares.
DEFAULT_CENTRAL: Final = {
    SECTION_PRESENCE: {},
    SECTION_PRESETS: DEFAULT_PRESETS,
    SECTION_CONTROL: DEFAULT_CONTROL,
    SECTION_SAFETY: {CONF_SENSOR_TIMEOUT: 120, CONF_FALLBACK_OUTPUT: 20},
    SECTION_WINDOW: {CONF_OPEN_DELAY: 30, CONF_CLOSE_DELAY: 0},
    SECTION_MANUAL: {CONF_TIMEOUT: 60},
}

MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 30.0
TEMP_STEP: Final = 0.5

SERVICE_RESUME: Final = "resume"

# Smallest valve change worth a write. Battery TRVs pay for every radio message,
# and a few percent makes no difference to the room.
VALVE_DEADBAND: Final = 5
# Seconds a smaller change must keep pointing the same way before it is written
# anyway. Without it the integral can't fine-tune a steady opening, which leaves
# the room cycling; this caps those writes at three pairs an hour.
VALVE_SUSTAIN: Final = 20 * 60
# Above this opening, in percent, a valve counts as calling for heat.
DEMAND_THRESHOLD: Final = 5
# Seconds after our own write in which reports from that device are not manual.
# Zigbee TRVs report several in-between states, and the TRVZB adjusts its own
# setpoint shortly after being written to (VTherm ignores 15 s for this).
SETTLE_WINDOW: Final = 30
# Differences smaller than these between what we sent and what a device reports
# are rounding, not someone changing it.
TEMP_TOLERANCE: Final = 0.25
NUMBER_TOLERANCE: Final = 1
# Longest gap the PID integrates over. After a long gap, such as HA being down,
# integrating the whole gap would wind the output up on stale information.
PID_MAX_DT: Final = 900
# Kelvin from the target within which the integral always adjusts. Further
# away it pauses while the room moves towards the target. In the Office the
# integral climbed from about 15 to 50 % during each morning warm-up, which
# overshot the room by up to 1 K and then left it below target.
INTEGRAL_BAND: Final = 0.5
# Longest HA shutdown waits for the hand-back writes to go out.
HAND_BACK_TIMEOUT: Final = 10

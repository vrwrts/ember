# Ember

A Home Assistant integration that heats rooms from an external temperature sensor, with presets you set once for the whole home.

Each thermostat drives switches, a TRV's valve directly, or a TRV's own setpoint. Presets (Frost, Eco, Comfort, Boost) and the control settings are central, and a thermostat can override them. Each preset has a temperature for when someone is home and one for when nobody is.

Ember borrows ideas from [Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat) and [Better Thermostat](https://github.com/KartoffelToby/better_thermostat), with far fewer options.

## Installation

Requires Home Assistant 2026.11 or later.

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Add `https://github.com/vrwrts/ember` with type **Integration**.
3. Install **Ember** and restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration** and choose **Ember**.

## Setup

Ember has one entry. It holds the settings all thermostats share: presence, presets, control, safety, windows and manual control. Change them with **Configure** on the Ember entry, which opens a menu with a page for each. Submitting a page takes you back to the menu, so you can change several pages. Choose **Save and close** in the menu to apply all changes. Closing the dialog without saving discards them.

Add a thermostat with **Add thermostat**. Each one creates a `climate` entity, which starts in heat on the Eco preset. Change a thermostat with its **Reconfigure** option. Changing the Ember settings or any thermostat restarts all thermostats, which ends manual control.

## Thermostat types

The type follows from the heaters you choose.

| Heaters | Type | What Ember does |
|---|---|---|
| One or more switches | Switch | Works out an output from 0 to 100 % with a PID controller, and turns the switches on for that share of each cycle. |
| One climate entity plus valve opening and closing degree entities | Valve | Works out the output with the PID controller and writes it to the valve. |
| One or more climate entities | Pass-through | Sends the target temperature and mode to each device, which regulates itself. |

### Valve control

For a TRV with valve opening degree and closing degree entities, such as the Sonoff TRVZB:

- the TRV is kept in heat with its setpoint at its maximum, so its own regulation always wants to open;
- Ember writes the output to the opening degree, and 100 minus the output to the closing degree;
- values are scaled to each entity's range;
- a new value is only written when it changes by at least 5 %, or to close or open the valve fully. Battery TRVs pay for every write;
- a smaller change is written once the output has stayed above, or below, the valve's position for 20 minutes. This lets Ember fine-tune a steady opening without writing more than a few times an hour.

### Pass-through

Each device regulates on its own sensor, so Ember's room sensor is only shown as the current temperature. Safety mode and the PID controller don't apply.

Several devices, such as the TRVs of one room, can share a thermostat. Each gets the same target, limited to its own temperature range. The thermostat is heating while any of them reports heating. A change on any one of them puts the whole thermostat under manual control.

## The climate entity

- **Off**: switches off, valve closed and TRV off, or the pass-through devices off.
- **Heat**: Ember controls the devices.
- **Presets**: Frost, Eco, Comfort and Boost. Setting a temperature by hand switches the preset to none.
- **Attributes**: `output` (switch and valve), `window_open`, `manual_control` and `manual_until`.

`hvac_action` is read from the devices: heating while a switch is on, the valve is more than 5 % open, or a pass-through device reports heating.

## Other entities of a thermostat

- **Valve** (valve thermostats): how far the TRV's valve is open, read from its opening degree. Opening, closing or setting a position writes it to the TRV straight away and puts the thermostat under manual control, so Ember leaves it there until manual control ends. Closing also turns the TRV off.
- **Output** (switch thermostats): the share of each cycle the switches are on, in %. It is 0 while the thermostat is off or a window is open, and unknown under manual control.
- **Integral** (switch and valve thermostats, disabled by default): the integral term of the PID controller, in %. Once the room has settled, it is roughly the output the room needs to hold its target, at the reference supply temperature if a supply sensor is set. That helps when tuning. It keeps its value while the thermostat is off, a window is open or the thermostat is under manual control.

Pass-through thermostats have none of these, as their devices regulate themselves.

## Ember settings

### Presence

| Option | Default | |
|---|---|---|
| Presence entity | none | A person, a zone, or an occupancy or presence binary sensor. |

While nobody is home (person not `home`, zone count 0, sensor off), thermostats use the away temperature of their preset. A temperature set by hand doesn't change. Without a presence entity, or while it's unavailable, Ember treats the home as occupied.

### Presets

| Preset | Home | Away |
|---|---|---|
| Frost | 7 °C | 7 °C |
| Eco | 17 °C | 15 °C |
| Comfort | 20 °C | 17 °C |
| Boost | 23 °C | 19 °C |

### Control

| Option | Default | |
|---|---|---|
| Kp | 60 | Output in % per degree below the target. |
| Ki | 0.01 | Output in % added per degree below the target, per second. |
| Kd | 2000 | Brakes the output while the room warms up quickly. |
| Control interval | 300 s | How often the output is worked out again. |
| Switch cycle | 10 min | Switches are on for the output's share of each cycle. |
| Minimum switch on or off time | 30 s | Shorter on or off periods are skipped. |

More than 0.5 °C from the target, the integral pauses while the room is already moving towards the target. That keeps a morning warm-up from building up an overshoot.

The defaults start from Better Thermostat's. Every room is different, so expect to tune them.

### Supply temperature

For heating whose water temperature changes a lot, such as a wood-fired boiler. A radiator gives off heat roughly in proportion to how much hotter its water is than the room. With a supply sensor, Ember scales the output of switch and valve thermostats by that difference, so a valve opens further while the water is cooler and less while it's hotter. The room's PID then no longer has to catch up with every change in supply.

| Option | Default | |
|---|---|---|
| Supply temperature sensor | none | Optional. Measures the water going to the radiators. Without one, the output isn't adjusted. |
| Reference supply temperature | 55 °C | The supply temperature your heating normally runs at, such as what a shunt or mixing valve aims for. At this temperature the output is as the PID works it out. |

When the supply is less than 5 °C above the room, for example with the fire out, the output goes to 100 % and the integral holds, so the room doesn't overshoot once hot water arrives. An unavailable supply sensor is ignored. Pass-through thermostats aren't affected.

### Safety

| Option | Default | |
|---|---|---|
| Sensor timeout | 120 min | A room sensor that's unavailable, or hasn't reported for this long, is treated as broken. |
| Fallback output | 20 % | Valve opening or switch share while the sensor is broken. |

Ember raises a repair issue while a sensor is broken, and clears it when readings return. Battery sensors that only report changes can stay silent for a long time in a stable room, so keep the timeout at a few hours.

### Windows

| Option | Default | |
|---|---|---|
| Open delay | 30 s | How long a window is open before heating stops. |
| Close delay | 0 s | How long a window is closed before heating starts again. |

While the window sensor of a thermostat is open, the output is 0 and pass-through devices are turned off. The mode stays heat. An unavailable window sensor counts as closed.

### Manual control

| Option | Default | |
|---|---|---|
| Timeout | 60 min | How long Ember leaves a device alone after it's changed outside Ember. |

A thermostat goes under manual control when one of its devices is changed by something other than Ember, for example turning a TRV's knob or switching a plug in its app, or when its Valve entity is set. Ember then sends nothing to that thermostat's devices.

Reports within 30 seconds of Ember's own write don't count. Zigbee TRVs report in-between states, and the TRVZB adjusts its setpoint by itself shortly after a write.

Manual control ends when:

- the timeout runs out. Another change on the device restarts it;
- you change the Ember thermostat's mode, preset or temperature;
- you call [`ember.resume`](#emberresume).

It survives a restart.

## Thermostat settings

### Devices

| Option | |
|---|---|
| Area | Optional. The area the device is placed in. |
| Name | The name of the device and its climate entity, for example "Radiator". The thermostat is listed under the area followed by the name, for example "Living Room Radiator". |
| Temperature sensor | The room temperature. |
| Heaters | One or more switches, or one or more climate entities. |
| Valve opening degree, valve closing degree | Optional. Both or neither, and only with a single climate entity. |
| Window sensor | Optional. A window, door or opening binary sensor. |

### Settings

| Option | Default | |
|---|---|---|
| Part of central heating | on for climate entities, off for switches | Counts towards the [heating demand](#heating-demand) entities. |
| Use central presets | on | Turn off to set this thermostat's own preset temperatures, on a page after this one. |
| Use central control settings | on | Turn off to set this thermostat's own PID and cycle settings, on a page after this one. |

## Heating demand

Ember is set up with a **Central heating** entry next to your thermostats. Its device has two entities, for running a boiler or heat pump:

- **Demand** (`binary_sensor`): on while any thermostat that's part of central heating calls for heat.
- **Thermostats calling for heat** (`sensor`): how many do.

Only thermostats with **Part of central heating** on count. It's on by default for TRVs, which usually sit on a water system, and off for switches, which usually drive electric heaters. Set it per thermostat, or for all of them at once on the **Central heating** page of Ember's settings, which lists the thermostats with a checkbox each.

If you don't need the demand entities, delete the central heating. Ember then offers **Add central heating** to add it back. There can only be one, so the button is hidden while it exists.

Installs from before the central heating entry existed keep their entity IDs (`binary_sensor.ember_heating_demand`, `sensor.ember_thermostats_calling_for_heat`). The entities move from the "Ember" device to the new "Central heating" device.

## Handing control back

When Home Assistant stops, Ember leaves the devices able to run on their own:

- **Valve**: opening and closing degree go back to their maximum (the TRVZB's default). The TRV gets the thermostat's target temperature and mode instead of the pinned maximum. Under manual control only the degrees are reset.
- **Switch**: switches are turned off, as a switch can't regulate by itself.
- **Pass-through**: nothing changes, the devices already regulate on Ember's target.

The same happens when Ember is disabled or removed, or a thermostat is deleted. When Home Assistant starts again, each thermostat goes back to the mode it was in and takes over its devices.

If Home Assistant crashes or loses power, there's no hand-back. A TRV then keeps its maximum setpoint and Ember's last valve position until Home Assistant is back.

## Actions

### `ember.resume`

Ends manual control of the targeted Ember thermostats and takes over their devices straight away.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
```

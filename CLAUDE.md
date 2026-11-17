# Ember

A Home Assistant custom integration, installed through HACS, for heating control. Each thermostat heats a room from an external temperature sensor. Presets (Frost, Eco, Comfort, Boost), each with a home and an away temperature, are set once centrally and used by every thermostat unless it overrides them. `README.md` describes the behaviour for users.

The aim is a small integration with few options. Prefer leaving a feature out over adding an option for it.

## Architecture

There is one config entry (`single_config_entry`) with the central settings in its options: presence, presets, control, safety, windows and manual control. Each thermostat is a subentry. Its data holds its devices and toggles, plus its own `presets` or `control` section when it doesn't use the central ones.

```
config entry (options: central settings)
├── thermostat subentry ─▶ Thermostat ─▶ Actuator ─▶ switch / climate / number entities
│                              ▲
│                              └── EmberClimate (climate entity, restores state)
├── …
└── HeatingDemand, CallingForHeat (central device, read every Thermostat)
```

- `__init__.py` creates one `Thermostat` per subentry in `entry.runtime_data` and forwards the platforms. It also registers `ember.resume`. A change to the entry or a subentry reloads the entry. On disable, on removal of the entry and on deleting a subentry it hands the devices back first. A plain reload doesn't hand them back.
- `config_flow.py` holds the config flow, the options flow and the subentry flow. The config flow creates the entry with `DEFAULT_CENTRAL`. The options flow edits the central settings in sections. The subentry flow has three steps: `user`/`reconfigure` (devices), `settings` (central heating and the two "use central" toggles), and `overrides` (only when a toggle is off).
- `thermostat.py` holds all behaviour of one thermostat:
  - the target from preset and presence, or a temperature set by hand;
  - the control loop on a fixed interval: PID output, window pause, stale sensor fallback with a repair issue;
  - manual control with its timeout;
  - restore data, and the hand-back on `EVENT_HOMEASSISTANT_STOP`.
  - It tells listeners (the entities) when something changes.
- `actuator.py` has one class per type. The type follows from the subentry data:
  - `SwitchActuator`: one or more switches, on for the output's share of each cycle.
  - `ValveActuator`: one TRV kept in heat at its max setpoint. The output goes to the opening degree and 100 minus the output to the closing degree, with a deadband.
  - `PassThroughActuator`: one or more climate entities that get the target and mode.
  - Every service call goes through `Actuator._call`, which records Ember's context and the expected value. `is_manual_change` uses these, with `SETTLE_WINDOW` and the tolerances, to tell outside changes from Ember's own echoes.
- `pid.py` is a plain PID (0 to 100 %, derivative on measurement, conditional integration). It has no Home Assistant imports.
- `climate.py` is a thin view on a `Thermostat`. It restores the thermostat's state through `extra_restore_state_data` and starts it once added.
- `demand.py`, `binary_sensor.py` and `sensor.py` count thermostats with "Part of central heating" on that call for heat. They read the devices' own state, not Ember's output.
- `const.py` holds keys, defaults and tuning constants.

Behaviour to keep when changing things:

- Under manual control Ember sends nothing to that thermostat's devices.
- Unknown presence counts as home, and an unavailable window sensor counts as closed, so a dead sensor never lowers the heating.
- Valve writes are rate-limited by `VALVE_DEADBAND`. Battery TRVs pay for every write.
- Temperatures are handled in °C. Sensors in other units are converted.

## Workflow

### Branches and pull requests

- `main` is the release branch. Work on a branch and open a pull request.
- PR titles and every commit message use [Conventional Commits](https://www.conventionalcommits.org/), because the release process depends on them. Examples: `feat: …`, `fix: …`, `docs: …`, `test: …`, `ci: …`, `chore: …`. Mark breaking changes with `!` (`feat!: …`) or a `BREAKING CHANGE:` footer.
- In the commit body, say why the change was made.
- PR descriptions use the sections Why, What changed, Not covered (if anything was left out on purpose) and Testing. On GitHub, don't hard-wrap Markdown paragraphs.

### CI

On pull requests:
- `tests.yml` runs pytest;
- `validate.yml` runs hassfest and the HACS action, also weekly.

### Releases

`release.yml` runs [semantic-release](https://semantic-release.gitbook.io/) on every push to `main`, configured in `.releaserc.json`.

- **What triggers a release:** `fix:` makes a patch release, `feat:` a minor one, and a breaking change a major one. Other types don't release.
- **What it does:**
  1. writes the version into `custom_components/ember/manifest.json`;
  2. commits that as `chore(release): x.y.z [skip ci]`;
  3. tags the commit and publishes a GitHub release with generated notes. HACS installs from those releases.
- **Never edit the version by hand.**

### Dependency updates

Dependabot (`.github/dependabot.yml`) opens one grouped PR a month for each of:
- Python test dependencies (`requirements_test.txt`), titled `chore(deps): …`;
- GitHub Actions, titled `ci: …`.

Neither type triggers a release. `pytest-homeassistant` pins the Home Assistant version the tests run against. When it moves past the minimum in `hacs.json`, decide whether to raise that minimum, which is a user-visible change.

## Code

- Comments say why, not what. Keep them sparse. Public methods get a one-line docstring that doesn't just repeat the signature.
- Constants go in `const.py`. Tuning values like `VALVE_DEADBAND` and `SETTLE_WINDOW` get a comment explaining why they exist.
- Spell user-facing text in British English. Keep `strings.json` and `translations/en.json` identical.

## Docs

- `README.md` is the user documentation. Update it in the same change as any user-visible behaviour change.
- Write plainly. No em dashes: use commas or split the sentence.

## Tests

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
```

- Tests use `pytest-homeassistant`, plus `freezer` for time.
- The mocks in `tests/conftest.py` are `MockSwitch`, `MockTRV` and `MockNumber`. Their `external()` simulates a change made outside Home Assistant.
- The helpers are `add_thermostat`, `central`, `call`, `set_temperature` and `state`. The test room sits at 16 °C, 1 K below the Eco target that new thermostats start on.
- A test for a bug fix should fail without the fix.

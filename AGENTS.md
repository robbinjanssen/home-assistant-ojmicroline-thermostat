# AGENTS.md

Guidance for AI coding agents working on this repository. Human contributors:
see [CONTRIBUTING](.github/CONTRIBUTING.md).

## Project

A Home Assistant custom integration (distributed through HACS) for OJ Microline
cloud thermostats. Domain: `ojmicroline_thermostat`. The API communication
lives in the [`ojmicroline-thermostat`](https://github.com/robbinjanssen/python-ojmicroline-thermostat)
library (same owner). Fix API behaviour in the library rather than working
around it here.

Three thermostat series, each with its own API in the library:

| Series | Library API | Notes |
| --- | --- | --- |
| WD5 (OWD5, MWD5, WCD5) | `WD5API`, `WD5LocalAPI` | session API; push via the SignalR hub in `push.py`; schedule, vacation and energy history; optional local gateway |
| WG4 (UWG4, AWG4) | `WG4API`, `WG4LocalAPI` | session API; push via the library's `subscribe()`; energy history and power; optional local gateway |
| WG5 (UWG5) | `WG5API` | OAuth API; polled; tested by users with a real thermostat (#302), not by the maintainers |

```text
custom_components/ojmicroline_thermostat/
  __init__.py      setup, unload, version migration, schedule card registration
  api.py           creates the model API from config entry data
  config_flow.py   user, wd5/wg4/wg5, reauth, reconfigure and options flow
  coordinator.py   polling, push handling, session retry, WD5 group updates
  energy.py        long-term energy statistics (WD5, WG4)
  local.py         local gateway of a WG4 or WD5 account: certificate,
                   stored snapshot and profiles, repair issues
  push.py          WD5 push client
  climate.py, sensor.py, binary_sensor.py, date.py, switch.py, schedule.py
  frontend/        schedule card served by async_setup
  strings.json, translations/{en,nl,pt}.json, icons.json, services.yaml, brand/
tests/             pytest-homeassistant-custom-component tests, API fixtures
```

## Commands

The project uses [uv](https://docs.astral.sh/uv/) and
[prek](https://github.com/j178/prek).

```sh
uv sync                        # create .venv with Home Assistant and dev tools
uv run prek install            # git hook running all checks on commit
uv run prek run --all-files    # Ruff, mypy, pylint, codespell, yamllint, ...
uv run pytest                  # tests; CI requires 70% coverage
```

Run all hooks and tests before committing. The hooks refuse commits to `main`;
work on a branch.

## Requirements and the library

- Python 3.14.2+ and Home Assistant 2026.10.0+ (`hacs.json`, README). Only
  raise the minimum on purpose and update both.
- `manifest.json` pins the released library version that users install.
- For development, `pyproject.toml` takes the library from its `main` branch.
  `uv.lock` pins a commit, so after merging library changes run
  `uv lock --upgrade-package ojmicroline-thermostat`.
- Release the library before an integration release that depends on it, and
  bump the manifest to that version.

## Conventions

- **Typing**: mypy runs in strict mode from `pyproject.toml` against the real
  Home Assistant types. Use `probatio` for schemas (Home Assistant's validation
  library since 2026.9), not `voluptuous`.
- **Name clash**: the integration package and the library are both called
  `ojmicroline_thermostat`. pylint ignores the module for that reason; keep the
  `ignored-modules` setting.
- **Documentation**: the README is also the page HACS shows, so keep it short:
  what the integration does, installation and configuration. Details go in
  `docs/` (apps, energy, schedule, local connection). Link from the README to
  the docs with absolute GitHub URLs, because HACS does not resolve relative
  links; within `docs/`, link relatively.
- **Sessions**: the coordinator calls the WD5/WG4 API directly with the session
  ID. Wrap such calls in `_async_with_session`, which logs in again and retries
  once when the API rejects the session (HTTP 401).
- **Entities**: `_attr_has_entity_name = True` with a `translation_key`; the
  device is named after the thermostat. While a thermostat is offline its
  climate entity, sensors and binary sensors are unavailable, except the
  sensor that tells it is offline: what it reported last is not what it
  does now. The settings of its group (vacation, schedule) stay available. Keep entity IDs stable for existing
  users. Features that only one series supports check the series first (for
  example `is_wd5()`).
- **Translations**: Home Assistant loads `translations/*.json` for custom
  integrations. When changing `strings.json`, update `en`, `nl` and `pt` too.
- **Presets**: switching to manual or comfort always sends a temperature
  (manual: the current target; comfort: the configured comfort temperature,
  otherwise the one stored in the thermostat). Without one, WG4 thermostats
  fall back to an unrelated value.
- **State updates**: after changing a thermostat, apply the change to the
  coordinator data right away and refresh in the background, as
  `climate._async_set_regulation_mode` does.
- **Reloading**: use `OptionsFlowWithReload` and `async_update_reload_and_abort`.
  Do not add a config entry update listener next to these; Home Assistant
  2026.12 rejects that combination.
- **Diagnostics**: redact credentials and API keys.
- **Local connection (WG4, WD5)**: with the `connection_mode` option on
  `relay` or `local`, the coordinator starts a `LocalGateway` in
  `_async_setup` and swaps its API for the library's `WG4LocalAPI` or
  `WD5LocalAPI`. The gateway and protocol live in the library; `local.py`
  only holds what Home Assistant keeps.
  - The WG4 gateway ran against four real thermostats of two users: on the
    first one its commands were confirmed too late in one test and in time
    in the next, for a reason that is not known. The WD5 gateway ran
    against OWD5 thermostats of four testers, with the relay and in local
    only. Neither is called experimental any more, which was the
    maintainer's choice. `docs/local-connection.md` tells what the local
    connection ran on and what was never tested; keep that list up to date.
  - `endpoint_for()` tells which device gateway the thermostats of an
    account look for, by WG4 application code or WD5 customer ID. The option
    is only offered when it knows one; add a brand there once its hostname
    is known. One gateway per port: only one account per series can run one.
  - Ask the library's API what reaches a thermostat: `on_gateway()`,
    `cloud_reaches()` and `can_set()`. A change through the cloud for a
    thermostat that only the gateway reaches is refused, not sent: the cloud
    accepts it and never delivers it.
  - WD5: a relayed thermostat is set through the cloud, because the cloud
    keeps the mode of a group and ignores what a thermostat reports; the app
    would not show a preset the gateway set (seen on a real OWD5). The
    library chooses the route and lets the gateway step in when the cloud
    cannot be reached: the coordinator only passes its group update as
    `through_cloud`. Do not decide between cloud and gateway here.
  - A group update replaces every setting of the group, so with a gateway
    it fetches the cloud first (`refresh()`) and starts from the cloud's
    view of the thermostat (`cloud_thermostat()`). That way neither a change
    made in the app a moment ago is undone, nor a preset the gateway set on
    one thermostat spread over its group. What a change sets is worked out
    after that fetch, from the group it is handed (`GroupChanges`,
    `ScheduleEdit`): a value read before it would bring back what the fetch
    replaced.
  - What a thermostat on the gateway measures is `None` until its first
    report, about a minute after it connected: the cloud's value is not
    used, because the cloud does not hear from it in local only (a tester's
    sensors showed 0). Use `helpers.current_temperature()`, and give a sensor that
    can be without a value `create_for`, or it is not created at a restart.
  - The cloud counts the energy usage from the reports of a thermostat
    that OJ's gateway gets: minutes of heating times the load (compared
    with a power meter on an OWD5). The library tells what the other
    reports are worth (`on_usage`); `local.py` adds that up per hour (UTC)
    and stores it, for eight days. `EnergyStatistics.async_hourly()` adds
    it to the cloud's hours, so the two never count the same report. For
    a thermostat that only the gateway hears, in local only, it is the
    whole usage: `_async_count_here()` sets the sensor from it and
    `schedule_import_counted()` writes the statistics, from the last hour
    written on, without asking the cloud. Earlier hours are left alone:
    the cloud may have counted those.
  - The gateway counts with the load a thermostat knows, unless the user
    set one: the **Heating load** number (`number.py`), which the store
    keeps as `loads` and `LocalGateway.async_start()` hands to the library
    again. It shows the load that is counted with, and 0 clears it. It is
    only created with a local connection, because it changes nothing the
    cloud counts.
  - Ask the store to save the usage once per write (`_usage_unsaved`):
    `Store.async_delay_save()` puts a planned write off when it is asked
    again, and a report comes every minute.
  - The hub in `push.py` is not used while a gateway runs: it would report a
    thermostat offline that is only away from the cloud. Thermostats that
    are not on the gateway are polled every minute for that reason.
  - A cloud failure must not stop the thermostats on the gateway: a
    rejected password starts reauthentication without failing the update.
  - `_async_with_session` logs in on the cloud API (`local.api.cloud`);
    logging in through `WG4LocalAPI` does nothing.
  - The stored snapshot holds the account's email address, and a profile
    is specific to a thermostat. Neither belongs in diagnostics or logs, and
    both are deleted when the entry is back in cloud mode or has no local
    gateway. The store names its account (a hash): what was stored before a
    reconfigure to another account is not used. The hash is made of the
    settings as they are used, with their defaults, because a reconfigure
    writes out defaults that an older entry leaves out.
  - The store also keeps the serial numbers of the thermostats that
    connected (`known`). In local only they do not reach the cloud, which
    has to hold after a restart too, before they connect again. They are
    only forgotten with the store, by going back to cloud mode.
  - A WG4 thermostat that is relayed gets a manual temperature when the
    comfort mode fails because the cloud cannot be reached
    (`_gateway_sets_manual()`). That only holds where the gateway cannot
    set the comfort mode itself: where it can, the error may be that of a
    thermostat that did not answer.

## Tests

- Tests mock the HTTP API with Home Assistant's `aioclient_mock`, using JSON
  responses in `tests/fixtures/` copied from the library's tests. The
  `mock_wd5_api`, `mock_wg4_api` and `mock_wg5_api` fixtures register them.
- `conftest.py` imports the integration up front (pytest-homeassistant-custom-
  component ships its own `custom_components` package), skips the frontend
  and http dependencies, enables the recorder, and patches the delayed refresh
  and push subscriptions. Keep these fixtures.
- Add a test for every bug fix that fails without the fix.

## Pull requests and releases

- Every pull request needs one of these labels: `breaking-change`, `bugfix`,
  `hotfix`, `documentation`, `enhancement`, `refactor`, `performance`,
  `new-feature`, `maintenance`, `ci`, `dependencies`, `skip-changelog`.
- Release Drafter derives the next version from the labels
  (`breaking-change` → major, `new-feature` → minor, others → patch).
  Publishing a GitHub release runs `release.yaml`, which sets the version in
  `manifest.json` from the tag, zips the integration and attaches
  `ojmicroline_thermostat.zip` to the release; HACS installs that zip
  (`zip_release` in `hacs.json`). The version in `manifest.json` and
  `pyproject.toml` stays `0.0.0`.
- Renovate keeps dependencies up to date and automerges minor and patch
  updates.

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
| WD5 (OWD5, MWD5, WCD5) | `WD5API` | session API; push via the SignalR hub in `push.py`; schedule, vacation and energy history |
| WG4 (UWG4, AWG4) | `WG4API` | session API; push via the library's `subscribe()`; energy history and power |
| WG5 (UWG5) | `WG5API` | OAuth API; polled; experimental, not tested with a real thermostat |

```text
custom_components/ojmicroline_thermostat/
  __init__.py      setup, unload, version migration, schedule card registration
  api.py           creates the model API from config entry data
  config_flow.py   user, wd5/wg4/wg5, reauth, reconfigure and options flow
  coordinator.py   polling, push handling, session retry, WD5 group updates
  energy.py        long-term energy statistics (WD5, WG4)
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
- **Sessions**: the coordinator calls the WD5/WG4 API directly with the session
  ID. Wrap such calls in `_async_with_session`, which logs in again and retries
  once when the API rejects the session (HTTP 401).
- **Entities**: `_attr_has_entity_name = True` with a `translation_key`; the
  device is named after the thermostat. Keep entity IDs stable for existing
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
  (`breaking-change` → major). Bump `version` in `manifest.json` and
  `pyproject.toml` to match before a release.
- Renovate keeps dependencies up to date and automerges minor and patch
  updates.

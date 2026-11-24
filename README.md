<!-- PROJECT SHIELDS -->
[![hacs_badge][hacs-shield]][hacs-url]
![Project Stage][project-stage-shield]

![Project Maintenance][maintenance-shield]
[![Maintainability][maintainability-shield]][maintainability-url]

# OJ Microline Thermostat Integration for Home Assistant

Control your OJ Microline floor heating thermostats from Home Assistant: set the
temperature and preset, follow what the floor uses, and edit the weekly
schedule from a dashboard card.

![A thermostat and its weekly schedule in Home Assistant][screenshot]

## Supported thermostats

| Series | Models | Apps |
| --- | --- | --- |
| WD5 | OWD5, MWD5, WCD5 | OJ Microline (OWD5), SWATT, Schlüter HEAT CONTROL, Microtemp |
| WG4 | UWG4, AWG4 | OJ Microline (mythermostat.info), Danfoss LX, Schlüter DITRA-HEAT-E-WiFi |
| WG5 | UWG5 | OJ Microline, nJoy / WarmlyYours |

The thermostat needs to be connected to the internet, unless you use the
[local connection][docs-local].

| Feature | WD5 | WG4 | WG5 |
| --- | :---: | :---: | :---: |
| Temperature and presets | ✓ | ✓ | ✓ |
| Changes show up within seconds | ✓ | ✓ | every minute |
| [Energy statistics][docs-energy] | ✓ | ✓ | |
| [Power and energy price][docs-energy] | | ✓ | |
| [Weekly schedule and card][docs-schedule] | ✓ | ✓ ¹ | |
| [Vacation][docs-schedule] | ✓ | | |
| [Local connection][docs-local], without OJ's cloud | ✓ | ✓ | |

¹ Changing the schedule of a WG4-series thermostat needs the [local connection][docs-local].

## Installation

Requires Home Assistant 2026.10 or newer.

**HACS:** search for `OJ Microline Thermostat` on the HACS page and download it,
then restart Home Assistant.

**Manually:** download `ojmicroline_thermostat.zip` from the
[latest release](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/releases/latest)
and extract it into `<config directory>/custom_components/ojmicroline_thermostat/`,
then restart Home Assistant.

## Configuration

[![ha_badge][ha-add-shield]][ha-add-url]

Add the integration under **Settings → Devices & services**. Choose the series of
your thermostat, then the app you use with it, and log in with the username and
password of that app. Not sure which app or settings to pick? See
[Apps and login settings][docs-apps].

Each thermostat becomes a device with a climate entity and sensors for its
temperatures, mode and state. While a thermostat is offline, its climate entity
and sensors are unavailable; only the "Online" sensor keeps telling that it is
disconnected.

WD5 and WG4-series thermostats receive changes made on the thermostat or in the
app within seconds, through the same notification service the apps use; the
integration then polls only every 5 minutes as a fallback. When that connection
drops, it polls every minute until the connection is back. WG5-series
thermostats are polled every minute.

<a name="apps-for-wd5-series-thermostats"></a>
<a name="apps-for-wg4-series-thermostats"></a>
<a name="energy-statistics-wd5-and-wg4-series"></a>
<a name="local-connection-wg4-and-wd5-series"></a>
<a name="local-connection-wg4-and-wd5-series-experimental"></a>
<a name="schedule-and-vacation-wd5-series"></a>

## Documentation

- [Apps and login settings][docs-apps]: hosts, customer IDs and application codes per app.
- [Energy][docs-energy]: energy statistics, the energy dashboard, power and energy price.
- [Schedule and vacation][docs-schedule]: the schedule card, the weekly schedule of WG4-series thermostats, and the `set_schedule`, `set_vacation` and `cancel_vacation` actions.
- [Local connection][docs-local]: keep control when your internet or OJ's cloud is down.

## Contributing

Please see [CONTRIBUTING](.github/CONTRIBUTING.md) and [CODE_OF_CONDUCT](.github/CODE_OF_CONDUCT.md) for details.

## References & Thanks

- https://community.home-assistant.io/t/mwd5-wifi-thermostat-oj-electronics-microtemp/445601
- https://mdapp.medium.com/the-android-emulator-and-charles-proxy-a-love-story-595c23484e02
- https://github.com/radubacaran/mwd5
- https://github.com/klaasnicolaas
- https://github.com/adamjernst
- https://github.com/ViPeR5000

<!-- Absolute links, so they also work on the HACS page. -->
[docs-apps]: https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/blob/main/docs/apps.md
[docs-energy]: https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/blob/main/docs/energy.md
[docs-schedule]: https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/blob/main/docs/schedule.md
[docs-local]: https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/blob/main/docs/local-connection.md
[screenshot]: https://raw.githubusercontent.com/robbinjanssen/home-assistant-ojmicroline-thermostat/main/docs/images/dashboard.png

[maintainability-shield]: https://api.codeclimate.com/v1/badges/d77f7409eb02e331261b/maintainability
[maintainability-url]: https://codeclimate.com/github/robbinjanssen/python-ojmicroline-thermostat
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-stable-brightgreen.svg?style=for-the-badge

[hacs-url]: https://github.com/hacs/integration
[hacs-shield]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge

[ha-add-url]: https://my.home-assistant.io/redirect/config_flow_start/?domain=ojmicroline_thermostat
[ha-add-shield]: https://my.home-assistant.io/badges/config_flow_start.svg

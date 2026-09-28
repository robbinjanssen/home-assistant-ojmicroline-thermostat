<!-- PROJECT SHIELDS -->
[![hacs_badge][hacs-shield]][hacs-url]
![Project Stage][project-stage-shield]

![Project Maintenance][maintenance-shield]
[![Maintainability][maintainability-shield]][maintainability-url]

# OJ Microline Thermostat Integration for Home Assistant

The OJ Microline Thermostat integration allows you to control your
thermostat from Home Assistant.

It has been tested and developed on the following models:

## Supported models

| Model            |
|------------------|
| OWD5             |
| UWG4             |
| WCD5             |

After installation you can add the thermostat through the integration page. Currently setting a preset mode and temperature is supported. Adjusting
the HVAC mode will (re)set it to the schedule preset.

## Requirements

Your thermostat needs to be connected to the internet. For OWD5 model thermostats you will need the API key and customer ID that is used by the app that you currently use to control your thermostat.

## HACS installation

Add this integration using HACS by searching for `OJ Microline Thermostat` on the `Integrations` page.

## Manual installation

Create a directory called `ojmicroline_thermostat` in the `<config directory>/custom_components/` directory on your Home Assistant instance.
Install this integration by copying all files in `/custom_components/ojmicroline_thermostat/` folder from this repo into the new `<config directory>/custom_components/ojmicroline_thermostat/` directory you just created.

## Configuration

[![ha_badge][ha-add-shield]][ha-add-url]

To configure the integration, add it using [Home Assistant integrations][ha-add-url]. This will provide you with a configuration screen where you enter the customer ID, API key, username and password.

## Live updates (WD5 series)

WD5-series thermostats receive live updates through the same notification service the OJ Microline and SWATT apps use, so changes made on the thermostat or in the app show up in Home Assistant within seconds. While this connection is up, the integration polls only every 5 minutes (for energy usage and as a fallback); when it drops, polling returns to every minute and the connection is retried automatically.

## Energy statistics (WD5 series)

For every WD5-series thermostat the integration imports the energy usage history into a long-term statistic named "<thermostat> energy" (`ojmicroline_thermostat:energy_<serial>`): the last 12 months per month, the last 5 weeks per day and the last week per hour, kept up to date per hour from then on. Add it under **Settings → Dashboards → Energy → Individual devices** to see the usage per day, week, month and year, like the apps' statistics screen.

The "Energy Usage" sensor shows today's usage (from local midnight). Use either the statistic or the sensor in the energy dashboard, not both, or the usage is counted twice.

## Schedule and vacation (WD5 series)

Every WD5-series thermostat gets these extra entities. Like in the apps, schedule and vacation settings belong to the thermostat's group.

| Entity | Description |
| --- | --- |
| `sensor.<name>_schedule` | The temperature the weekly schedule prescribes right now. The attributes list every weekday's events (`time`, `temperature`, and `next_day` for events after midnight). |
| `date.<name>_vacation_begin` | The first day of the vacation. |
| `date.<name>_vacation_end` | The day normal regulation resumes (at 00:00). Moving one date past the other moves the other along. |
| `switch.<name>_vacation` | Enables the vacation period. If it has already started, vacation mode is activated immediately; switching it off returns to schedule or manual mode, whichever was used last. |

### Schedule card

The integration ships a dashboard card that shows the weekly schedule and highlights the event that is active right now. Tap a day to edit it: change, add or remove events, optionally apply the same events to other days, and save. It is loaded automatically: edit a dashboard, add a card and pick **OJ Microline schedule**, or use YAML:

```yaml
type: custom:ojmicroline-schedule-card
entity: sensor.living_room_schedule
title: Living room  # optional
climate_entity: climate.living_room  # optional; found via the device otherwise
```

### Services

| Service | Description |
| --- | --- |
| `ojmicroline_thermostat.set_schedule` | Set the events of one or more weekdays: up to 6 per day, on the quarter hour, at least 15 minutes apart, 5-40 °C. A time earlier than the previous one is after midnight (03:00 at the latest). The first event must be at 22:00 at the latest. |
| `ojmicroline_thermostat.set_vacation` | Set and enable a vacation from `start_date` until `end_date`. |
| `ojmicroline_thermostat.cancel_vacation` | Disable the vacation. |

```yaml
action: ojmicroline_thermostat.set_schedule
target:
  entity_id: climate.living_room
data:
  days: [monday, tuesday, wednesday, thursday, friday]
  events:
    - time: "06:00"
      temperature: 21
    - time: "08:30"
      temperature: 17
    - time: "17:00"
      temperature: 21
    - time: "22:30"
      temperature: 17
```

## Contributing

Please see [CONTRIBUTING](.github/CONTRIBUTING.md) and [CODE_OF_CONDUCT](.github/CODE_OF_CONDUCT.md) for details.

## References & Thanks

- https://community.home-assistant.io/t/mwd5-wifi-thermostat-oj-electronics-microtemp/445601
- https://mdapp.medium.com/the-android-emulator-and-charles-proxy-a-love-story-595c23484e02
- https://github.com/radubacaran/mwd5
- https://github.com/klaasnicolaas
- https://github.com/adamjernst
- https://github.com/ViPeR5000

[maintainability-shield]: https://api.codeclimate.com/v1/badges/d77f7409eb02e331261b/maintainability
[maintainability-url]: https://codeclimate.com/github/robbinjanssen/python-ojmicroline-thermostat
[maintenance-shield]: https://img.shields.io/maintenance/yes/2025.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-stable-brightgreen.svg?style=for-the-badge

[hacs-url]: https://github.com/hacs/integration
[hacs-shield]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge

[ha-add-url]: https://my.home-assistant.io/redirect/config_flow_start/?domain=ojmicroline_thermostat
[ha-add-shield]: https://my.home-assistant.io/badges/config_flow_start.svg

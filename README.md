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

| Model            | Series |
|------------------|--------|
| OWD5             | WD5    |
| WCD5             | WD5    |
| UWG4             | WG4    |
| UWG5             | WG5    |

After installation you can add the thermostat through the integration page. Currently setting a preset mode and temperature is supported. Adjusting
the HVAC mode will (re)set it to the schedule preset.

## Requirements

Your thermostat needs to be connected to the internet. For WD5 and WG4-series thermostats you need to know which app you use to control your thermostat, see [Apps for WD5-series thermostats](#apps-for-wd5-series-thermostats) and [Apps for WG4-series thermostats](#apps-for-wg4-series-thermostats).

This integration requires Home Assistant 2026.10 or newer.

## HACS installation

Add this integration using HACS by searching for `OJ Microline Thermostat` on the `Integrations` page.

## Manual installation

Create a directory called `ojmicroline_thermostat` in the `<config directory>/custom_components/` directory on your Home Assistant instance.
Download `ojmicroline_thermostat.zip` from the [latest release](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/releases/latest) and extract it into the new `<config directory>/custom_components/ojmicroline_thermostat/` directory you just created.

## Configuration

[![ha_badge][ha-add-shield]][ha-add-url]

To configure the integration, add it using [Home Assistant integrations][ha-add-url]. This will provide you with a configuration screen where you first choose the thermostat series and then enter your username and password (for the WD5 and WG4 series you first choose your app, which fills in its settings).

To change these settings later, for example after changing your password or to use another host, choose **Reconfigure** in the integration's menu.

### Apps for WD5-series thermostats

WD5-series thermostats are sold under several brands, each with its own app. The apps share one API key (`f219aab4-9ac0-4343-8422-b72203e2fac9`, used when you leave the field blank); they differ in host and customer ID. When you add a WD5-series account, choose your app to fill in these settings, or choose **Other** to enter them yourself. Use the username and password of the app.

| App | Host | Customer ID |
| --- | --- | --- |
| OJ Microline (OWD5 app) | (default) | `1` |
| SWATT | (default) | `99` |
| Schlüter HEAT CONTROL (Europe, DITRA-HEAT-E-WiFi and DITRA-HEAT-E-R6) | `owd5-sl003-app.ojelectronics.com` | `3` |
| Microtemp | `owd5-mh015-app.ojelectronics.com` | `111` |

The Schlüter and Microtemp settings were reported by users ([#466](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/issues/466) and the Home Assistant forum: [Schlüter R6](https://community.home-assistant.io/t/schluter-ditra-heat-home-assistant-integration/185275/65), [Microtemp](https://community.home-assistant.io/t/mwd5-wifi-thermostat-oj-electronics-microtemp/445601)); the maintainers have not tested them.

If the login fails, try the customer ID of another app (1, 99 or 3). The customer ID belongs to the app your account was created with, which is not always the number the app shows under thermostat data (the Schlüter app shows 33, for example). Does your app work with other settings? Open an issue with them, so they can be added.

### Apps for WG4-series thermostats

WG4-series thermostats are also sold under several brands. Their apps differ in host and application code. When you add a WG4-series account, choose your app to fill in these settings, or choose **Other** to enter them yourself. Use the email address and password of the app.

| App | Host | Application code |
| --- | --- | --- |
| OJ Microline (mythermostat.info) | (default) | `2` |
| Danfoss LX | `lxwifi.danfoss.us` | `4` |
| Schlüter DITRA-HEAT-E-WiFi (North America) | `ditra-heat-e-wifi.schluter.com` | `7` |

The Danfoss and Schlüter settings were reported by users ([#441](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/issues/441), [#469](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/issues/469)); the maintainers have not tested them. With the wrong application code the login succeeds, but the account has no thermostats; the integration then asks you to check the app.

## Live updates (WD5 and WG4 series)

WD5-series thermostats receive live updates through the same notification service the OJ Microline and SWATT apps use, so changes made on the thermostat or in the app show up in Home Assistant within seconds. While this connection is up, the integration polls only every 5 minutes (for energy usage and as a fallback); when it drops, polling returns to every minute and the connection is retried automatically.

WG4-series thermostats receive live updates through the notification long-poll of the mythermostat.info API, provided by the `ojmicroline-thermostat` library. Changes arrive within seconds and periodic temperature reports about every minute. While subscribed, the integration polls only every 5 minutes as a fallback; failed requests are retried automatically with an increasing delay.

## Energy statistics (WD5 and WG4 series)
For every WD5 and WG4-series thermostat the integration imports the energy usage history into a long-term statistic named "<thermostat> energy" (`ojmicroline_thermostat:energy_<serial>`): the last 12 months per month, the last 5 weeks per day and the last week per hour, kept up to date per hour from then on. Add it under **Settings → Dashboards → Energy → Individual devices** to see the usage per day, week, month and year, like the apps' statistics screen.

The "Energy Usage" sensor shows today's usage (from local midnight). Use either the statistic or the sensor in the energy dashboard, not both, or the usage is counted twice.

## Power (WG4 series)

For WG4-series thermostats, energy usage is taken from the "Energy Use" page of mythermostat.info, where the usage of each hour is added once that hour has ended. The "Power" sensor shows the power draw of the floor heating: the load of the heating element, as reported by the thermostat (measured, or configured on the thermostat if load measuring is off), while the thermostat is heating, and 0 W otherwise.

## Energy price (WG4 series)

WG4-series thermostats store the price per kWh that the app uses to show the energy costs. The integration shows it as `number.<name>_energy_price`, in the currency set in Home Assistant, and you can change it there. The thermostat keeps two decimals: the cloud accepts more, but the thermostat truncates the price at its next sync.

The entity is disabled by default: the cloud applies a new price to all stored usage, including earlier days, so the costs in the app are only right for one constant price. Do not use it to follow changing tariffs; Home Assistant's energy dashboard tracks costs with changing prices itself.

## Local connection (WG4 and WD5 series, experimental)

A thermostat keeps a connection open to OJ's own gateway. With a DNS record on your network that points the name of that gateway at Home Assistant, the thermostat connects to Home Assistant instead, and keeps working when your internet or OJ's cloud is down. Nothing on the thermostat changes, and removing the record undoes it.

| Series | Name the thermostat looks for | Port |
| --- | --- | --- |
| WG4 | `na-thermos.ojelectronics.com` | 9533 |
| WD5, SWATT app (customer ID 99) | `owd5-r1099-thermostat.ojelectronics.com` | 9513 |
| WD5, Schlüter in Europe (customer ID 3) | `owd5-sl003-thermostat.ojelectronics.com` | 9513 |

For a WD5-series account of another app the name is not known yet, and the connection option is not shown. If you find the name in the DNS log of your router, please report it.

**This is experimental.** Stay on the cloud connection unless you are comfortable editing DNS on your network, and please report what you find.

- **WG4 series:** tested on one real thermostat. Connecting, the relay and local only work. A temperature set from Home Assistant was confirmed by the thermostat too late, so Home Assistant showed an error; that is being worked on.
- **WD5 series:** not confirmed on a real thermostat with this integration yet. The protocol comes from an ioBroker adapter where it works on an OWD5 thermostat.

Choose the connection under **Configure** in the integration's menu:

| Connection | Setup | The app | When your internet is down |
| --- | --- | --- | --- |
| **Cloud** (default) | None | Works | Home Assistant loses the thermostat |
| **Local with relay** | DNS record | Works | Home Assistant keeps control |
| **Local only** | DNS record; for the WG4 series after the relay has been used once | Shows the thermostat offline | Nothing changes |

With the relay, Home Assistant passes the thermostat's connection on to OJ's gateway, so the app keeps working. For a WG4-series thermostat it also records how OJ's gateway answers the thermostat. Home Assistant needs those answers to serve that thermostat itself, which is why local only works after it has connected through the relay once. A WD5-series thermostat needs nothing recorded.

### Setting it up

1. Give Home Assistant a fixed IP address, with a DHCP reservation on your router.
2. On the DNS server your thermostats use, add a record that points the name from the table above at that address. Pi-hole and AdGuard Home (also available as a Home Assistant add-on) call this a local DNS record or DNS rewrite. Many routers of internet providers cannot do this. Redirect only this name: it is the one the thermostat connects to, not the name of the app or the website.
3. Under **Configure**, choose **Local with relay**. The next screen shows the record to create, and warns if Home Assistant does not see it.
4. Switch each thermostat off and on again, so it looks up the address again. Changing the DNS record does not move the connection a thermostat already has. A factory reset is not needed: the thermostat keeps its Wi-Fi settings and its schedule.

If no thermostat has connected after ten minutes, a repair issue under **Settings → System → Repairs** tells you what to check. It disappears when a thermostat connects.

To go back, choose **Cloud**, remove the DNS record and switch the thermostats off and on again.

### What changes in a local mode

- The temperature, the mode and whether the floor is heating come straight from the thermostat, and a new temperature goes straight to it.
- **WG4 series:** the schedule and manual presets are set on the thermostat directly. The comfort preset and the energy usage still need the cloud, so they only work with the relay, while the internet is up. In local only, the option to use comfort mode when changing the temperature is ignored.
- **WD5 series:** the schedule, comfort, manual, boost and eco presets are set on the thermostat directly. Frost protection, the vacation, changes to the weekly schedule and the energy usage still need the cloud, so they only work with the relay, while the internet is up.
- **WD5 series:** the cloud sets a preset for every thermostat in a group. A preset that goes straight to a thermostat only changes that thermostat.
- **WD5 series:** a thermostat on the same account that does not connect to Home Assistant is no longer updated right away, but once every five minutes.
- "Online" means the thermostat is connected to Home Assistant.
- A thermostat on the same account that never connected to Home Assistant, for example one in another building, keeps working through the cloud.
- With the DNS record in place, the app only works while Home Assistant is running.
- The port from the table above has to be free on the machine that runs Home Assistant, and reachable for the thermostats. With Home Assistant in a container, use host networking or publish the port. Every device on your network can reach it: use a local mode only on a network you trust, and do not open the port to the internet.
- If OJ's gateway ever shows another certificate than the one this integration knows, nothing is passed on to it and a repair issue tells you. Thermostats that connected before are then served by Home Assistant.

### Reporting how it goes

A local mode has not been confirmed on a real thermostat yet, so a report helps, whether it works or not. Two things show what happened:

- **Diagnostics.** Under **Settings → Devices & services → OJ Microline Thermostat**, open the **⋮** menu and choose **Download diagnostics**. The `gateway` part holds the last 300 events: every connection and whether its TLS handshake succeeded, every message between thermostat and gateway by field number and decoded temperature, each command and its answer, and why OJ's gateway could not be used. Attach the file to an [issue](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/issues).
- **Debug logging.** In the same menu, choose **Enable debug logging**, reproduce the problem, and disable it again to download the log. It has the same events without the limit of 300.

Both name the serial number of your thermostat and its address on your network. Neither contains your email address or password: a login is never written down.

What a first report should answer:

- Is there a line `Connection from …, secured with …`? If the thermostat connects but the line says `The TLS handshake … failed`, the thermostat does not accept the connection. If there is no line at all, the DNS record does not reach the thermostat.
- Is there a line `Thermostat … logged in; it is relayed to OJ's gateway`, and does the app keep working?
- Does `Recorded the profile of thermostat …` show up? Local only needs it.
- After changing the temperature in Home Assistant: is `Sending command …` followed by `acknowledged command …`, and does the thermostat follow?

The gateway is part of the [`ojmicroline-thermostat`](https://github.com/robbinjanssen/python-ojmicroline-thermostat) library and builds on [peskyAdmin/schluter-local](https://github.com/peskyAdmin/schluter-local).

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
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-stable-brightgreen.svg?style=for-the-badge

[hacs-url]: https://github.com/hacs/integration
[hacs-shield]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge

[ha-add-url]: https://my.home-assistant.io/redirect/config_flow_start/?domain=ojmicroline_thermostat
[ha-add-shield]: https://my.home-assistant.io/badges/config_flow_start.svg

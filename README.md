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

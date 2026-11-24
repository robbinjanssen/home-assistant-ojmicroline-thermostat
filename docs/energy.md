# Energy

## Energy statistics (WD5 and WG4 series)

For every WD5 and WG4-series thermostat the integration imports the energy usage history into a long-term statistic named "<thermostat> energy" (`ojmicroline_thermostat:energy_<serial>`): the last 12 months per month, the last 5 weeks per day and the last week per hour, kept up to date per hour from then on. Add it under **Settings → Dashboards → Energy → Individual devices** to see the usage per day, week, month and year, like the apps' statistics screen.

The "Energy Usage" sensor shows today's usage (from local midnight). Use either the statistic or the sensor in the energy dashboard, not both, or the usage is counted twice.

For WG4-series thermostats, energy usage is taken from the "Energy Use" page of mythermostat.info, where the usage of each hour is added once that hour has ended.

## Counting with a local connection

With a [local connection](local-connection.md), Home Assistant counts the usage itself wherever OJ's cloud does not hear the thermostat: in local only, and with the relay while OJ's cloud is unreachable. It counts the way the cloud does: the time a thermostat reports that its floor is heating, times the load of the heating. With the relay, what Home Assistant counted is added to what the cloud counted.

- A power meter confirmed this way of counting on an OWD5 thermostat: over four hours, what the cloud counted was within a percent of what the house drew for the floor. Home Assistant's own count is new, and on a WG4-series thermostat nothing has been compared yet.
- It is as good as the load it counts with. A WD5-series thermostat tells its load itself; for a WG4-series thermostat it comes from the cloud. That load was entered at the installation or measured by the thermostat, and a floor can draw something else: on an OWD5 thermostat a power meter showed 3900 W where the thermostat told 4010 W. The real draw also moves a few percent with the mains voltage.
- **Heating load.** Every thermostat of an account with a local connection has a **Heating load** setting, in W. It shows the load of the thermostat until you enter another one, which Home Assistant counts with from then on; enter 0 to go back to the load of the thermostat. It only changes what Home Assistant counts itself: the cloud keeps counting with the load of the thermostat. On a WD5-series thermostat you can also change the load in the menu of the thermostat itself, which changes both; Home Assistant takes that over within a minute.
- The count runs a few percent long when the floor switches on and off every few minutes: a report counts for the whole minute before it. Over an evening of ten-minute cycles it counted 3% more heating time than a power meter saw. The cloud counts the same reports.
- A thermostat only reports once a minute, so what it used while Home Assistant was not running, or in the minutes around a restart, is not counted.
- On the day you switch to local only, the sensor starts again from the moment of the switch. The statistic keeps what the cloud counted before.
- Usage is not counted while the load of the thermostat is not known; the sensor then stays unknown.

## Power (WG4 series)

The "Power" sensor shows the power draw of the floor heating: the load of the heating element, as reported by the thermostat (measured, or configured on the thermostat if load measuring is off), while the thermostat is heating, and 0 W otherwise.

## Energy price (WG4 series)

WG4-series thermostats store the price per kWh that the app uses to show the energy costs. The integration shows it as `number.<name>_energy_price`, in the currency set in Home Assistant, and you can change it there. The thermostat keeps two decimals: the cloud accepts more, but the thermostat truncates the price at its next sync.

The entity is disabled by default: the cloud applies a new price to all stored usage, including earlier days, so the costs in the app are only right for one constant price. Do not use it to follow changing tariffs; Home Assistant's energy dashboard tracks costs with changing prices itself.

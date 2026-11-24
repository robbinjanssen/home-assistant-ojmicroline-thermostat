# Local connection (WG4 and WD5 series)

A thermostat keeps a connection open to OJ's own gateway. With a DNS record on your network that points the name of that gateway at Home Assistant, the thermostat connects to Home Assistant instead, and keeps working when your internet or OJ's cloud is down. Nothing on the thermostat changes, and removing the record undoes it.

Stay on the cloud connection unless you are comfortable editing DNS on your network.

- [Which thermostats](#which-thermostats)
- [Choosing a connection](#choosing-a-connection)
- [Setting it up](#setting-it-up)
- [What changes in a local mode](#what-changes-in-a-local-mode)
- [What it has been tested on](#what-it-has-been-tested-on)
- [Reporting how it goes](#reporting-how-it-goes)

## Which thermostats

| Series | Name the thermostat looks for | Port |
| --- | --- | --- |
| WG4, OJ Microline (mythermostat.info) or Schlüter in North America | `na-thermos.ojelectronics.com` | 9533 |
| WD5, SWATT app (customer ID 99) | `owd5-r1099-thermostat.ojelectronics.com` | 9513 |
| WD5, Schlüter in Europe (customer ID 3) | `owd5-sl003-thermostat.ojelectronics.com` | 9513 |
| WD5, OJ Microline app (OWD5, customer ID 1) | `owd5-oj001-thermostat.ojelectronics.com` | 9513 |

For an account of another app, such as Danfoss LX or Microtemp, the name is not known yet, and the connection option is not shown. If you find the name in the DNS log of your router, please report it.

The name the thermostat looks for is not the host in the integration's settings. That host, such as `owd5-sl003-app.ojelectronics.com`, is the cloud API that Home Assistant and the app use; do not point it at Home Assistant.

Only one account per series can use a local connection, because the thermostats of a series all connect to the same port.

## Choosing a connection

Choose the connection under **Configure** in the integration's menu:

| Connection | Setup | The app | When your internet is down |
| --- | --- | --- | --- |
| **Cloud** (default) | None | Works | Home Assistant loses the thermostat |
| **Local with relay** | DNS record | Works | Home Assistant keeps control |
| **Local only** | DNS record; for the WG4 series after the relay has been used once | Shows the thermostat offline | Nothing changes |

With the relay, Home Assistant passes the thermostat's connection on to OJ's gateway, so the app keeps working. For a WG4-series thermostat it also records how OJ's gateway answers the thermostat. Home Assistant needs those answers to serve that thermostat itself, which is why local only works after it has connected through the relay once. A WD5-series thermostat needs nothing recorded.

## Setting it up

1. Give Home Assistant a fixed IP address, with a DHCP reservation on your router.
2. On the DNS server your thermostats use, add a record that points the name from the table above at that address. Pi-hole and AdGuard Home (also available as a Home Assistant add-on) call this a local DNS record or DNS rewrite. Many routers of internet providers cannot do this. Redirect only this name: it is the one the thermostat connects to, not the name of the app or the website.
3. Under **Configure**, choose **Local with relay**. The next screen shows the record to create, and warns if Home Assistant does not see it. It suggests the address Home Assistant uses to reach the internet. The gateway listens on every address, so the record may point at any IPv4 address of the machine that your thermostats can reach, for example a second one on the network your thermostats are on. Home Assistant reads its addresses when it starts, so after adding one, restart Home Assistant before this screen recognises a record that points at it.
4. Switch each thermostat off and on again, so it looks up the address again. Changing the DNS record does not move the connection a thermostat already has. A factory reset is not needed: the thermostat keeps its Wi-Fi settings and its schedule.

If no thermostat has connected after ten minutes, a repair issue under **Settings → System → Repairs** tells you what to check. It disappears when a thermostat connects.

To go back, choose **Cloud**, remove the DNS record and switch the thermostats off and on again. Home Assistant then deletes what it stored for the local connection: the last answer of the cloud, which holds the email address of the account, and the recorded answers of OJ's gateway. Local only for a WG4-series thermostat then needs the relay once more.

## What changes in a local mode

### Control

- The temperature, the mode and whether the floor is heating come straight from the thermostat, and a new temperature goes straight to it.
- **WG4 series:** the schedule and manual presets are set on the thermostat directly. The comfort preset still needs the cloud, so it only works while the thermostat is relayed: with the relay, while the internet is up. Without that, the option to use comfort mode when changing the temperature is ignored. When the thermostat is relayed but the cloud cannot be reached, a new temperature becomes a manual one, which stays until you change the preset; Home Assistant logs a warning when that happens.
- **WG4 series, local only:** a thermostat that has not connected through the relay yet cannot be answered. The setup screen names such thermostats before you switch.
- **WD5 series, with the relay:** presets still go through the cloud, as in cloud mode, so the app shows them: the cloud ignores a preset that a thermostat reports itself. The cloud sets a preset for every thermostat in a group. Only when the cloud cannot be reached does Home Assistant set the schedule, comfort, manual, boost, eco and frost protection presets on the thermostat directly; the app does not see those.
- **WD5 series, local only, or with the relay while OJ's cloud is unreachable:** the schedule, comfort, manual, boost, eco and frost protection presets are set on the thermostat directly, and only change that thermostat. The vacation and changes to the weekly schedule need the cloud, so Home Assistant refuses them instead of sending them to a cloud that cannot pass them on. A later change of the group in the cloud starts from the preset the cloud knows for the group.
- The energy usage of a thermostat that the cloud does not hear is counted by Home Assistant, see [Counting with a local connection](energy.md#counting-with-a-local-connection).

### Status and updates

- "Online" means the thermostat is connected to Home Assistant. A thermostat that loses power or its network is shown offline within 100 seconds: it only reports once a minute, and nothing tells Home Assistant sooner that a silent connection is gone.
- A thermostat reports its temperature about once a minute. Right after it connected, for example after a restart of Home Assistant, the measured temperature is unknown until that first report.
- A thermostat on the same account that does not connect to Home Assistant is no longer updated right away, but once a minute.
- A thermostat on the same account that never connected to Home Assistant, for example one in another building, keeps working through the cloud.
- **Local only:** a thermostat that connected to Home Assistant once is expected there from then on, also after a restart. If you later let it connect to OJ's cloud again, choose **Cloud** once, so Home Assistant forgets it, and then **Local only** again.

### Network and security

- With the DNS record in place, the app only works while Home Assistant is running.
- The port from the table above has to be free on the machine that runs Home Assistant, and reachable for the thermostats. With Home Assistant in a container, use host networking or publish the port. Every device on your network can reach it: use a local mode only on a network you trust, and do not open the port to the internet.
- If OJ's gateway ever shows another certificate than the one this integration knows, nothing is passed on to it and a repair issue tells you. Thermostats that connected before are then served by Home Assistant.

## What it has been tested on

This is what the local connection has run on so far; please report what you find, most of all on another model or brand:

- **WG4 series:** tested on four real thermostats of two users. Connecting, the relay, local only, and falling back to local while OJ's cloud was unreachable work. In the first test on one thermostat it confirmed a temperature set from Home Assistant too late, so Home Assistant showed an error. In the second test it confirmed every change within a few seconds. Why the two tests differed is not known yet. On three UWG4 thermostats of the second user the relay worked at once: the app, Home Assistant and the thermostat itself each follow the others.
- **WD5 series:** tested on OWD5 thermostats of four users, with firmware 1013W213 and 1013W220, with the relay and in local only: connecting, the relay, presets and falling back to local while OJ's cloud was unreachable work. The protocol comes from an ioBroker adapter where it works on an OWD5 thermostat.
- **Not tested yet:** Schlüter thermostats in North America, and the other models of both series.

## Reporting how it goes

The local connection has only run on a few thermostats, so a report helps, whether it works or not. Two things show what happened:

- **Diagnostics.** Under **Settings → Devices & services → OJ Microline Thermostat**, open the **⋮** menu and choose **Download diagnostics**. The `gateway` part holds the last 300 events: every connection and whether its TLS handshake succeeded, every message between thermostat and gateway by field number and decoded temperature, each command and its answer, and why OJ's gateway could not be used. The times are in UTC. `history_before_reload` holds the events from before the integration was last reloaded, so a reload does not lose them; a restart of Home Assistant does. A command that a thermostat did not answer or refused also shows as a warning in the Home Assistant log. Attach the file to an [issue](https://github.com/robbinjanssen/home-assistant-ojmicroline-thermostat/issues).
- **Debug logging.** In the same menu, choose **Enable debug logging**, reproduce the problem, and disable it again to download the log. It has the same events without the limit of 300.

Both name the serial number of your thermostat and its address on your network. Neither contains your email address or password: a login is never written down.

What a first report should answer:

- Is there a line `Connection from …, secured with …`? If the thermostat connects but the line says `The TLS handshake … failed`, the thermostat does not accept the connection. If there is no line at all, the DNS record does not reach the thermostat.
- Is there a line `Thermostat … logged in; it is relayed to OJ's gateway`, and does the app keep working?
- Does `Recorded the profile of thermostat …` show up? Local only needs it.
- After changing the temperature in Home Assistant: is `Sending command …` followed by `acknowledged command …`, and does the thermostat follow?

The gateway is part of the [`ojmicroline-thermostat`](https://github.com/robbinjanssen/python-ojmicroline-thermostat) library and builds on [peskyAdmin/schluter-local](https://github.com/peskyAdmin/schluter-local).

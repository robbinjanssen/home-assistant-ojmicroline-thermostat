# Experimental WG4 local control

This optional backend hosts the thermostat's TLS gateway inside Home Assistant.
It was tested on one mythermostat.info WG4 thermostat running firmware
`1012M201`. Other firmware, brands, multiple thermostats per account, and
multiple local accounts are not supported by this initial implementation.
Cloud mode remains the default for every existing installation.

The thermostat connects to `na-thermos.ojelectronics.com` on TCP port 9533.
A LAN DNS override sends that connection to Home Assistant. This emulates the
device gateway, rather than the mythermostat.info website or its REST API.
There is no separate relay process, add-on, or container to maintain, and the
local backend does not forward traffic to the manufacturer's server.

## Preparation and private profile

This is an advanced, experimental setup. It requires a configuration and support
response captured from **your own thermostat's working cloud connection**.
There is no automatic capture wizard in this release. Do not enable local mode
without a verified profile. The protocol implementation was adapted from
[peskyAdmin/schluter-local](https://github.com/peskyAdmin/schluter-local), but
that project's fixed Schlüter configuration is not suitable for every WG4.

A profile is a JSON object with four string fields:

- `serial_sha256`: lowercase SHA-256 of the thermostat serial encoded as UTF-8.
- `firmware`: the exact cloud metadata `SWVersion` string.
- `configuration`: hex of the complete original server frame containing field 10.
- `support`: hex of the complete original server frame containing field 18.

Frames include the `08` marker and unsigned varint length prefix. Only the
configuration/support root message types are accepted. Do not import someone
else's frames or invent settings for an untested thermostat. Capturing requires
observing the startup exchange through a temporary TLS forwarding gateway,
then restoring the original DNS route until local setup is ready. Keep original
server authentication verified or certificate-pinned in any capture tooling.
Never publish raw login frames, account details, serials, certificates/private
keys, or captured configuration. This repository intentionally includes no
real device profile or packet capture.

Place the profile at `/config/ojmicroline_thermostat/local_profile.json`, or
`/config/ojmicroline_thermostat/<config-entry-id>.profile.json`. Home Assistant
imports it to its private `.storage` directory, outside the integration folder.
The initial prototype's bundled profile is also migrated automatically if it
still exists. Back up the imported profile before replacing that prototype.

## Enable local mode

1. Set up the existing WG4 integration normally, while the cloud is reachable.
   Keep the same configuration entry and entity registry.
2. Import the verified profile as described above.
3. In the integration's **Configure** options, select **Use local WG4 gateway**.
   The first local setup reads cloud metadata once and saves it privately.
   Later starts load this cache and make no cloud requests.
4. Reserve a stable LAN address for Home Assistant. Make TCP 9533 reachable
   from the thermostat, including across VLANs if applicable. Container users
   need a published port or host networking. Do not expose this port publicly.
5. Override `na-thermos.ojelectronics.com` in the DNS server actually used by
   the thermostat to the Home Assistant address. The observed device used this
   North American hostname; verify other products before changing DNS.
6. Power-cycle the thermostat normally if necessary for a fresh connection.
   Do not factory-reset it. Wait for its state, schedule, and telemetry upload.

The integration retains its domain, unique IDs, entity IDs, history, and cards.
Existing cloud accounts are unaffected unless their local option is selected.
The manifest still declares the cloud integration's static `cloud_push` class;
Home Assistant can therefore display an internet-related classification even
while this backend is operating locally.

## Available features and limits

Local mode provides current temperature, heating status, target temperature,
manual mode, and resuming the thermostat's stored schedule. Physical thermostat
changes are pushed to Home Assistant. Commands require a connected device,
fresh state/schedule templates, configured temperature limits, and a device
acknowledgement. Unsent commands are cancelled rather than saved for a later
reconnection. Manual mode follows the integration's existing behavior: entering
manual uses the current target temperature.

Temporary comfort holds, vacation commands, and cloud energy
history are not implemented locally. Energy and hold/vacation timestamps are
unavailable, rather than presenting cached data as current. A power estimate is
only usable if the cached metadata contains a valid measured/configured load;
local telemetry does not provide a verified wattage or energy total. Use a
separate meter for measured power and energy. Cloud-app control is unavailable
while the thermostat connects to Home Assistant.

## Weekly schedule editor

Local WG4 devices get a `sensor.<name>_schedule` entity as soon as the gateway
receives a compatible seven-day schedule. Add the bundled dashboard card:

```yaml
type: custom:ojmicroline-schedule-card
entity: sensor.your_thermostat_schedule
climate_entity: climate.your_thermostat
```

Tap a weekday to edit its active events. Set times and temperatures, select
additional days under **Also apply to**, and save. Selecting every day applies
the same pattern all week. The card displays and edits Fahrenheit or Celsius
according to HA's unit settings. The underlying `set_schedule` service continues
to use Celsius, as its existing WD5 interface does.

The tested WG4 schedule has seven ISO weekdays (1 Monday to 7 Sunday), six
slots per day, and Celsius x100 schedule temperatures. Hold commands use a
different x200 scale. Slot zero stays active; inactive slots are retained where
possible, with existing active slots preferred during edits. Unknown fields,
other weekdays, regulation mode, and hold temperatures are preserved. The
editor supports one to six active events, in increasing same-day order on
quarter hours, within the device's configured temperature limits. WD5's
cross-midnight event behavior is not assumed for WG4.

A save requires a device acknowledgement and a matching schedule uploaded by
the thermostat. The firmware uploads its stored schedule on reconnect, so a
changed schedule triggers a brief reconnect and the card waits for readback.
This can take about a minute; keep the editor open while it checks. The
schedule and state update timestamps are refreshed together in the command.
An acknowledgement by itself is insufficient. If confirmation
times out, the card shows an error: refresh the schedule before retrying,
since a sent command might already have been applied. Unavailable schedules
cannot be edited. Keep an HA backup before making substantial schedule changes.

## Keeping it running

The listener starts automatically with the integration and stops on unload.
After HA or thermostat restarts the thermostat reconnects automatically. Wi-Fi
loss and missing heartbeats mark the device offline. During HA downtime the
thermostat continues its own stored schedule; remote HA changes must wait.

Back up the entire Home Assistant configuration, including hidden `.storage`,
`/config/ojmicroline_thermostat/`, and the custom integration. The private files
include cached account metadata, the device profile, and the gateway TLS
certificate/key. Do not attach them to public bug reports. There is no periodic
relay command, login renewal, or scheduled restart to run. Keep the reserved HA
address and DNS override intact. Re-capture/revalidate the profile after a
thermostat firmware change; a metadata/profile mismatch prevents startup.

Only one listener can bind TCP 9533. Stop any experimental gateway before using
this backend. For trouble, check the integration log, DNS route, TCP reachability,
and device Wi-Fi; reload the integration and wait for reconnection.

## Recovery

To return to cloud control, remove the thermostat-host DNS override, disable
**Use local WG4 gateway**, and reconnect/power-cycle the thermostat normally.
Do not delete the HA integration or its entities. Keep a known-working release
and an HA backup for rollback. Cached cloud metadata is required for offline
startup; deleting `.storage` would require the cloud again to rebuild it.

## Development evidence and attribution

Validation includes a physical-device local-only temperature command with
acknowledgement and reported state, restoring schedule mode, an HA Core restart,
and native HA preset changes. Automated tests use synthetic identity/profile
fixtures and exercise framed protobuf messages, Celsius scales, command fields,
connection replacement, malformed input, private profile import, cached offline
HA setup, stable entity identity, service calls, reload/unload, and rejection
of mismatched profiles and unsupported commands.

The adapted protocol gateway retains the MIT notice in
`custom_components/ojmicroline_thermostat/LOCAL_GATEWAY_LICENSE`. The cloud
library continues to own the unchanged cloud API implementation; this backend
owns the optional HA-hosted device listener.

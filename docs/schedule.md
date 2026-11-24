# Schedule and vacation

WD5-series thermostats get a weekly schedule and a vacation. Like in the apps,
these belong to the thermostat's group. They stay available while a thermostat
is offline, because the cloud keeps those settings.

## Entities (WD5 series)

| Entity | Description |
| --- | --- |
| `sensor.<name>_schedule` | The temperature the weekly schedule prescribes right now. The attributes list every weekday's events (`time`, `temperature`, and `next_day` for events after midnight). |
| `date.<name>_vacation_begin` | The first day of the vacation. |
| `date.<name>_vacation_end` | The day normal regulation resumes (at 00:00). Moving one date past the other moves the other along. |
| `switch.<name>_vacation` | Enables the vacation period. If it has already started, vacation mode is activated immediately; switching it off returns to schedule or manual mode, whichever was used last. |

## Schedule card

The integration ships a dashboard card that shows the weekly schedule and highlights the event that is active right now.

<img src="images/schedule-card.png" alt="The schedule card" width="500">

Tap a day to edit it: change, add or remove events, optionally apply the same events to other days, and save.

<img src="images/schedule-card-edit.png" alt="Editing a day in the schedule card" width="500">

It is loaded automatically: edit a dashboard, add a card and pick **OJ Microline schedule**, or use YAML:

```yaml
type: custom:ojmicroline-schedule-card
entity: sensor.living_room_schedule
title: Living room  # optional
climate_entity: climate.living_room  # optional; found via the device otherwise
```

## Actions

| Action | Description |
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

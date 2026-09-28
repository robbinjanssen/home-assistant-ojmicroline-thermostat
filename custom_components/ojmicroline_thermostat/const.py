"""Constants for the OJMicroline component."""

DOMAIN = "ojmicroline_thermostat"
MANUFACTURER = "OJ Electronics"
INTEGRATION_NAME = "OJ Microline Thermostat"
CONFIG_FLOW_VERSION = 2

API_TIMEOUT = 30
UPDATE_INTERVAL = 60
# Polling interval while push updates are connected (WD5 series).
PUSH_UPDATE_INTERVAL = 300
# Rate limiting: energy usage changes slowly, so fetch it (one request per
# thermostat) at most this often, and space out extra refresh requests.
ENERGY_UPDATE_INTERVAL = 1800
REFRESH_COOLDOWN = 30
# "Action" value in pushed thermostat data for an update (1 = add, 3 = remove).
PUSH_ACTION_UPDATE = 2

CONF_MODEL = "model"
CONF_CUSTOMER_ID = "customer_id"
CONF_APPLICATION = "application"
CONF_USE_COMFORT_MODE = "use_comfort_mode"
CONF_COMFORT_MODE_DURATION = "comfort_mode_duration"

MODEL_WD5_SERIES = "WD5 series"
MODEL_WG4_SERIES = "WG4 series"

# The application code sent on WG4 login. Standard WG4 thermostats use 2
# (the library default); Danfoss LX (lxwifi.danfoss.us) requires 4.
DEFAULT_WG4_APPLICATION = 2

PRESET_SCHEDULE = "schedule"
PRESET_MANUAL = "manual"
PRESET_VACATION = "vacation"
PRESET_FROST_PROTECTION = "frost_protection"

MODE_FLOOR = "Floor"
MODE_ROOM = "Room"
MODE_ROOM_FLOOR = "Room/Floor"

SERVICE_SET_VACATION = "set_vacation"
SERVICE_CANCEL_VACATION = "cancel_vacation"
SERVICE_SET_SCHEDULE = "set_schedule"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"
ATTR_DAYS = "days"
ATTR_EVENTS = "events"
ATTR_TIME = "time"

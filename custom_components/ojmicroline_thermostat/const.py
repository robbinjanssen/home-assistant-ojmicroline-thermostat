"""Constants for the OJMicroline component."""
DOMAIN = "ojmicroline_thermostat"
MANUFACTURER = "OJ Electronics"
INTEGRATION_NAME = "OJ Microline Thermostat"
CONFIG_FLOW_VERSION = 2

API_TIMEOUT = 30
UPDATE_INTERVAL = 60

CONF_CUSTOMER_ID = "customer_id"
CONF_DEFAULT_HOST = "ocd5.azurewebsites.net"
CONF_DEFAULT_CUSTOMER_ID = 99
CONF_USE_COMFORT_MODE = "use_comfort_mode"
CONF_COMFORT_MODE_DURATION = "comfort_mode_duration"

PRESET_VACATION = "Vacation"
PRESET_FROST_PROTECTION = "Frost Protection"

MODE_FLOOR = "Floor"
MODE_ROOM = "Room"
MODE_ROOM_FLOOR = "Room/Floor"

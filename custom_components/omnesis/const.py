"""Constants for the Omnesis integration."""

from typing import Final

DOMAIN: Final = "omnesis"

CONF_FINGERPRINT: Final = "fingerprint"
CONF_PAIRING_CODE: Final = "pairing_code"
CONF_ANSWER_TIMEOUT: Final = "answer_timeout"

DEFAULT_PORT: Final = 7600
DEFAULT_ANSWER_TIMEOUT: Final = 120
MIN_ANSWER_TIMEOUT: Final = 10
MAX_ANSWER_TIMEOUT: Final = 600

HEALTH_INTERVAL_SECONDS: Final = 60

SERVICE_ASK: Final = "ask"
ATTR_QUESTION: Final = "question"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

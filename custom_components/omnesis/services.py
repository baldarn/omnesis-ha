"""Actions for Omnesis."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .answer import async_ask
from .api import MAX_QUESTION_LENGTH
from .const import ATTR_CONFIG_ENTRY_ID, ATTR_QUESTION, DOMAIN, SERVICE_ASK
from .coordinator import OmnesisConfigEntry

ASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUESTION): vol.All(cv.string, vol.Length(min=1, max=MAX_QUESTION_LENGTH)),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def _entry_for(hass: HomeAssistant, entry_id: str | None) -> OmnesisConfigEntry:
    entries: list[OmnesisConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and (entry_id is None or entry.entry_id == entry_id)
    ]
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_loaded_entry")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_required")
    return entries[0]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Omnesis actions."""

    async def ask(call: ServiceCall) -> ServiceResponse:
        entry = _entry_for(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        answer = await async_ask(hass, entry, call.data[ATTR_QUESTION])
        return answer.as_dict()

    hass.services.async_register(
        DOMAIN,
        SERVICE_ASK,
        ask,
        schema=ASK_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

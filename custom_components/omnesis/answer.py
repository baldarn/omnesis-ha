"""Ask the gateway a question, with errors Home Assistant can show."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import (
    Answer,
    AnswerTimeout,
    CannotConnect,
    CertificateError,
    GatewayError,
    InvalidAuth,
    InvalidResponse,
)
from .const import CONF_ANSWER_TIMEOUT, DEFAULT_ANSWER_TIMEOUT, DOMAIN
from .coordinator import OmnesisConfigEntry


async def async_ask(
    hass: HomeAssistant,
    entry: OmnesisConfigEntry,
    question: str,
    conversation_id: str | None = None,
) -> Answer:
    """Ask one question; raise HomeAssistantError with a readable reason on failure."""
    data = entry.runtime_data
    budget = entry.options.get(CONF_ANSWER_TIMEOUT, DEFAULT_ANSWER_TIMEOUT)
    try:
        return await data.client.async_answer(
            question, budget=budget, conversation_id=conversation_id
        )
    except InvalidAuth as err:
        entry.async_start_reauth(hass)
        raise _error("token_refused") from err
    except CertificateError as err:
        entry.async_start_reauth(hass)
        raise _error("certificate_changed") from err
    except AnswerTimeout as err:
        raise _error("answer_timeout", seconds=str(budget)) from err
    except CannotConnect as err:
        raise _error("gateway_unreachable", error=str(err)) from err
    except GatewayError as err:
        raise _error("gateway_refused", error=err.detail) from err
    except InvalidResponse as err:
        raise _error("invalid_response") from err


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )

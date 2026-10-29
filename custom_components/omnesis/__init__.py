"""The Omnesis integration: ask your Omnesis gateway from Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import CertificateError, InvalidAuth, OmnesisClient, OmnesisError
from .const import CONF_FINGERPRINT, DOMAIN
from .coordinator import OmnesisConfigEntry, OmnesisData, OmnesisHealthCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CONVERSATION]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Omnesis actions."""
    async_setup_services(hass)
    return True


def client_for_entry(hass: HomeAssistant, entry: OmnesisConfigEntry) -> OmnesisClient:
    """Build a client from a config entry's data."""
    fingerprint = entry.data.get(CONF_FINGERPRINT)
    return OmnesisClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
        bytes.fromhex(fingerprint) if fingerprint else None,
    )


async def async_setup_entry(hass: HomeAssistant, entry: OmnesisConfigEntry) -> bool:
    """Set up Omnesis from a config entry."""
    client = client_for_entry(hass, entry)
    try:
        await client.async_check_auth()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="token_refused"
        ) from err
    except CertificateError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="certificate_changed"
        ) from err
    except OmnesisError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="gateway_unreachable",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err

    coordinator = OmnesisHealthCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = OmnesisData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OmnesisConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

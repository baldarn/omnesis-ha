"""Gateway health polling for Omnesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CertificateError, OmnesisClient, OmnesisError
from .const import DOMAIN, HEALTH_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

type OmnesisConfigEntry = ConfigEntry[OmnesisData]


@dataclass
class OmnesisData:
    """Runtime data for one Omnesis config entry."""

    client: OmnesisClient
    coordinator: OmnesisHealthCoordinator
    # Home Assistant conversation id -> Omnesis conversation id.
    conversations: dict[str, str] = field(default_factory=dict)


class OmnesisHealthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the gateway's public health endpoint."""

    config_entry: OmnesisConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: OmnesisConfigEntry, client: OmnesisClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=HEALTH_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_health()
        except CertificateError as err:
            # The gateway presents another certificate: confirm it again.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="certificate_changed"
            ) from err
        except OmnesisError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="gateway_unreachable",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err

"""Base entity for Omnesis."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OmnesisHealthCoordinator


class OmnesisEntity(CoordinatorEntity[OmnesisHealthCoordinator]):
    """An entity that belongs to the Omnesis gateway device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OmnesisHealthCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Omnesis",
            manufacturer="Omnesis",
            model="Gateway",
            sw_version=(coordinator.data or {}).get("version"),
            configuration_url=f"{coordinator.client.url}/portal/",
            entry_type=DeviceEntryType.SERVICE,
        )

"""Gateway connectivity sensor for Omnesis."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OmnesisConfigEntry
from .entity import OmnesisEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmnesisConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([OmnesisConnectivitySensor(entry.runtime_data.coordinator)])


class OmnesisConnectivitySensor(OmnesisEntity, BinarySensorEntity):
    """Whether the gateway answers its health check."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "gateway"

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "gateway")

    @property
    def available(self) -> bool:
        """Stay available: an unreachable gateway is reported as off."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the last health check succeeded."""
        return self.coordinator.last_update_success

"""Repairs issues for Omnesis."""

from __future__ import annotations

from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import OmnesisConfigEntry


def portal_devices_url(url: str) -> str:
    """Return the portal page where a device's access level is chosen."""
    return f"{url}/portal/settings/devices"


def _issue_id(entry: OmnesisConfigEntry) -> str:
    return f"access_level_{entry.entry_id}"


def async_create_access_level_issue(
    hass: HomeAssistant, entry: OmnesisConfigEntry, code: str
) -> None:
    """Ask for an access level to be chosen for Home Assistant's device."""
    portal = portal_devices_url(entry.data[CONF_URL])
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=code.lower(),
        translation_placeholders={"url": portal, "title": entry.title},
        learn_more_url=portal,
    )


def async_delete_access_level_issue(hass: HomeAssistant, entry: OmnesisConfigEntry) -> None:
    """Withdraw the access level issue, if any."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))

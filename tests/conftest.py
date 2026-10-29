"""Fixtures for the Omnesis tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_TOKEN, CONF_URL
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.omnesis.const import CONF_FINGERPRINT, DOMAIN

URL = "https://127.0.0.1:7600"
TOKEN = "omn_test_token"
FINGERPRINT = "ab" * 32
HEALTH = {"status": "ok", "version": "0.7.0"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture(autouse=True)
def fast_retries() -> Generator[None]:
    """Make the answer retry loop wait no real time."""
    with (
        patch("custom_components.omnesis.api.FIRST_RETRY_DELAY", 0.001),
        patch("custom_components.omnesis.api.MAX_RETRY_DELAY", 0.001),
    ):
        yield


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """A configured gateway with a pinned certificate."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Omnesis (127.0.0.1)",
        unique_id=URL,
        data={CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_FINGERPRINT: FINGERPRINT},
    )


@pytest.fixture
def mock_fetch_fingerprint() -> Generator[AsyncMock]:
    """Stub reading the gateway's certificate."""
    with patch(
        "custom_components.omnesis.config_flow.async_fetch_fingerprint",
        return_value=bytes.fromhex(FINGERPRINT),
    ) as mock:
        yield mock


@pytest.fixture
async def ha_core(hass) -> None:
    """Set up the core integration that conversation depends on."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})

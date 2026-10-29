"""Tests for the Omnesis config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.omnesis.const import (
    CONF_ANSWER_TIMEOUT,
    CONF_FINGERPRINT,
    CONF_PAIRING_CODE,
    DOMAIN,
)

from .conftest import FINGERPRINT, HEALTH, TOKEN, URL

pytestmark = pytest.mark.usefixtures("ha_core")


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_flow_with_pinned_certificate(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_fetch_fingerprint: AsyncMock
) -> None:
    # The mocker does not do TLS, so pretend the system roots refused the cert
    # on the first probe and the pinned one answers.
    from custom_components.omnesis.api import CertificateError

    calls = {"n": 0}

    async def health(method, url, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise CertificateError("self-signed")
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        return AiohttpClientMockResponse(method, url, json=HEALTH)

    aioclient_mock.get(f"{URL}/health", side_effect=health)
    aioclient_mock.post(f"{URL}/devices/pair", json={"token": TOKEN, "scopes": ["answer"]})

    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "127.0.0.1"}
    )
    assert result["step_id"] == "certificate"
    assert result["description_placeholders"]["fingerprint"] == FINGERPRINT

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRING_CODE: "abc123"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_FINGERPRINT: FINGERPRINT}


async def test_trusted_certificate_skips_pinning(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get("https://gw.ts.net:7600/health", json=HEALTH)
    aioclient_mock.post(
        "https://gw.ts.net:7600/devices/pair", json={"token": TOKEN, "scopes": ["answer"]}
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "https://gw.ts.net"}
    )
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRING_CODE: "abc"}
    )
    assert result["data"][CONF_FINGERPRINT] is None


async def test_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://192.168.1.2"}
    )
    assert result["errors"] == {CONF_URL: "insecure_url"}

    aioclient_mock.get("https://gw:7600/health", json={"nope": True})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: "gw"})
    assert result["errors"] == {"base": "not_omnesis"}

    aioclient_mock.clear_requests()
    aioclient_mock.get("https://gw:7600/health", json=HEALTH)
    aioclient_mock.post(
        "https://gw:7600/devices/pair",
        status=400,
        json={"code": "BAD_REQUEST", "error": "Invalid pairing code"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: "gw"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRING_CODE: "bad"}
    )
    assert result["errors"] == {CONF_PAIRING_CODE: "invalid_pairing_code"}


async def test_already_configured(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    mock_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_reauth_with_new_code(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
    mock_fetch_fingerprint: AsyncMock,
) -> None:
    mock_entry.add_to_hass(hass)
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    aioclient_mock.get(
        f"{URL}/answer/tasks/ha_auth_probe", status=401, json={"code": "UNAUTHORIZED"}
    )
    aioclient_mock.post(f"{URL}/devices/pair", json={"token": "omn_fresh", "scopes": ["answer"]})

    result = await mock_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {CONF_PAIRING_CODE: "token_refused"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRING_CODE: "new"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_TOKEN] == "omn_fresh"


async def test_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    aioclient_mock.get(f"{URL}/answer/tasks/ha_auth_probe", status=404, json={"code": "NOT_FOUND"})
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ANSWER_TIMEOUT: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_ANSWER_TIMEOUT] == 60

"""Tests for Omnesis setup, the conversation agent and the ask action."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.omnesis.const import DOMAIN

from .conftest import HEALTH, URL

pytestmark = pytest.mark.usefixtures("ha_core")


async def _setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    aioclient_mock.get(f"{URL}/answer/tasks/ha_auth_probe", status=404, json={"code": "NOT_FOUND"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.omnesis_gateway").state == "on"
    assert hass.states.get("conversation.omnesis") is not None
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.NOT_LOADED


async def test_revoked_token_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(
        f"{URL}/answer/tasks/ha_auth_probe", status=401, json={"code": "UNAUTHORIZED"}
    )
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_gateway_down_retries_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{URL}/answer/tasks/ha_auth_probe", exc=TimeoutError())
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


async def test_conversation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    aioclient_mock.post(
        f"{URL}/answer",
        json={
            "status": "released_with_reductions",
            "taskId": "t",
            "answer": "Next Tuesday at 10.",
            "reductions": ["address"],
            "conversationId": "c_1",
        },
    )
    result = await conversation.async_converse(
        hass, "When is the dentist?", None, None, agent_id="conversation.omnesis"
    )
    speech = result.response.speech["plain"]["speech"]
    assert speech.startswith("Next Tuesday at 10.")
    assert "address" in speech

    # A follow-up in the same Assist conversation continues the Omnesis one.
    await conversation.async_converse(
        hass, "And the one after?", result.conversation_id, None, agent_id="conversation.omnesis"
    )
    follow_up = aioclient_mock.mock_calls[-1][2]
    assert follow_up["conversationId"] == "c_1"


async def test_conversation_error_is_spoken(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    aioclient_mock.post(
        f"{URL}/answer",
        status=503,
        json={"code": "SERVICE_UNAVAILABLE", "error": "Agent disabled."},
    )
    result = await conversation.async_converse(
        hass, "ciao", None, None, language="it", agent_id="conversation.omnesis"
    )
    assert result.response.response_type.value == "error"
    assert "Agent disabled." in result.response.speech["plain"]["speech"]


async def test_ask_action(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    aioclient_mock.post(f"{URL}/answer", json={"status": "released", "taskId": "t", "answer": "42"})
    response = await hass.services.async_call(
        DOMAIN, "ask", {"question": "meaning?"}, blocking=True, return_response=True
    )
    assert response == {"status": "released", "answer": "42", "reductions": [], "reason": None}


PORTAL = f"{URL}/portal/settings/devices"


def _no_level(code: str = "ACCESS_LEVEL_REQUIRED") -> dict:
    return {"code": code, "error": "This integration has no access level yet."}


def _reauth_started(hass: HomeAssistant) -> bool:
    return any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_missing_access_level_raises_issue_not_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    aioclient_mock.get(f"{URL}/answer/tasks/ha_auth_probe", status=403, json=_no_level())
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.SETUP_RETRY
    assert not _reauth_started(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"access_level_{mock_entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "access_level_required"
    assert issue.learn_more_url == PORTAL

    # Once a level is chosen, the retry connects and withdraws the issue.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/answer/tasks/ha_auth_probe", status=404, json={"code": "NOT_FOUND"})
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"access_level_{mock_entry.entry_id}") is None


async def test_conversation_access_level_unavailable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    aioclient_mock.post(f"{URL}/answer", status=403, json=_no_level("ACCESS_LEVEL_UNAVAILABLE"))
    result = await conversation.async_converse(
        hass, "When?", None, None, agent_id="conversation.omnesis"
    )
    assert result.response.response_type.value == "error"
    assert PORTAL in result.response.speech["plain"]["speech"]
    assert not _reauth_started(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"access_level_{mock_entry.entry_id}")
    assert issue is not None and issue.translation_key == "access_level_unavailable"


async def test_ask_action_access_level_required(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_entry: MockConfigEntry
) -> None:
    await _setup(hass, aioclient_mock, mock_entry)
    aioclient_mock.post(f"{URL}/answer", status=403, json=_no_level())
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "ask", {"question": "q"}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "access_level_required"
    assert not _reauth_started(hass)

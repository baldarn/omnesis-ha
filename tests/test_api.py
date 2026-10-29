"""Tests for the Omnesis gateway client."""

from __future__ import annotations

import aiohttp
from aioresponses import aioresponses
import pytest

from custom_components.omnesis.api import (
    AnswerTimeout,
    CannotConnect,
    GatewayError,
    InvalidAuth,
    InvalidPairingCode,
    InvalidResponse,
    OmnesisClient,
    normalize_url,
)

URL = "https://gw:7600"


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        yield OmnesisClient(session, URL, "tok")


def _bodies(mocked: aioresponses, path: str) -> list[dict]:
    return [
        call.kwargs["json"] for call in mocked.requests[("POST", aiohttp.client.URL(URL + path))]
    ]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("gw", "https://gw:7600"),
        ("https://gw:7600/", "https://gw:7600"),
        ("https://gw.ts.net", "https://gw.ts.net:7600"),
        ("http://localhost:7600", "http://localhost:7600"),
        ("https://[::1]:7600", "https://[::1]:7600"),
    ],
)
def test_normalize_url(given: str, expected: str) -> None:
    assert normalize_url(given) == expected


@pytest.mark.parametrize(
    ("given", "error"), [("http://gw:7600", "insecure_url"), ("ftp://gw", "invalid_url")]
)
def test_normalize_url_refuses(given: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        normalize_url(given)


async def test_released(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer",
            payload={
                "status": "released",
                "taskId": "t1",
                "answer": "Tuesday",
                "conversationId": "c1",
            },
        )
        answer = await client.async_answer("When?", budget=5)
    assert answer.answer == "Tuesday"
    assert answer.conversation_id == "c1"
    body = _bodies(mocked, "/answer")[0]
    assert body["approval"] == "never"
    assert body["question"] == "When?"
    assert "conversationId" not in body


async def test_continues_conversation(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/answer", payload={"status": "released", "taskId": "t1", "answer": "ok"})
        await client.async_answer("And then?", budget=5, conversation_id="c1")
    assert _bodies(mocked, "/answer")[0]["conversationId"] == "c1"


async def test_released_with_reductions_and_denied(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer",
            payload={
                "status": "released_with_reductions",
                "taskId": "t",
                "answer": "a",
                "reductions": ["phone number"],
            },
        )
        mocked.post(
            f"{URL}/answer", payload={"status": "denied", "taskId": "t", "reason": "policy"}
        )
        reduced = await client.async_answer("q", budget=5)
        denied = await client.async_answer("q", budget=5)
    assert reduced.reductions == ["phone number"] and reduced.released
    assert denied.reason == "policy" and not denied.released


async def test_retries_in_progress_under_same_request_id(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer", status=409, payload={"code": "ANSWER_IN_PROGRESS", "error": "running"}
        )
        mocked.post(f"{URL}/answer", exception=aiohttp.ClientConnectionError())
        mocked.post(f"{URL}/answer", status=502)
        mocked.post(
            f"{URL}/answer", payload={"status": "released", "taskId": "t", "answer": "done"}
        )
        answer = await client.async_answer("q", budget=5)
    assert answer.answer == "done"
    ids = {body["clientRequestId"] for body in _bodies(mocked, "/answer")}
    assert len(ids) == 1


async def test_reasks_once_after_access_change(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer", status=409, payload={"code": "ANSWER_ACCESS_CHANGED", "error": "x"}
        )
        mocked.post(
            f"{URL}/answer", status=409, payload={"code": "ANSWER_ACCESS_CHANGED", "error": "again"}
        )
        with pytest.raises(GatewayError) as err:
            await client.async_answer("q", budget=5)
    assert err.value.detail == "again"


async def test_coded_errors_are_final(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer",
            status=503,
            payload={"code": "SERVICE_UNAVAILABLE", "error": "Agent disabled."},
        )
        with pytest.raises(GatewayError, match="Agent disabled"):
            await client.async_answer("q", budget=5)


async def test_unauthorized(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{URL}/answer", status=401, payload={"code": "UNAUTHORIZED", "error": "Unauthorized"}
        )
        with pytest.raises(InvalidAuth):
            await client.async_answer("q", budget=5)


async def test_timeout(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/answer", exception=TimeoutError())
        with pytest.raises(AnswerTimeout):
            await client.async_answer("q", budget=5)


async def test_outage_gives_up(client: OmnesisClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("custom_components.omnesis.api.OUTAGE_GIVE_UP", 0.01)
    with aioresponses() as mocked:
        mocked.post(f"{URL}/answer", exception=aiohttp.ClientConnectionError(), repeat=True)
        with pytest.raises(CannotConnect):
            await client.async_answer("q", budget=5)


async def test_malformed_answer(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/answer", payload={"status": "released", "taskId": "t"})
        with pytest.raises(InvalidResponse):
            await client.async_answer("q", budget=5)


async def test_redirect_not_followed(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/answer", status=307, headers={"Location": "https://evil/answer"})
        with pytest.raises(GatewayError, match="redirects"):
            await client.async_answer("q", budget=5)


async def test_redeem(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/devices/pair", payload={"token": "omn_new", "scopes": ["answer"]})
        assert await client.async_redeem(" abcd ") == "omn_new"
    assert _bodies(mocked, "/devices/pair")[0] == {"pairingCode": "ABCD"}
    assert client.token == "omn_new"


@pytest.mark.parametrize(
    "response",
    [
        {"status": 400, "payload": {"code": "BAD_REQUEST", "error": "Invalid code"}},
        {"status": 200, "payload": {"token": "omn_admin", "scopes": ["admin", "read"]}},
    ],
)
async def test_redeem_refused(client: OmnesisClient, response: dict) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{URL}/devices/pair", **response)
        with pytest.raises(InvalidPairingCode):
            await client.async_redeem("x")


async def test_check_auth(client: OmnesisClient) -> None:
    with aioresponses() as mocked:
        mocked.get(
            f"{URL}/answer/tasks/ha_auth_probe",
            status=404,
            payload={"code": "NOT_FOUND", "error": "x"},
        )
        await client.async_check_auth()
        mocked.get(
            f"{URL}/answer/tasks/ha_auth_probe", status=401, payload={"code": "UNAUTHORIZED"}
        )
        with pytest.raises(InvalidAuth):
            await client.async_check_auth()

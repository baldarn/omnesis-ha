"""Client for the Omnesis gateway's integration API.

An integration device holds a token with only the `answer` scope: it can ask
questions through `POST /answer` and nothing else. What the answers may draw
on is the access level chosen for the device in the Omnesis portal.

`/answer` keeps each `clientRequestId` as one durable task and never delivers
two answers for it, so a question is asked again under the same id after a
dropped connection, while the answer is still being made, or while the
gateway is momentarily full or restarting. This mirrors omnesis-guv's ask.ts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import re
import ssl
from typing import Any
from urllib.parse import urlsplit
import uuid

import aiohttp

MAX_QUESTION_LENGTH = 10_000

FIRST_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 10.0
# How long the gateway may stay unavailable before a question reports it.
OUTAGE_GIVE_UP = 30.0
# How long one attempt may take while the gateway is unavailable.
OUTAGE_PROBE = 10.0
REQUEST_TIMEOUT = 15.0

# Proxy statuses that mean the gateway behind it is restarting or down. The
# gateway's own errors always carry a code, so only uncoded ones count.
_PROXY_GAP_STATUSES = frozenset({502, 503, 504})
# Refusals that clear on their own: the task is running, or the gateway is full.
_TRANSIENT_CODES = frozenset(
    {"ANSWER_IN_PROGRESS", "ANSWER_CAPACITY", "QUEUE_FULL", "SQLITE_READONLY"}
)
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")

_CERTIFICATE_ERRORS = (
    aiohttp.ClientConnectorCertificateError,
    aiohttp.ServerFingerprintMismatch,
    ssl.SSLCertVerificationError,
)


class OmnesisError(Exception):
    """Base class for Omnesis errors."""


class CannotConnect(OmnesisError):
    """The gateway could not be reached."""


class CertificateError(OmnesisError):
    """The gateway's certificate is not the trusted one."""


class RequestTimeout(CannotConnect):
    """One request took longer than its timeout."""


class InvalidAuth(OmnesisError):
    """The token was refused: revoked, or never valid."""


class InvalidPairingCode(OmnesisError):
    """The pairing code was refused: wrong, used, or expired."""


class InvalidResponse(OmnesisError):
    """The gateway answered in a form this client does not understand."""


class AnswerTimeout(OmnesisError):
    """No answer arrived within the time budget."""


class GatewayError(OmnesisError):
    """The gateway refused the request with an error status."""

    def __init__(self, status: int, code: str | None, detail: str) -> None:
        """Initialize the error."""
        super().__init__(f"Omnesis answered HTTP {status}{f' {code}' if code else ''}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Answer:
    """The gateway's verdict on one question."""

    status: str
    task_id: str
    answer: str | None = None
    reductions: list[str] = field(default_factory=list)
    reason: str | None = None
    approval_id: str | None = None
    conversation_id: str | None = None

    @property
    def released(self) -> bool:
        """Whether an answer was released."""
        return self.status in ("released", "released_with_reductions")

    def as_dict(self) -> dict[str, Any]:
        """Return the answer as service response data."""
        return {
            "status": self.status,
            "answer": self.answer,
            "reductions": self.reductions,
            "reason": self.reason,
        }


def normalize_url(url: str) -> str:
    """Return the gateway origin for a user-entered URL."""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("invalid_url")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        # The token would cross the network in the clear.
        raise ValueError("insecure_url")
    port = parts.port or (7600 if parts.scheme == "https" else 80)
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}:{port}"


def format_fingerprint(fingerprint: bytes) -> str:
    """Format a SHA-256 fingerprint as `omnesis tls status` prints it."""
    return fingerprint.hex()


async def async_fetch_fingerprint(url: str) -> bytes:
    """Return the SHA-256 fingerprint of the certificate the gateway presents."""
    parts = urlsplit(url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            _, writer = await asyncio.open_connection(
                parts.hostname, parts.port, ssl=context, server_hostname=parts.hostname
            )
    except (OSError, TimeoutError) as err:
        raise CannotConnect(str(err)) from err
    try:
        der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        writer.close()
    if not der:
        raise CertificateError("no certificate")
    return hashlib.sha256(der).digest()


class OmnesisClient:
    """One Omnesis gateway, as an integration device sees it."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str | None = None,
        fingerprint: bytes | None = None,
    ) -> None:
        """Initialize the client.

        With a fingerprint, the gateway's certificate is pinned to it instead
        of being verified against the system's trusted roots.
        """
        self._session = session
        self.url = url
        self._token = token
        self._ssl: aiohttp.Fingerprint | bool = (
            aiohttp.Fingerprint(fingerprint) if fingerprint else True
        )

    @property
    def token(self) -> str | None:
        """Return the device token, once known."""
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT,
        auth: bool = True,
    ) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method,
                f"{self.url}{path}",
                json=body,
                headers=headers,
                ssl=self._ssl,
                # The gateway never redirects these; following one would send the token on.
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                text = await response.text()
                status = response.status
        except _CERTIFICATE_ERRORS as err:
            raise CertificateError(str(err)) from err
        except aiohttp.ClientSSLError as err:
            raise CertificateError(str(err)) from err
        except TimeoutError as err:
            raise RequestTimeout("timeout") from err
        except (aiohttp.ClientError, OSError) as err:
            raise CannotConnect(type(err).__name__) from err
        if 300 <= status < 400:
            raise GatewayError(status, None, "the gateway address redirects")
        try:
            payload = json.loads(text) if text else None
        except ValueError:
            payload = None
        if status in (401, 403):
            raise InvalidAuth(_error_detail(payload, "Unauthorized"))
        if status >= 400:
            envelope = payload if isinstance(payload, dict) else {}
            code = envelope.get("code")
            raise GatewayError(
                status,
                code if isinstance(code, str) else None,
                _error_detail(payload, "no detail given"),
            )
        return status, payload

    async def async_health(self) -> dict[str, Any]:
        """Return the gateway's public health document."""
        _, payload = await self._request("GET", "/health", auth=False)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise InvalidResponse
        return payload

    async def async_redeem(self, pairing_code: str) -> str:
        """Exchange a pairing code for this device's token, and keep it."""
        try:
            _, payload = await self._request(
                "POST",
                "/devices/pair",
                body={"pairingCode": pairing_code.strip().upper()},
                auth=False,
            )
        except GatewayError as err:
            if err.status in (400, 409):
                raise InvalidPairingCode(err.detail) from err
            raise
        if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
            raise InvalidResponse
        if "answer" not in payload.get("scopes", []):
            raise InvalidPairingCode("the code is not for an integration")
        self._token = payload["token"]
        return self._token

    async def async_check_auth(self) -> None:
        """Raise InvalidAuth if the token is refused.

        Polling a task that does not exist needs only the answer scope and
        creates nothing; any refusal other than 401/403 means the token is good.
        """
        try:
            await self._request("GET", "/answer/tasks/ha_auth_probe")
        except GatewayError:
            return

    async def async_answer(
        self,
        question: str,
        *,
        budget: float,
        conversation_id: str | None = None,
    ) -> Answer:
        """Ask one question and wait for the gateway's verdict, within `budget` seconds."""
        if not question.strip():
            raise ValueError("question must not be blank")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"question exceeds {MAX_QUESTION_LENGTH} characters")
        request: dict[str, Any] = {
            "question": question,
            "clientRequestId": f"ha_{uuid.uuid4().hex}",
            # Nobody is there to approve a held answer.
            "approval": "never",
        }
        if conversation_id and _CONVERSATION_ID.match(conversation_id):
            request["conversationId"] = conversation_id

        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget
        delay = FIRST_RETRY_DELAY
        reasked_after_access_change = False
        outage_since: float | None = None
        outage: OmnesisError | None = None
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AnswerTimeout(f"no answer within {round(budget)} seconds") from outage
            # During an outage every attempt is a short probe: a gateway that is
            # back answers at once, one still gone never does.
            probing = outage_since is not None
            attempt = min(remaining, OUTAGE_PROBE) if probing else remaining
            try:
                _, payload = await self._request("POST", "/answer", body=request, timeout=attempt)
                return _parse_answer(payload)
            except RequestTimeout as err:
                if not probing:
                    # The attempt had the whole remaining budget.
                    raise AnswerTimeout(f"no answer within {round(budget)} seconds") from err
                # A silent probe: the gateway is still gone, or is back and
                # making the answer; the next probe tells which.
                error: OmnesisError = outage or err
            except (CannotConnect, GatewayError) as err:
                error = err

            if (
                isinstance(error, GatewayError)
                and error.code == "ANSWER_ACCESS_CHANGED"
                and not reasked_after_access_change
            ):
                # The access level changed while the answer was made, so the
                # gateway withheld it. Ask once more under the new level.
                reasked_after_access_change = True
                outage_since = None
                continue
            if _is_outage(error):
                outage = error
                if outage_since is None:
                    outage_since = loop.time()
                if loop.time() - outage_since >= OUTAGE_GIVE_UP:
                    raise error
            elif isinstance(error, GatewayError) and error.code in _TRANSIENT_CODES:
                outage_since = None
            else:
                raise error

            now = loop.time()
            wait = min(delay, deadline - now)
            if outage_since is not None:
                wait = min(wait, outage_since + OUTAGE_GIVE_UP - now)
            if wait > 0:
                await asyncio.sleep(wait)
            delay = min(delay * 2, MAX_RETRY_DELAY)


def _is_outage(error: OmnesisError) -> bool:
    if isinstance(error, CannotConnect):
        return True
    if not isinstance(error, GatewayError):
        return False
    return error.code == "GATEWAY_SHUTTING_DOWN" or (
        error.code is None and error.status in _PROXY_GAP_STATUSES
    )


def _error_detail(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return fallback


def _parse_answer(payload: Any) -> Answer:
    if not isinstance(payload, dict):
        raise InvalidResponse
    status = payload.get("status")
    task_id = payload.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise InvalidResponse
    conversation_id = payload.get("conversationId")
    if not isinstance(conversation_id, str):
        conversation_id = None
    answer = payload.get("answer")
    match status:
        case "released" if isinstance(answer, str):
            return Answer(status, task_id, answer=answer, conversation_id=conversation_id)
        case "released_with_reductions" if isinstance(answer, str) and _is_str_list(
            reductions := payload.get("reductions")
        ):
            return Answer(
                status,
                task_id,
                answer=answer,
                reductions=reductions,
                conversation_id=conversation_id,
            )
        case "approval_required" if isinstance(approval_id := payload.get("approvalId"), str):
            return Answer(status, task_id, approval_id=approval_id)
        case "denied" if isinstance(reason := payload.get("reason"), str):
            return Answer(status, task_id, reason=reason)
    raise InvalidResponse


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)

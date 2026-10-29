"""Config flow for Omnesis."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .api import (
    CannotConnect,
    CertificateError,
    InvalidAuth,
    InvalidPairingCode,
    OmnesisClient,
    OmnesisError,
    async_fetch_fingerprint,
    format_fingerprint,
    normalize_url,
)
from .const import (
    CONF_ANSWER_TIMEOUT,
    CONF_FINGERPRINT,
    CONF_PAIRING_CODE,
    DEFAULT_ANSWER_TIMEOUT,
    DOMAIN,
    MAX_ANSWER_TIMEOUT,
    MIN_ANSWER_TIMEOUT,
)
from .coordinator import OmnesisConfigEntry

_LOGGER = logging.getLogger(__name__)

# Home Assistant OS runs Core on the host network, where the add-on's port is published.
DEFAULT_URL = "https://127.0.0.1:7600"


class OmnesisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair Home Assistant with an Omnesis gateway as an integration device."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._url: str | None = None
        # Hex SHA-256 of the pinned certificate; None when the system's roots trust it.
        self._fingerprint: str | None = None

    def _client(self, token: str | None = None) -> OmnesisClient:
        assert self._url is not None
        return OmnesisClient(
            async_get_clientsession(self.hass),
            self._url,
            token,
            bytes.fromhex(self._fingerprint) if self._fingerprint else None,
        )

    async def _async_probe_certificate(self) -> str | None:
        """Find out how to trust the gateway; return an error key, or None.

        A certificate the system already trusts (Tailscale, a public CA) is
        verified normally. Otherwise the one the gateway presents is pinned,
        after the user compares its fingerprint with the gateway's.
        """
        assert self._url is not None
        self._fingerprint = None
        if self._url.startswith("http://"):
            return await self._async_check_health()
        try:
            await self._client().async_health()
        except CertificateError:
            pass
        except CannotConnect:
            return "cannot_connect"
        except OmnesisError:
            return "not_omnesis"
        else:
            return None
        try:
            self._fingerprint = (await async_fetch_fingerprint(self._url)).hex()
        except OmnesisError:
            return "cannot_connect"
        return await self._async_check_health()

    async def _async_check_health(self) -> str | None:
        try:
            await self._client().async_health()
        except CannotConnect:
            return "cannot_connect"
        except OmnesisError:
            return "not_omnesis"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the gateway address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._url = normalize_url(user_input[CONF_URL])
            except ValueError as err:
                errors[CONF_URL] = str(err)
            else:
                await self.async_set_unique_id(self._url)
                self._abort_if_unique_id_configured()
                if not (error := await self._async_probe_certificate()):
                    if self._fingerprint:
                        return await self.async_step_certificate()
                    return await self.async_step_pair()
                errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_URL): str}),
                {CONF_URL: self._url or DEFAULT_URL},
            ),
            errors=errors,
        )

    async def async_step_certificate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Have the user confirm the self-signed certificate's fingerprint."""
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="certificate",
            data_schema=vol.Schema({}),
            description_placeholders=self._certificate_placeholders(),
        )

    def _certificate_placeholders(self) -> dict[str, str]:
        assert self._url is not None and self._fingerprint is not None
        return {
            "url": self._url,
            "fingerprint": format_fingerprint(bytes.fromhex(self._fingerprint)),
        }

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Redeem an integration pairing code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._client()
            try:
                token = await client.async_redeem(user_input[CONF_PAIRING_CODE])
            except InvalidPairingCode:
                errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
            except CertificateError:
                errors["base"] = "certificate_changed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except OmnesisError:
                _LOGGER.exception("Unexpected answer while pairing with Omnesis")
                errors["base"] = "unknown"
            else:
                assert self._url is not None
                return self.async_create_entry(
                    title=f"Omnesis ({urlsplit(self._url).hostname})",
                    data={
                        CONF_URL: self._url,
                        CONF_TOKEN: token,
                        CONF_FINGERPRINT: self._fingerprint,
                    },
                )
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required(CONF_PAIRING_CODE): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start again when the token is refused or the certificate changed."""
        self._url = entry_data[CONF_URL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the certificate again and, if needed, pair again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is None:
            if error := await self._async_probe_certificate():
                errors["base"] = error
        else:
            code = (user_input.get(CONF_PAIRING_CODE) or "").strip()
            client = self._client(None if code else entry.data[CONF_TOKEN])
            try:
                if code:
                    await client.async_redeem(code)
                else:
                    await client.async_check_auth()
            except InvalidPairingCode:
                errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
            except InvalidAuth:
                errors[CONF_PAIRING_CODE] = "token_refused"
            except CertificateError:
                errors["base"] = "certificate_changed"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except OmnesisError:
                _LOGGER.exception("Unexpected answer while re-pairing with Omnesis")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_TOKEN: client.token,
                        CONF_FINGERPRINT: self._fingerprint,
                    },
                )
        placeholders = {"url": self._url or "", "fingerprint": "—"}
        if self._fingerprint:
            placeholders = self._certificate_placeholders()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_PAIRING_CODE): str}),
            description_placeholders=placeholders,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: OmnesisConfigEntry) -> OmnesisOptionsFlow:
        """Return the options flow."""
        return OmnesisOptionsFlow()


class OmnesisOptionsFlow(OptionsFlowWithReload):
    """Options for Omnesis."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set how long a question may take."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_ANSWER_TIMEOUT): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_ANSWER_TIMEOUT,
                                max=MAX_ANSWER_TIMEOUT,
                                step=1,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
                {
                    CONF_ANSWER_TIMEOUT: self.config_entry.options.get(
                        CONF_ANSWER_TIMEOUT, DEFAULT_ANSWER_TIMEOUT
                    )
                },
            ),
        )

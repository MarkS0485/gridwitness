"""Config + options flow: discovery, the earn-the-ask consent screen, location tier, registration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import ApiClient, GridWitnessApiError
from .const import (
    CONF_ALLOW_INSECURE,
    CONF_CHANNELS,
    CONF_LOC_REF,
    CONF_LOC_TIER,
    CONF_MAPPING,
    CONF_NODE_ID,
    CONF_POSTCODE,
    CONF_REGION,
    CONF_SERVER_URL,
    CONF_TOKEN,
    CONSENT_GROUPS,
    DEFAULT_SERVER_URL,
    DOMAIN,
    LOC_ANON,
    LOC_DATA_SHARE,
    LOC_REGION,
    LOC_TIERS,
    REGIONS,
)
from .discovery import discover, propose_mapping

_LOGGER = logging.getLogger(__name__)


def _channels_from_groups(enabled_groups: list[str]) -> list[str]:
    channels: list[str] = []
    for grp in enabled_groups:
        channels.extend(CONSENT_GROUPS[grp]["channels"])
    return channels


class GridWitnessConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._mapping: dict[str, list[dict[str, str]]] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_SERVER_URL] = user_input[CONF_SERVER_URL].rstrip("/")
            self._data[CONF_ALLOW_INSECURE] = user_input.get(CONF_ALLOW_INSECURE, False)
            return await self.async_step_consent()

        schema = vol.Schema({
            vol.Required(CONF_SERVER_URL, default=DEFAULT_SERVER_URL): str,
            vol.Optional(CONF_ALLOW_INSECURE, default=False): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_consent(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Discover once so we can propose a mapping and know which groups have sensors.
        discovery = await self.hass.async_add_executor_job(discover, self.hass)
        self._mapping = propose_mapping(discovery)

        if user_input is not None:
            enabled = [g for g in CONSENT_GROUPS if user_input.get(f"share_{g}")]
            self._data["_enabled_groups"] = enabled
            self._data[CONF_LOC_TIER] = user_input[CONF_LOC_TIER]
            if user_input[CONF_LOC_TIER] == LOC_REGION:
                return await self.async_step_region()
            if user_input[CONF_LOC_TIER] == LOC_DATA_SHARE:
                return await self.async_step_postcode()
            return await self._async_register_and_create()

        schema_dict: dict[Any, Any] = {}
        for grp, spec in CONSENT_GROUPS.items():
            has = bool(discovery.groups.get(grp))
            schema_dict[vol.Optional(f"share_{grp}", default=spec["default"] and has)] = bool
        schema_dict[vol.Required(CONF_LOC_TIER, default=LOC_ANON)] = vol.In(list(LOC_TIERS))

        return self.async_show_form(
            step_id="consent",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "discovered": ", ".join(
                    f"{g} ({len(c)})" for g, c in discovery.groups.items() if c
                ) or "none found",
            },
        )

    async def async_step_region(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_REGION] = user_input[CONF_REGION]
            return await self._async_register_and_create()
        schema = vol.Schema({vol.Required(CONF_REGION): vol.In(list(REGIONS))})
        return self.async_show_form(step_id="region", data_schema=schema)

    async def async_step_postcode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_POSTCODE] = user_input[CONF_POSTCODE].strip()
            return await self._async_register_and_create()
        schema = vol.Schema({vol.Required(CONF_POSTCODE): str})
        return self.async_show_form(step_id="postcode", data_schema=schema)

    async def _async_register_and_create(self) -> ConfigFlowResult:
        channels = _channels_from_groups(self._data.get("_enabled_groups", ["frequency"]))
        if not channels:
            channels = ["frequency_hz"]
        # keep only mapping for channels the user consented to share
        mapping = {ch: ents for ch, ents in self._mapping.items() if ch in channels}

        api = ApiClient(
            async_get_clientsession(self.hass),
            self._data[CONF_SERVER_URL],
            allow_insecure=self._data.get(CONF_ALLOW_INSECURE, False),
        )
        payload = {
            "channels": channels,
            "loc_tier": self._data[CONF_LOC_TIER],
            "region": self._data.get(CONF_REGION),
            "postcode": self._data.get(CONF_POSTCODE),
            "device_type": "home_assistant",
        }
        try:
            resp = await api.register(payload)
        except GridWitnessApiError as err:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_SERVER_URL, default=self._data[CONF_SERVER_URL]): str,
                    vol.Optional(CONF_ALLOW_INSECURE,
                                 default=self._data.get(CONF_ALLOW_INSECURE, False)): bool,
                }),
                errors={"base": "cannot_connect"},
                description_placeholders={"error": str(err)},
            )

        node_id = resp["node_id"]
        await self.async_set_unique_id(node_id)
        self._abort_if_unique_id_configured()

        data = {
            CONF_SERVER_URL: self._data[CONF_SERVER_URL],
            CONF_ALLOW_INSECURE: self._data.get(CONF_ALLOW_INSECURE, False),
            CONF_NODE_ID: node_id,
            CONF_TOKEN: resp["token"],
            CONF_CHANNELS: channels,
            CONF_LOC_TIER: self._data[CONF_LOC_TIER],
            CONF_LOC_REF: resp.get("loc_ref"),
            CONF_MAPPING: mapping,
        }
        return self.async_create_entry(title=f"GridWitness node {node_id[:8]}", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "GridWitnessOptionsFlow":
        return GridWitnessOptionsFlow(entry)


class GridWitnessOptionsFlow(OptionsFlow):
    """Revocable consent + a delete-my-data action."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = {**self.entry.data, **self.entry.options}
        current_channels = set(current.get(CONF_CHANNELS, []))

        if user_input is not None:
            if user_input.get("delete_my_data"):
                return await self._async_delete()
            enabled = [g for g in CONSENT_GROUPS if user_input.get(f"share_{g}")]
            channels = _channels_from_groups(enabled) or ["frequency_hz"]
            # push the consent change to the server (server is the enforcement point)
            api = ApiClient(
                async_get_clientsession(self.hass),
                current[CONF_SERVER_URL],
                allow_insecure=current.get(CONF_ALLOW_INSECURE, False),
            )
            try:
                await api.update_consent(
                    current[CONF_NODE_ID], current[CONF_TOKEN], {"channels": channels}
                )
            except GridWitnessApiError as err:
                return self.async_abort(reason="cannot_connect")
            mapping = {ch: e for ch, e in current.get(CONF_MAPPING, {}).items() if ch in channels}
            return self.async_create_entry(
                title="", data={CONF_CHANNELS: channels, CONF_MAPPING: mapping}
            )

        def _group_on(grp: str) -> bool:
            return bool(set(CONSENT_GROUPS[grp]["channels"]) & current_channels)

        schema_dict: dict[Any, Any] = {
            vol.Optional(f"share_{g}", default=_group_on(g)): bool for g in CONSENT_GROUPS
        }
        schema_dict[vol.Optional("delete_my_data", default=False)] = bool
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))

    async def _async_delete(self) -> ConfigFlowResult:
        current = {**self.entry.data, **self.entry.options}
        api = ApiClient(
            async_get_clientsession(self.hass),
            current[CONF_SERVER_URL],
            allow_insecure=current.get(CONF_ALLOW_INSECURE, False),
        )
        try:
            await api.delete_node(current[CONF_NODE_ID], current[CONF_TOKEN])
        except GridWitnessApiError:
            _LOGGER.warning("Server erasure call failed; removing local entry regardless")
        await self.hass.config_entries.async_remove(self.entry.entry_id)
        return self.async_abort(reason="deleted")

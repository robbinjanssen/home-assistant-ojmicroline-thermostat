"""Validate and privately store a captured WG4 gateway configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .local_gateway import MAX_FRAME, parse, uvarint

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class LocalProfile(TypedDict):
    """Device-specific responses captured from the original gateway."""

    serial_sha256: str
    firmware: str
    configuration: str
    support: str


def profile_store(hass: HomeAssistant, entry_id: str) -> Store[LocalProfile]:
    """Return the private profile store for one account."""
    return Store(hass, 1, f"{DOMAIN}.{entry_id}.local_profile")


def validate_profile(data: Any) -> LocalProfile:
    """Accept only a device hash, firmware, and two narrowly shaped responses."""
    keys = ("serial_sha256", "firmware", "configuration", "support")
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), str) or not data[key] for key in keys
    ):
        msg = "The local profile is incomplete."
        raise ValueError(msg)
    if re.fullmatch(r"[0-9a-f]{64}", data["serial_sha256"]) is None:
        msg = "The local profile has an invalid thermostat hash."
        raise ValueError(msg)
    for key, field in (("configuration", 10), ("support", 18)):
        try:
            raw = bytes.fromhex(data[key])
            size, offset = uvarint(raw, 1)
            fields = parse(raw[offset:])
            valid = (
                raw[0] == 8
                and 0 < size <= MAX_FRAME
                and size == len(raw) - offset
                and set(fields) <= {1, 5, field}
                and len(fields.get(field, [])) == 1
                and isinstance(fields[field][0], bytes)
            )
        except (IndexError, ValueError) as err:
            msg = "The local profile contains an invalid gateway response."
            raise ValueError(msg) from err
        if not valid:
            msg = "The local profile must contain configuration/support responses only."
            raise ValueError(msg)
    return LocalProfile(
        serial_sha256=data["serial_sha256"],
        firmware=data["firmware"],
        configuration=data["configuration"],
        support=data["support"],
    )


async def async_load_profile(hass: HomeAssistant, entry_id: str) -> LocalProfile:
    """Load a saved profile or import one from the user's private config folder.

    The final path migrates the initial experimental build. No device profile
    is distributed with the integration or included in a public release.
    """
    store = profile_store(hass, entry_id)
    if saved := await store.async_load():
        return validate_profile(saved)

    def read_profile() -> LocalProfile:
        for path in (
            Path(hass.config.path(DOMAIN, f"{entry_id}.profile.json")),
            Path(hass.config.path(DOMAIN, "local_profile.json")),
            Path(__file__).with_name("local_profile.json"),
        ):
            if path.is_file():
                return validate_profile(json.loads(path.read_text(encoding="utf-8")))
        msg = "Import a captured local profile before enabling the WG4 gateway."
        raise ValueError(msg)

    profile = await hass.async_add_executor_job(read_profile)
    await store.async_save(profile)
    return profile

from __future__ import annotations

from collections.abc import Mapping


_REQUIRED_OIDC_SETTINGS = (
    "redirect_uri",
    "cookie_secret",
    "client_id",
    "client_secret",
    "server_metadata_url",
)


def has_oidc_configuration(secrets: Mapping[str, object]) -> bool:
    auth_settings = secrets.get("auth")
    if not isinstance(auth_settings, Mapping):
        return False
    return all(
        isinstance(auth_settings.get(key), str) and bool(auth_settings[key].strip())
        for key in _REQUIRED_OIDC_SETTINGS
    )

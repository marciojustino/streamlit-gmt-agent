from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class AppConfig:
    environment: str
    authorization_mode: str
    allowed_user_ids: frozenset[str]
    top_k: int
    max_document_bytes: int
    max_excerpt_chars: int
    memory_ttl_seconds: int
    memory_max_turns: int
    audit_path: Path
    audit_retention_days: int | None
    provider_kind: str


def load_config(path: Path) -> AppConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigurationError("Não foi possível carregar a configuração.") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("A configuração deve ser um objeto YAML.")

    try:
        auth = _mapping(raw, "authorization")
        retrieval = _mapping(raw, "retrieval")
        memory = _mapping(raw, "memory")
        audit = _mapping(raw, "audit")
        provider = _mapping(raw, "provider")
        environment = _required_string(raw, "environment")
        authorization_mode = _required_string(auth, "mode")
        if authorization_mode not in {"local", "oidc"}:
            raise ConfigurationError("authorization.mode deve ser local ou oidc.")
        if authorization_mode == "local" and environment != "local":
            raise ConfigurationError("authorization.mode=local exige environment=local.")

        user_ids = auth["allowed_user_ids"]
        if not isinstance(user_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in user_ids
        ):
            raise ConfigurationError("authorization.allowed_user_ids deve ser uma lista de IDs.")
        env_user_ids = os.environ.get("GMT_ALLOWED_USER_IDS")
        if env_user_ids is not None:
            user_ids = [value.strip() for value in env_user_ids.split(",")]
            if not all(user_ids):
                raise ConfigurationError("GMT_ALLOWED_USER_IDS contém um identificador vazio.")

        provider_kind = provider["kind"]
        if provider_kind != "disabled" or provider.get("endpoint") or provider.get("model"):
            raise ConfigurationError("Este protótipo aceita somente provider.kind=disabled.")

        retention = audit["retention_days"]
        if retention is not None and (
            not isinstance(retention, int) or isinstance(retention, bool) or retention < 1
        ):
            raise ConfigurationError("audit.retention_days deve ser positivo ou null.")

        config = AppConfig(
            environment=environment,
            authorization_mode=authorization_mode,
            allowed_user_ids=frozenset(value.strip().casefold() for value in user_ids),
            top_k=_positive_int(retrieval, "top_k"),
            max_document_bytes=_positive_int(retrieval, "max_document_bytes"),
            max_excerpt_chars=_positive_int(retrieval, "max_excerpt_chars"),
            memory_ttl_seconds=_positive_int(memory, "ttl_seconds"),
            memory_max_turns=_positive_int(memory, "max_turns"),
            audit_path=Path(_required_string(audit, "path")),
            audit_retention_days=retention,
            provider_kind=provider_kind,
        )
    except (KeyError, TypeError) as exc:
        raise ConfigurationError("A configuração está incompleta ou inválida.") from exc

    return config


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw[key]
    if not isinstance(value, dict):
        raise ConfigurationError(f"{key} deve ser um objeto YAML.")
    return value


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} deve ser um texto não vazio.")
    return value.strip()


def _positive_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigurationError(f"{key} deve ser um inteiro positivo.")
    return value

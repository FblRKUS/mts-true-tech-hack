from __future__ import annotations

import re
from uuid import uuid4

from app.core.errors import AppError
from app.modules.provider_connections.model import ProviderConnection
from app.modules.provider_connections.repository import provider_connection_repository
from app.modules.provider_connections.schemas import (
    ProviderConnectionCreateRequest,
    ProviderConnectionRecord,
    ProviderConnectionUpdateRequest,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,63}$")
_ALLOWED_PROVIDERS = {"openai", "ollama"}


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def _normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _to_record(model: ProviderConnection) -> ProviderConnectionRecord:
    return ProviderConnectionRecord(
        id=model.id,
        provider=model.provider,  # type: ignore[arg-type]
        slug=model.slug,
        display_name=model.display_name,
        base_url=model.base_url,
        api_key_masked=_mask_secret(model.api_key),
        is_enabled=model.is_enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


async def list_provider_connections() -> list[ProviderConnectionRecord]:
    rows = await provider_connection_repository.list_all()
    return [_to_record(item) for item in rows]


async def list_enabled_provider_connections() -> list[ProviderConnection]:
    return await provider_connection_repository.list_enabled()


async def get_enabled_provider_connection(provider: str, slug: str) -> ProviderConnection | None:
    row = await provider_connection_repository.get_by_provider_slug(provider=provider, slug=slug)
    if row is None or not row.is_enabled:
        return None
    return row


async def create_provider_connection(payload: ProviderConnectionCreateRequest) -> ProviderConnectionRecord:
    provider = payload.provider.strip().lower()
    slug = payload.slug.strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise AppError(
            code="provider_not_supported",
            message="Provider is not supported",
            details={"provider": provider},
            status_code=422,
        )
    if not _SLUG_RE.match(slug):
        raise AppError(
            code="invalid_slug",
            message="Slug must match [a-z0-9][a-z0-9-]{1,63}",
            details={"slug": slug},
            status_code=422,
        )
    existing = await provider_connection_repository.get_by_provider_slug(provider=provider, slug=slug)
    if existing is not None:
        raise AppError(
            code="connection_exists",
            message="Provider connection with this slug already exists",
            details={"provider": provider, "slug": slug},
            status_code=409,
        )

    model = ProviderConnection(
        id=str(uuid4()),
        provider=provider,
        slug=slug,
        display_name=payload.display_name.strip(),
        base_url=_normalize_base_url(payload.base_url),
        api_key=payload.api_key.strip(),
        is_enabled=payload.is_enabled,
    )
    created = await provider_connection_repository.insert(model)
    return _to_record(created)


async def update_provider_connection(
    connection_id: str, payload: ProviderConnectionUpdateRequest
) -> ProviderConnectionRecord:
    existing = await provider_connection_repository.get_by_id(connection_id)
    if existing is None:
        raise AppError(
            code="connection_not_found",
            message="Provider connection not found",
            details={"id": connection_id},
            status_code=404,
        )

    if payload.display_name is not None:
        existing.display_name = payload.display_name.strip()
    if payload.base_url is not None:
        existing.base_url = _normalize_base_url(payload.base_url)
    if payload.api_key is not None:
        existing.api_key = payload.api_key.strip()
    if payload.is_enabled is not None:
        existing.is_enabled = payload.is_enabled

    updated = await provider_connection_repository.update(existing)
    return _to_record(updated)


async def delete_provider_connection(connection_id: str) -> bool:
    deleted = await provider_connection_repository.delete_by_id(connection_id)
    if not deleted:
        raise AppError(
            code="connection_not_found",
            message="Provider connection not found",
            details={"id": connection_id},
            status_code=404,
        )
    return True

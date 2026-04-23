from __future__ import annotations

from fastapi import APIRouter

from app.modules.provider_connections.schemas import (
    ProviderConnectionCreateRequest,
    ProviderConnectionDeleteResponse,
    ProviderConnectionRecord,
    ProviderConnectionUpdateRequest,
)
from app.modules.provider_connections.service import (
    create_provider_connection,
    delete_provider_connection,
    list_provider_connections,
    update_provider_connection,
)

router = APIRouter(prefix="/features/provider-connections", tags=["feature:provider-connections"])


@router.get(
    "",
    response_model=list[ProviderConnectionRecord],
    summary="List provider connections",
    description="Возвращает настроенные upstream-подключения (OpenAI/Ollama) для маршрутизации через GPTHub API.",
)
async def get_provider_connections() -> list[ProviderConnectionRecord]:
    return await list_provider_connections()


@router.post(
    "",
    response_model=ProviderConnectionRecord,
    summary="Create provider connection",
    description="Создает upstream-подключение для OpenAI или Ollama.",
)
async def add_provider_connection(payload: ProviderConnectionCreateRequest) -> ProviderConnectionRecord:
    return await create_provider_connection(payload)


@router.patch(
    "/{connection_id}",
    response_model=ProviderConnectionRecord,
    summary="Update provider connection",
    description="Обновляет параметры upstream-подключения (URL/ключ/статус).",
)
async def patch_provider_connection(
    connection_id: str, payload: ProviderConnectionUpdateRequest
) -> ProviderConnectionRecord:
    return await update_provider_connection(connection_id, payload)


@router.delete(
    "/{connection_id}",
    response_model=ProviderConnectionDeleteResponse,
    summary="Delete provider connection",
    description="Удаляет upstream-подключение.",
)
async def remove_provider_connection(connection_id: str) -> ProviderConnectionDeleteResponse:
    deleted = await delete_provider_connection(connection_id)
    return ProviderConnectionDeleteResponse(deleted=deleted, id=connection_id)

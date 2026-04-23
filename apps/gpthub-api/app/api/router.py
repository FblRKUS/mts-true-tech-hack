from fastapi import APIRouter

from app.api.download import router as download_router
from app.modules.auto_model.router import router as auto_model_router
from app.modules.chat_memory.router import router as chat_memory_router
from app.modules.feature_settings.router import router as feature_settings_router
from app.modules.media_gallery.router import router as media_gallery_router
from app.modules.provider_connections.router import router as provider_connections_router
from app.modules.workspaces.router import router as workspaces_router

api_router = APIRouter()


@api_router.get(
    "/health",
    tags=["health"],
    summary="Backend health check",
    description="Проверка доступности backend API.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(auto_model_router)
api_router.include_router(chat_memory_router)
api_router.include_router(feature_settings_router)
api_router.include_router(media_gallery_router)
api_router.include_router(provider_connections_router)
api_router.include_router(download_router)
api_router.include_router(workspaces_router)

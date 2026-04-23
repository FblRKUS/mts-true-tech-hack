from fastapi import APIRouter

from app.modules.auto_model.schemas import AutoModelRequest, AutoModelResponse
from app.modules.auto_model.service import route_request

router = APIRouter(prefix="/features/auto-model", tags=["feature:auto-model"])


@router.post(
    "/route",
    response_model=AutoModelResponse,
    summary="Route request in Auto mode",
    description="Определяет домен задачи, выбирает инструмент и модель, возвращает причины выбора.",
)
async def route_model(payload: AutoModelRequest) -> AutoModelResponse:
    return await route_request(payload)

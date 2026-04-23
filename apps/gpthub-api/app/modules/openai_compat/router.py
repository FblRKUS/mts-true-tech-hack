from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import StreamingResponse

from app.modules.openai_compat.schemas import ChatCompletionRequest, EmbeddingRequest, ImageGenerationRequest
from app.modules.openai_compat.service import (
    audio_transcription,
    chat_completion,
    embeddings,
    images_generation,
    list_models,
    stream_chat_completion,
    validate_chat_completion_request,
)

router = APIRouter(tags=["openai-compatible"])
_DEFAULT_MODEL_AVATAR_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "model_avatars" / "default_model_avatar_mts.svg"
)
_UPLOADED_DEFAULT_AVATAR_BASENAME = "default_model_avatar_uploaded"
_ALLOWED_DEFAULT_AVATAR_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg")


@router.get(
    "/assets/model-avatars/default",
    summary="Get default model avatar",
)
async def get_default_model_avatar():
    avatar_dir = _DEFAULT_MODEL_AVATAR_PATH.parent
    uploaded_path = None
    for ext in _ALLOWED_DEFAULT_AVATAR_EXTENSIONS:
        candidate = avatar_dir / f"{_UPLOADED_DEFAULT_AVATAR_BASENAME}{ext}"
        if candidate.exists():
            uploaded_path = candidate
            break
    chosen = uploaded_path or _DEFAULT_MODEL_AVATAR_PATH
    if not chosen.exists():
        return JSONResponse(status_code=404, content={"code": "not_found", "message": "Default avatar not found"})
    media_type = "image/svg+xml"
    if chosen.suffix.lower() in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif chosen.suffix.lower() == ".png":
        media_type = "image/png"
    return FileResponse(str(chosen), media_type=media_type)


@router.get(
    "/models",
    summary="List OpenAI-compatible models",
    description="Возвращает список моделей, включая autoselect-роутер для режима Auto.",
)
async def get_models() -> dict:
    return await list_models()


@router.post(
    "/chat/completions",
    summary="Create chat completion",
    description="OpenAI-compatible endpoint с поддержкой Auto/Manual выбора модели и streaming.",
)
async def create_chat_completion(payload: ChatCompletionRequest):
    if payload.stream:
        validate_chat_completion_request(payload)
        return StreamingResponse(stream_chat_completion(payload), media_type="text/event-stream")
    return await chat_completion(payload)


@router.post(
    "/embeddings",
    summary="Create embeddings",
    description="OpenAI-compatible embeddings endpoint с поддержкой роутинга модели.",
)
async def create_embeddings(payload: EmbeddingRequest):
    return await embeddings(payload)


@router.post(
    "/images/generations",
    summary="Generate images",
    description="OpenAI-compatible image generation endpoint с поддержкой роутинга модели.",
)
async def create_image_generation(payload: ImageGenerationRequest):
    return await images_generation(payload)


@router.post(
    "/audio/transcriptions",
    summary="Transcribe audio",
    description="OpenAI-compatible ASR endpoint с поддержкой роутинга модели.",
)
async def create_audio_transcription(
    file: UploadFile = File(...),
    model: str = Form("autoselect"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str | None = Form(None),
    temperature: float | None = Form(None),
):
    return await audio_transcription(
        file=file,
        model=model,
        language=language,
        prompt=prompt,
        response_format=response_format,
        temperature=temperature,
    )

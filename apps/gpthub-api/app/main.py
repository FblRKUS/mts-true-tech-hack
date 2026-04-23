from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.router import api_router
from app.core.auth import verify_bearer
from app.core.database import db_manager
from app.core.errors import AppError
from app.core.settings import get_settings
from app.modules.feature_settings.service import load_feature_settings_overrides
from app.modules.openai_compat.router import router as openai_router

settings = get_settings()
APP_NAME = "GPTHub API"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db_manager.initialize_checkpointer()
    await load_feature_settings_overrides()
    yield
    await db_manager.close()


app = FastAPI(title=APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1", dependencies=[Depends(verify_bearer)])
app.include_router(openai_router, prefix="/v1", dependencies=[Depends(verify_bearer)])


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.as_payload())


@app.exception_handler(HTTPException)
async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and {"code", "message", "details"} <= set(exc.detail.keys()):
        payload = exc.detail
    else:
        payload = {"code": "http_error", "message": str(exc.detail), "details": None}
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Request validation failed",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Internal server error",
            "details": {"type": exc.__class__.__name__},
        },
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "mode": "stub-ready"}

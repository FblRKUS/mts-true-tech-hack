from fastapi import APIRouter, File, HTTPException, UploadFile

from app.modules.feature_settings.schemas import (
    ApplyClassifierWinnerPayload,
    BenchmarkHistoryResult,
    ClassifierBenchmarkResult,
    FeatureSettingsPatchPayload,
    FeatureSettingsPayload,
    TextTournamentBenchmarkResult,
    TextBenchmarkResult,
)
from app.modules.feature_settings.service import (
    apply_classifier_winner,
    get_benchmark_history,
    get_feature_settings,
    run_classifier_benchmark,
    run_text_tournament_benchmark,
    run_text_benchmark,
    upload_default_model_avatar,
    update_feature_settings,
)

router = APIRouter(prefix="/features/settings", tags=["feature:settings"])


@router.get(
    "",
    response_model=FeatureSettingsPayload,
    summary="Get GPTHub feature settings",
    description="Возвращает текущие настройки GPTHub фич.",
)
async def fetch_feature_settings() -> FeatureSettingsPayload:
    return await get_feature_settings()


@router.patch(
    "",
    response_model=FeatureSettingsPayload,
    summary="Update GPTHub feature settings",
    description="Обновляет настройки GPTHub фич (в рантайме).",
)
async def patch_feature_settings(payload: FeatureSettingsPatchPayload) -> FeatureSettingsPayload:
    return await update_feature_settings(payload)


@router.post(
    "/default-avatar",
    summary="Upload default model avatar",
    description="Загружает стандартную аватарку модели (jpg/jpeg/png/svg).",
)
async def upload_default_avatar(file: UploadFile = File(...)) -> dict[str, str]:
    try:
        return await upload_default_model_avatar(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/benchmarks/classifier/run",
    response_model=ClassifierBenchmarkResult,
    summary="Run classifier benchmark",
)
async def run_classifier_benchmark_endpoint() -> ClassifierBenchmarkResult:
    return await run_classifier_benchmark()


@router.post(
    "/benchmarks/classifier/apply",
    response_model=FeatureSettingsPayload,
    summary="Apply classifier benchmark winner",
)
async def apply_classifier_benchmark_winner_endpoint(payload: ApplyClassifierWinnerPayload) -> FeatureSettingsPayload:
    return await apply_classifier_winner(payload)


@router.post(
    "/benchmarks/text/run",
    response_model=TextBenchmarkResult,
    summary="Run text model benchmark (GENERAL/CODING/REASONING)",
)
async def run_text_benchmark_endpoint() -> TextBenchmarkResult:
    return await run_text_benchmark()


@router.post(
    "/benchmarks/text/tournament/run",
    response_model=TextTournamentBenchmarkResult,
    summary="Run text tournament benchmark",
)
async def run_text_tournament_benchmark_endpoint() -> TextTournamentBenchmarkResult:
    return await run_text_tournament_benchmark()


@router.get(
    "/benchmarks/history",
    response_model=BenchmarkHistoryResult,
    summary="Get benchmark history",
)
async def get_benchmark_history_endpoint() -> BenchmarkHistoryResult:
    return await get_benchmark_history()

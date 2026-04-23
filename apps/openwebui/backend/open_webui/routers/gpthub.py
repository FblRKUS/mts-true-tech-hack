import logging
from typing import Literal, Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from open_webui.utils.auth import get_admin_user, get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()


def _resolve_gpthub_base(request: Request) -> tuple[str, str]:
    base = str(getattr(request.app.state.config, 'GPTHUB_API_URL', '') or '').strip()

    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='GPTHUB_API_URL is empty; GPTHub upstream is not configured',
        )

    base = base.rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    api_key = _resolve_gpthub_key(request, base)
    return base, api_key


def _normalize_openai_url(url: str) -> str:
    normalized = (url or '').strip().rstrip('/')
    return normalized


def _resolve_gpthub_key(request: Request, gpthub_api_base: str) -> str:
    urls = list(getattr(request.app.state.config, 'OPENAI_API_BASE_URLS', []) or [])
    keys = list(getattr(request.app.state.config, 'OPENAI_API_KEYS', []) or [])
    configs = dict(getattr(request.app.state.config, 'OPENAI_API_CONFIGS', {}) or {})

    def key_for_index(idx: int) -> str:
        if idx < 0 or idx >= len(keys):
            return ''
        return str(keys[idx] or '').strip()

    # Preferred source: OpenAI connection with title "GPTHub"
    for idx, url in enumerate(urls):
        api_config = configs.get(str(idx), configs.get(url, {}))
        title = str(api_config.get('title', '')).strip().lower() if isinstance(api_config, dict) else ''
        if title == 'gpthub':
            return key_for_index(idx)

    # Fallback: connection URL matches GPTHub API URL (+ optional /v1)
    base_no_v1 = _normalize_openai_url(gpthub_api_base)
    base_with_v1 = _normalize_openai_url(f'{gpthub_api_base}/v1')
    for idx, url in enumerate(urls):
        normalized = _normalize_openai_url(url)
        if normalized in {base_no_v1, base_with_v1}:
            return key_for_index(idx)

    return ''


def _forward(
    request: Request,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    timeout: int = 20,
):
    base, api_key = _resolve_gpthub_base(request)
    url = f'{base}{path}'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        response = requests.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        log.exception('Failed to reach GPTHub upstream')
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'Failed to reach GPTHub upstream: {exc.__class__.__name__}',
        ) from exc

    body: dict | list | str
    try:
        body = response.json()
    except ValueError:
        body = response.text

    if not response.ok:
        raise HTTPException(status_code=response.status_code, detail=body)
    return body


async def _forward_async(
    request: Request,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    timeout: int = 20,
):
    return await run_in_threadpool(_forward, request, method, path, payload, timeout)


def _forward_binary_get(request: Request, path: str, fallback_filename: str, timeout: int = 30) -> Response:
    base, api_key = _resolve_gpthub_base(request)
    url = f'{base}{path}'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        upstream = requests.get(url=url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        log.exception('Failed to reach GPTHub upstream')
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'Failed to reach GPTHub upstream: {exc.__class__.__name__}',
        ) from exc

    if not upstream.ok:
        try:
            body = upstream.json()
        except ValueError:
            body = upstream.text
        raise HTTPException(status_code=upstream.status_code, detail=body)

    content_disposition = upstream.headers.get(
        'Content-Disposition',
        f'attachment; filename="{fallback_filename}"',
    )
    media_type = upstream.headers.get('Content-Type', 'application/octet-stream')

    return Response(
        content=upstream.content,
        media_type=media_type,
        headers={'Content-Disposition': content_disposition},
    )


class ProviderConnectionCreateForm(BaseModel):
    provider: Literal['openai', 'ollama']
    slug: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=2, max_length=128)
    base_url: str = Field(min_length=8, max_length=512)
    api_key: str = Field(default='', max_length=1024)
    is_enabled: bool = True


class ProviderConnectionUpdateForm(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=128)
    base_url: str | None = Field(default=None, min_length=8, max_length=512)
    api_key: str | None = Field(default=None, max_length=1024)
    is_enabled: bool | None = None


class FeatureSettingsPatchForm(BaseModel):
    mws_stub_mode: bool | None = None
    mws_default_model: str | None = Field(default=None, max_length=128)
    langgraph_recursion_limit: int | None = None
    max_qa_iterations: int | None = None

    memory_recall_top_k: int | None = None
    memory_lexical_candidates: int | None = None
    memory_thread_boost: float | None = None
    memory_chat_history_token_budget: int | None = None
    memory_retrieval_token_budget: int | None = None
    memory_summary_token_budget: int | None = None
    memory_max_recent_messages: int | None = None
    memory_summary_interval: int | None = None
    memory_summary_window_messages: int | None = None
    memory_summary_min_messages: int | None = None

    auto_enable_manual_override: bool | None = None
    auto_show_routing_reason: bool | None = None
    auto_enable_domain_hint: bool | None = None
    auto_enforce_model_profile: bool | None = None
    auto_auto_downgrade_on_latency: bool | None = None
    auto_show_latency_badge: bool | None = None
    auto_allow_provider_mixing: bool | None = None
    auto_low_confidence_threshold: float | None = None
    auto_classifier_temperature: float | None = None
    auto_classifier_max_tokens: int | None = None
    auto_classifier_timeout_seconds: int | None = None
    auto_classifier_confidence_threshold: float | None = None
    auto_classifier_system_prompt_template: str | None = Field(default=None, max_length=4000)
    auto_classifier_user_prompt_template: str | None = Field(default=None, max_length=4000)
    auto_classifier_model: str | None = Field(default=None, max_length=128)
    auto_task_model_general: str | None = Field(default=None, max_length=128)
    auto_task_model_coding: str | None = Field(default=None, max_length=128)
    auto_task_model_reasoning: str | None = Field(default=None, max_length=128)
    auto_task_model_vision: str | None = Field(default=None, max_length=128)
    auto_task_model_image_generation: str | None = Field(default=None, max_length=128)
    auto_model_type_overrides_json: str | None = Field(default=None, max_length=20000)
    auto_task_override_prompt_template: str | None = Field(default=None, max_length=12000)
    default_model_avatar_url: str | None = Field(default=None, max_length=2048)

    autopilot_enable_stream_steps: bool | None = None
    autopilot_enable_auto_retry: bool | None = None
    autopilot_enable_risk_guard: bool | None = None
    autopilot_enable_partial_result_publish: bool | None = None
    autopilot_enable_cost_guard: bool | None = None
    autopilot_enable_plan_preview: bool | None = None
    autopilot_enable_human_handoff: bool | None = None

    model_court_enabled: bool | None = None
    model_court_candidates_count: int | None = None
    model_court_candidate_timeout_seconds: int | None = None
    model_court_judge_model: str | None = Field(default=None, max_length=128)
    model_court_enable_anonymous_judging: bool | None = None

    deep_research_enabled: bool | None = None
    deep_research_max_queries: int | None = None
    deep_research_max_sources: int | None = None
    deep_research_fetch_timeout_seconds: int | None = None
    deep_research_source_char_limit: int | None = None
    deep_research_max_output_tokens: int | None = None

    media_gallery_enabled: bool | None = None
    media_gallery_page_size: int | None = None
    media_gallery_max_filters: int | None = None
    media_gallery_retention_days: int | None = None

    workspace_enable_shared_workspaces: bool | None = None
    workspace_enable_file_tree_sync: bool | None = None
    workspace_enable_workspace_scoping: bool | None = None
    workspace_enable_diff_preview: bool | None = None
    workspace_enable_conflict_guards: bool | None = None
    workspace_enable_session_locks: bool | None = None
    workspace_enable_workspace_templates: bool | None = None
    workspace_max_files_per_workspace: int | None = None


class GPTHubConfigUpdateForm(BaseModel):
    api_url: str = Field(min_length=8, max_length=512)


class AutoModelRouteForm(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    input_type: Literal['text', 'image', 'audio', 'file', 'mixed'] = 'text'
    task_domain: Literal['coding', 'analysis', 'creative', 'document', 'ocr', 'support', 'general'] | None = None
    manual_model: str | None = Field(default=None, max_length=128)


class ApplyClassifierWinnerForm(BaseModel):
    model_id: str = Field(min_length=1, max_length=256)


@router.get('/health')
async def get_gpthub_health(request: Request, user=Depends(get_admin_user)):
    return _forward(request, 'GET', '/api/v1/health')


@router.get('/config')
async def get_gpthub_config(request: Request, user=Depends(get_admin_user)):
    configured_url = str(getattr(request.app.state.config, 'GPTHUB_API_URL', '') or '').strip()
    api_key = _resolve_gpthub_key(request, configured_url) if configured_url else ''
    return {
        'api_url': configured_url,
        'api_key_set': bool(api_key),
    }


@router.post('/config/update')
async def update_gpthub_config(
    request: Request,
    form_data: GPTHubConfigUpdateForm,
    user=Depends(get_admin_user),
):
    api_url = form_data.api_url.strip().rstrip('/')
    if api_url.endswith('/v1'):
        api_url = api_url[:-3]

    request.app.state.config.GPTHUB_API_URL = api_url
    _, api_key = _resolve_gpthub_base(request)

    return {
        'api_url': str(request.app.state.config.GPTHUB_API_URL or ''),
        'api_key_set': bool(api_key),
    }


@router.get('/provider-connections')
async def list_provider_connections(request: Request, user=Depends(get_admin_user)):
    return _forward(request, 'GET', '/api/v1/features/provider-connections')


@router.post('/provider-connections')
async def create_provider_connection(
    request: Request,
    form_data: ProviderConnectionCreateForm,
    user=Depends(get_admin_user),
):
    return _forward(
        request,
        'POST',
        '/api/v1/features/provider-connections',
        payload=form_data.model_dump(),
    )


@router.patch('/provider-connections/{connection_id}')
async def update_provider_connection(
    request: Request,
    connection_id: str,
    form_data: ProviderConnectionUpdateForm,
    user=Depends(get_admin_user),
):
    return _forward(
        request,
        'PATCH',
        f'/api/v1/features/provider-connections/{connection_id}',
        payload=form_data.model_dump(exclude_none=True),
    )


@router.delete('/provider-connections/{connection_id}')
async def delete_provider_connection(request: Request, connection_id: str, user=Depends(get_admin_user)):
    return _forward(
        request,
        'DELETE',
        f'/api/v1/features/provider-connections/{connection_id}',
    )


@router.get('/feature-settings')
async def get_feature_settings(request: Request, user=Depends(get_admin_user)):
    return _forward(request, 'GET', '/api/v1/features/settings')


@router.patch('/feature-settings')
async def patch_feature_settings(
    request: Request,
    form_data: FeatureSettingsPatchForm,
    user=Depends(get_admin_user),
):
    return _forward(
        request,
        'PATCH',
        '/api/v1/features/settings',
        payload=form_data.model_dump(exclude_none=True),
    )


@router.post('/feature-settings/default-avatar')
async def upload_default_model_avatar(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_admin_user),
):
    base, api_key = _resolve_gpthub_base(request)
    url = f'{base}/api/v1/features/settings/default-avatar'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    content = await file.read()
    files = {'file': (file.filename or 'avatar', content, file.content_type or 'application/octet-stream')}
    try:
        upstream = requests.post(url=url, headers=headers, files=files, timeout=30)
    except requests.RequestException as exc:
        log.exception('Failed to reach GPTHub upstream')
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'Failed to reach GPTHub upstream: {exc.__class__.__name__}',
        ) from exc

    try:
        body = upstream.json()
    except ValueError:
        body = upstream.text

    if not upstream.ok:
        raise HTTPException(status_code=upstream.status_code, detail=body)
    return body


@router.get('/feature-settings/default-avatar')
async def get_default_model_avatar(
    request: Request,
    user=Depends(get_admin_user),
):
    return _forward_binary_get(
        request=request,
        path='/v1/assets/model-avatars/default',
        fallback_filename='default-model-avatar.svg',
    )


@router.get('/media-gallery/{owner_id}')
async def list_media_gallery_items(
    request: Request,
    owner_id: str,
    page: int = 1,
    page_size: int | None = None,
    kind: str | None = None,
    search: str | None = None,
    model_id: str | None = None,
    chat_id: str | None = None,
    thread_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(get_verified_user),
):
    query: dict[str, str] = {"page": str(page)}
    if page_size is not None:
        query["page_size"] = str(page_size)
    if kind:
        query["kind"] = kind
    if search:
        query["search"] = search
    if model_id:
        query["model_id"] = model_id
    if chat_id:
        query["chat_id"] = chat_id
    if thread_id:
        query["thread_id"] = thread_id
    if date_from:
        query["date_from"] = date_from
    if date_to:
        query["date_to"] = date_to
    qs = urlencode(query)
    path = f'/api/v1/features/media-gallery/{owner_id}'
    if qs:
        path = f'{path}?{qs}'
    return _forward(request, 'GET', path)


@router.get('/media-gallery/{owner_id}/{item_id}')
async def get_media_gallery_item(
    request: Request,
    owner_id: str,
    item_id: str,
    user=Depends(get_verified_user),
):
    return _forward(request, 'GET', f'/api/v1/features/media-gallery/{owner_id}/{item_id}')


@router.delete('/media-gallery/{owner_id}/{item_id}')
async def delete_media_gallery_item(
    request: Request,
    owner_id: str,
    item_id: str,
    user=Depends(get_verified_user),
):
    return _forward(request, 'DELETE', f'/api/v1/features/media-gallery/{owner_id}/{item_id}')


@router.get('/download/{thread_id}')
async def download_generated_project(
    request: Request,
    thread_id: str,
    user=Depends(get_verified_user),
):
    base, api_key = _resolve_gpthub_base(request)
    url = f'{base}/api/v1/download/{thread_id}'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        upstream = requests.get(url=url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        log.exception('Failed to reach GPTHub download upstream')
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'Failed to reach GPTHub upstream: {exc.__class__.__name__}',
        ) from exc

    if not upstream.ok:
        try:
            body = upstream.json()
        except ValueError:
            body = upstream.text
        raise HTTPException(status_code=upstream.status_code, detail=body)

    content_disposition = upstream.headers.get(
        'Content-Disposition',
        f'attachment; filename=project_{thread_id[:8]}.zip',
    )
    media_type = upstream.headers.get('Content-Type', 'application/zip')

    return Response(
        content=upstream.content,
        media_type=media_type,
        headers={'Content-Disposition': content_disposition},
    )


@router.post('/auto-model/route')
async def route_auto_model(
    request: Request,
    form_data: AutoModelRouteForm,
    user=Depends(get_admin_user),
):
    return _forward(
        request,
        'POST',
        '/api/v1/features/auto-model/route',
        payload=form_data.model_dump(exclude_none=True),
    )


@router.post('/feature-settings/benchmarks/classifier/run')
async def run_classifier_benchmark(request: Request, user=Depends(get_admin_user)):
    return await _forward_async(
        request,
        'POST',
        '/api/v1/features/settings/benchmarks/classifier/run',
        timeout=900,
    )


@router.post('/feature-settings/benchmarks/classifier/apply')
async def apply_classifier_benchmark_winner(
    request: Request,
    form_data: ApplyClassifierWinnerForm,
    user=Depends(get_admin_user),
):
    return _forward(
        request,
        'POST',
        '/api/v1/features/settings/benchmarks/classifier/apply',
        payload=form_data.model_dump(),
    )


@router.post('/feature-settings/benchmarks/text/run')
async def run_text_benchmark(request: Request, user=Depends(get_admin_user)):
    return await _forward_async(
        request,
        'POST',
        '/api/v1/features/settings/benchmarks/text/run',
        timeout=900,
    )


@router.post('/feature-settings/benchmarks/text/tournament/run')
async def run_text_tournament_benchmark(request: Request, user=Depends(get_admin_user)):
    return await _forward_async(
        request,
        'POST',
        '/api/v1/features/settings/benchmarks/text/tournament/run',
        timeout=900,
    )


@router.get('/feature-settings/benchmarks/history')
async def get_benchmark_history(request: Request, user=Depends(get_admin_user)):
    return _forward(
        request,
        'GET',
        '/api/v1/features/settings/benchmarks/history',
    )


# ---------------------------------------------------------------------------
# Workspaces proxy
# ---------------------------------------------------------------------------

class WorkspaceCreateForm(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ''


class WorkspaceUpdateForm(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class NodeCreateForm(BaseModel):
    parent_id: str | None = None
    node_type: Literal['file', 'directory'] = 'file'
    name: str = Field(min_length=1, max_length=255)
    content: str = ''
    mime_type: str = 'text/plain'


class NodeUpdateForm(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    mime_type: str | None = None
    parent_id: str | None = None


class WorkspaceAgentMessageForm(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(default='', max_length=12000)


class WorkspaceAgentRunForm(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    model: str = Field(default='autoselect', min_length=1, max_length=128)
    autopilot: bool = False
    history: list[WorkspaceAgentMessageForm] = Field(default_factory=list)
    run_id: str | None = Field(default=None, max_length=128)


@router.get('/workspaces/{owner_id}')
async def list_workspaces(request: Request, owner_id: str, user=Depends(get_verified_user)):
    return _forward(request, 'GET', f'/api/v1/features/workspaces/{owner_id}')


@router.post('/workspaces/{owner_id}')
async def create_workspace(
    request: Request,
    owner_id: str,
    form_data: WorkspaceCreateForm,
    user=Depends(get_verified_user),
):
    return _forward(request, 'POST', f'/api/v1/features/workspaces/{owner_id}', payload=form_data.model_dump())


@router.get('/workspaces/{owner_id}/{workspace_id}')
async def get_workspace(request: Request, owner_id: str, workspace_id: str, user=Depends(get_verified_user)):
    return _forward(request, 'GET', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}')


@router.patch('/workspaces/{owner_id}/{workspace_id}')
async def update_workspace(
    request: Request,
    owner_id: str,
    workspace_id: str,
    form_data: WorkspaceUpdateForm,
    user=Depends(get_verified_user),
):
    return _forward(
        request,
        'PATCH',
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}',
        payload=form_data.model_dump(exclude_none=True),
    )


@router.delete('/workspaces/{owner_id}/{workspace_id}')
async def delete_workspace(request: Request, owner_id: str, workspace_id: str, user=Depends(get_verified_user)):
    return _forward(request, 'DELETE', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}')


@router.get('/workspaces/{owner_id}/{workspace_id}/nodes')
async def list_workspace_nodes(request: Request, owner_id: str, workspace_id: str, user=Depends(get_verified_user)):
    return _forward(request, 'GET', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes')


@router.post('/workspaces/{owner_id}/{workspace_id}/nodes')
async def create_workspace_node(
    request: Request,
    owner_id: str,
    workspace_id: str,
    form_data: NodeCreateForm,
    user=Depends(get_verified_user),
):
    return _forward(
        request,
        'POST',
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes',
        payload=form_data.model_dump(),
    )


@router.get('/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}')
async def get_workspace_node(
    request: Request, owner_id: str, workspace_id: str, node_id: str, user=Depends(get_verified_user)
):
    return _forward(request, 'GET', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}')


@router.patch('/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}')
async def update_workspace_node(
    request: Request,
    owner_id: str,
    workspace_id: str,
    node_id: str,
    form_data: NodeUpdateForm,
    user=Depends(get_verified_user),
):
    return _forward(
        request,
        'PATCH',
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}',
        payload=form_data.model_dump(exclude_none=True),
    )


@router.delete('/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}')
async def delete_workspace_node(
    request: Request, owner_id: str, workspace_id: str, node_id: str, user=Depends(get_verified_user)
):
    return _forward(request, 'DELETE', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}')


@router.get('/workspaces/{owner_id}/{workspace_id}/context')
async def get_workspace_context(request: Request, owner_id: str, workspace_id: str, user=Depends(get_verified_user)):
    return _forward(request, 'GET', f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/context')


@router.post('/workspaces/{owner_id}/{workspace_id}/agent/run')
async def run_workspace_agent(
    request: Request,
    owner_id: str,
    workspace_id: str,
    form_data: WorkspaceAgentRunForm,
    user=Depends(get_verified_user),
):
    return await _forward_async(
        request,
        'POST',
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/agent/run',
        payload=form_data.model_dump(),
        timeout=600,
    )


@router.get('/workspaces/{owner_id}/{workspace_id}/agent/status/{run_id}')
async def get_workspace_agent_status(
    request: Request,
    owner_id: str,
    workspace_id: str,
    run_id: str,
    user=Depends(get_verified_user),
):
    return await _forward_async(
        request,
        'GET',
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/agent/status/{run_id}',
    )


@router.get('/workspaces/{owner_id}/{workspace_id}/download')
async def download_workspace_archive(
    request: Request, owner_id: str, workspace_id: str, user=Depends(get_verified_user)
):
    return _forward_binary_get(
        request,
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/download',
        fallback_filename=f'workspace_{workspace_id[:8]}.zip',
        timeout=60,
    )


@router.get('/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}/download')
async def download_workspace_node(
    request: Request, owner_id: str, workspace_id: str, node_id: str, user=Depends(get_verified_user)
):
    return _forward_binary_get(
        request,
        f'/api/v1/features/workspaces/{owner_id}/{workspace_id}/nodes/{node_id}/download',
        fallback_filename=f'file_{node_id[:8]}.txt',
        timeout=60,
    )

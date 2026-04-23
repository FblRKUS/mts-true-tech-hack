from fastapi import APIRouter
from fastapi.responses import Response

from app.modules.workspaces.schemas import (
    NodeCreate,
    NodeDeleteResponse,
    NodeRecord,
    NodeUpdate,
    WorkspaceAgentRunRequest,
    WorkspaceAgentRunResponse,
    WorkspaceAgentStatusResponse,
    WorkspaceContextResponse,
    WorkspaceCreate,
    WorkspaceRecord,
    WorkspaceUpdate,
)
from app.modules.workspaces.service import (
    create_node,
    create_workspace,
    delete_node,
    delete_workspace,
    get_node,
    get_workspace,
    get_workspace_context,
    get_workspace_download,
    get_workspace_agent_status,
    get_node_download,
    list_nodes,
    list_workspaces,
    run_workspace_agent,
    update_node,
    update_workspace,
)

router = APIRouter(prefix="/features/workspaces", tags=["feature:workspaces"])


@router.get(
    "/{owner_id}",
    response_model=list[WorkspaceRecord],
    summary="List workspaces",
    description="Возвращает все пространства, принадлежащие пользователю.",
)
async def get_workspaces(owner_id: str) -> list[WorkspaceRecord]:
    return await list_workspaces(owner_id)


@router.post(
    "/{owner_id}",
    response_model=WorkspaceRecord,
    status_code=201,
    summary="Create workspace",
    description="Создаёт новое рабочее пространство для пользователя.",
)
async def add_workspace(owner_id: str, payload: WorkspaceCreate) -> WorkspaceRecord:
    return await create_workspace(owner_id, payload)


@router.get(
    "/{owner_id}/{workspace_id}",
    response_model=WorkspaceRecord,
    summary="Get workspace",
    description="Возвращает данные рабочего пространства.",
)
async def fetch_workspace(owner_id: str, workspace_id: str) -> WorkspaceRecord:
    return await get_workspace(owner_id, workspace_id)


@router.patch(
    "/{owner_id}/{workspace_id}",
    response_model=WorkspaceRecord,
    summary="Update workspace",
    description="Обновляет имя или описание рабочего пространства.",
)
async def patch_workspace(owner_id: str, workspace_id: str, payload: WorkspaceUpdate) -> WorkspaceRecord:
    return await update_workspace(owner_id, workspace_id, payload)


@router.delete(
    "/{owner_id}/{workspace_id}",
    response_model=dict,
    summary="Delete workspace",
    description="Удаляет рабочее пространство и все его узлы.",
)
async def remove_workspace(owner_id: str, workspace_id: str) -> dict:
    deleted = await delete_workspace(owner_id, workspace_id)
    return {"deleted": deleted, "workspace_id": workspace_id}


@router.get(
    "/{owner_id}/{workspace_id}/nodes",
    response_model=list[NodeRecord],
    summary="List nodes",
    description="Возвращает все узлы (файлы и директории) пространства.",
)
async def get_nodes(owner_id: str, workspace_id: str) -> list[NodeRecord]:
    return await list_nodes(owner_id, workspace_id)


@router.post(
    "/{owner_id}/{workspace_id}/nodes",
    response_model=NodeRecord,
    status_code=201,
    summary="Create node",
    description="Создаёт файл или директорию в рабочем пространстве.",
)
async def add_node(owner_id: str, workspace_id: str, payload: NodeCreate) -> NodeRecord:
    return await create_node(owner_id, workspace_id, payload)


@router.get(
    "/{owner_id}/{workspace_id}/nodes/{node_id}",
    response_model=NodeRecord,
    summary="Get node",
    description="Возвращает узел по идентификатору.",
)
async def fetch_node(owner_id: str, workspace_id: str, node_id: str) -> NodeRecord:
    return await get_node(owner_id, workspace_id, node_id)


@router.patch(
    "/{owner_id}/{workspace_id}/nodes/{node_id}",
    response_model=NodeRecord,
    summary="Update node",
    description="Обновляет содержимое, имя или расположение узла.",
)
async def patch_node(owner_id: str, workspace_id: str, node_id: str, payload: NodeUpdate) -> NodeRecord:
    return await update_node(owner_id, workspace_id, node_id, payload)


@router.delete(
    "/{owner_id}/{workspace_id}/nodes/{node_id}",
    response_model=NodeDeleteResponse,
    summary="Delete node",
    description="Удаляет узел из рабочего пространства.",
)
async def remove_node(owner_id: str, workspace_id: str, node_id: str) -> NodeDeleteResponse:
    deleted = await delete_node(owner_id, workspace_id, node_id)
    return NodeDeleteResponse(deleted=deleted, node_id=node_id)


@router.get(
    "/{owner_id}/{workspace_id}/context",
    response_model=WorkspaceContextResponse,
    summary="Get workspace context",
    description="Возвращает все файлы пространства для инъекции в контекст LLM.",
)
async def fetch_context(owner_id: str, workspace_id: str) -> WorkspaceContextResponse:
    return await get_workspace_context(owner_id, workspace_id)


@router.get(
    "/{owner_id}/{workspace_id}/download",
    response_class=Response,
    summary="Download workspace",
    description="Скачивает все файлы workspace в zip-архиве.",
)
async def download_workspace(owner_id: str, workspace_id: str) -> Response:
    data, filename = await get_workspace_download(owner_id, workspace_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{owner_id}/{workspace_id}/nodes/{node_id}/download",
    response_class=Response,
    summary="Download file node",
    description="Скачивает содержимое файла из workspace.",
)
async def download_node(owner_id: str, workspace_id: str, node_id: str) -> Response:
    data, filename, media_type = await get_node_download(owner_id, workspace_id, node_id)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{owner_id}/{workspace_id}/agent/run",
    response_model=WorkspaceAgentRunResponse,
    summary="Run workspace agent",
    description="Запускает AI-агента на выбранном workspace и применяет изменения в файлы.",
)
async def run_agent(
    owner_id: str,
    workspace_id: str,
    payload: WorkspaceAgentRunRequest,
) -> WorkspaceAgentRunResponse:
    return await run_workspace_agent(owner_id, workspace_id, payload)


@router.get(
    "/{owner_id}/{workspace_id}/agent/status/{run_id}",
    response_model=WorkspaceAgentStatusResponse,
    summary="Get workspace agent run status",
    description="Возвращает текущий этап выполнения workspace-агента.",
)
async def get_agent_status(owner_id: str, workspace_id: str, run_id: str) -> WorkspaceAgentStatusResponse:
    return await get_workspace_agent_status(owner_id, workspace_id, run_id)

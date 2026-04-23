from __future__ import annotations

import mimetypes
import posixpath
from io import BytesIO
import re
from zipfile import ZIP_DEFLATED, ZipFile
from uuid import uuid4

import structlog

from app.core.config import settings
from app.core.errors import AppError
from app.modules.workspaces.model import Workspace, WorkspaceAuditLog, WorkspaceNode
from app.modules.workspaces.repository import audit_repository, node_repository, workspace_repository
from app.modules.workspaces.schemas import (
    NodeCreate,
    NodeRecord,
    NodeUpdate,
    WorkspaceAgentMessage,
    WorkspaceAgentRunRequest,
    WorkspaceAgentRunResponse,
    WorkspaceAgentStatusResponse,
    WorkspaceContextResponse,
    WorkspaceCreate,
    WorkspaceRecord,
    WorkspaceUpdate,
)
from app.services.llm_router import llm_router

logger = structlog.get_logger(__name__)
_workspace_agent_runs: dict[str, dict[str, object]] = {}


def _workspace_path(parent_path: str | None, name: str) -> str:
    if not parent_path:
        return name
    return f"{parent_path.rstrip('/')}/{name}"


def _safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned or fallback


def _normalize_workspace_file_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    normalized = normalized.lstrip("./").lstrip("/")
    normalized = posixpath.normpath(normalized)
    if normalized in {".", ""}:
        return ""
    if normalized.startswith("../") or normalized == "..":
        return ""
    return normalized


def _normalize_workspace_file_map(raw: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_path, raw_content in (raw or {}).items():
        path = _normalize_workspace_file_path(raw_path)
        if not path:
            continue
        normalized[path] = str(raw_content or "")
    return normalized


def _guess_mime_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "text/plain"


def _build_workspace_context(file_map: dict[str, str], max_files: int = 40, max_chars: int = 6000) -> str:
    items = sorted(file_map.items())[:max_files]
    chunks: list[str] = []
    for path, content in items:
        trimmed = content[:max_chars]
        if len(content) > max_chars:
            trimmed += "\n... [truncated]"
        chunks.append(f"### {path}\n{trimmed}")
    return "\n\n".join(chunks)


def _strip_generated_files_section(text: str) -> str:
    marker = "## 📁 Generated Files"
    index = text.find(marker)
    if index == -1:
        return text.strip()
    head = text[:index].rstrip()
    if head.endswith("---"):
        head = head[:-3].rstrip()
    return head


def _serialize_history(history: list[WorkspaceAgentMessage], max_messages: int = 16) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    for message in history[-max_messages:]:
        role = message.role if message.role in {"user", "assistant"} else "user"
        content = str(message.content or "").strip()
        if not content:
            continue
        serialized.append({"role": role, "content": content})
    return serialized


def _set_workspace_agent_status(
    run_id: str,
    *,
    stage: str | None = None,
    done: bool | None = None,
    error: str | None = None,
    steps: list[str] | None = None,
) -> None:
    if run_id not in _workspace_agent_runs and len(_workspace_agent_runs) >= 256:
        oldest_run_id = next(iter(_workspace_agent_runs))
        _workspace_agent_runs.pop(oldest_run_id, None)
    current = _workspace_agent_runs.get(run_id, {"run_id": run_id, "stage": "", "done": False, "error": "", "steps": []})
    updated = {
        "run_id": run_id,
        "stage": stage if stage is not None else str(current.get("stage", "")),
        "done": bool(done) if done is not None else bool(current.get("done", False)),
        "error": error if error is not None else str(current.get("error", "")),
        "steps": steps if steps is not None else list(current.get("steps", [])),
    }
    _workspace_agent_runs[run_id] = updated


def _get_workspace_agent_status(run_id: str) -> dict[str, object] | None:
    status = _workspace_agent_runs.get(run_id)
    if status is None:
        return None
    return {
        "run_id": str(status.get("run_id", run_id)),
        "stage": str(status.get("stage", "")),
        "done": bool(status.get("done", False)),
        "error": str(status.get("error", "")),
        "steps": list(status.get("steps", [])),
    }


async def _replace_workspace_tree(workspace_id: str, file_map: dict[str, str]) -> None:
    await node_repository.delete_by_workspace(workspace_id)
    if not file_map:
        return

    directory_id_by_path: dict[str, str] = {}
    directory_paths: set[str] = set()

    for file_path in file_map.keys():
        parts = file_path.split("/")
        for idx in range(1, len(parts)):
            directory_paths.add("/".join(parts[:idx]))

    for directory_path in sorted(directory_paths, key=lambda value: (value.count("/"), value)):
        parent_path = directory_path.rsplit("/", 1)[0] if "/" in directory_path else None
        parent_id = directory_id_by_path.get(parent_path or "")
        name = directory_path.rsplit("/", 1)[-1]
        node = WorkspaceNode(
            id=uuid4().hex,
            workspace_id=workspace_id,
            parent_id=parent_id,
            node_type="directory",
            name=name,
            path=directory_path,
            content="",
            mime_type="inode/directory",
            size_bytes=0,
        )
        saved = await node_repository.insert(node)
        directory_id_by_path[directory_path] = saved.id

    for file_path, content in sorted(file_map.items()):
        parent_path = file_path.rsplit("/", 1)[0] if "/" in file_path else None
        parent_id = directory_id_by_path.get(parent_path or "")
        name = file_path.rsplit("/", 1)[-1]
        node = WorkspaceNode(
            id=uuid4().hex,
            workspace_id=workspace_id,
            parent_id=parent_id,
            node_type="file",
            name=name,
            path=file_path,
            content=content,
            mime_type=_guess_mime_type(file_path),
            size_bytes=len(content.encode("utf-8")),
        )
        await node_repository.insert(node)


async def _audit(
    workspace_id: str,
    actor_id: str,
    action: str,
    node_id: str | None = None,
    node_path: str = "",
    detail: str = "",
    actor_type: str = "user",
) -> None:
    log = WorkspaceAuditLog(
        id=uuid4().hex,
        workspace_id=workspace_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        node_id=node_id,
        node_path=node_path,
        detail=detail,
    )
    await audit_repository.insert(log)


async def list_workspaces(owner_id: str) -> list[WorkspaceRecord]:
    rows = await workspace_repository.list_by_owner(owner_id)
    return [WorkspaceRecord.model_validate(r) for r in rows]


async def create_workspace(owner_id: str, payload: WorkspaceCreate) -> WorkspaceRecord:
    workspace = Workspace(
        id=uuid4().hex,
        owner_id=owner_id,
        name=payload.name,
        description=payload.description,
    )
    saved = await workspace_repository.insert(workspace)
    if settings.workspace_enable_workspace_templates:
        default_content = (
            f"# {payload.name}\n\n"
            "This workspace was initialized from the default template.\n"
        )
        template_node = WorkspaceNode(
            id=uuid4().hex,
            workspace_id=saved.id,
            parent_id=None,
            node_type="file",
            name="README.md",
            path="README.md",
            content=default_content,
            mime_type="text/markdown",
            size_bytes=len(default_content.encode()),
        )
        await node_repository.insert(template_node)
        await _audit(saved.id, owner_id, "template_init", node_id=template_node.id, node_path="README.md")
    await _audit(saved.id, owner_id, "create_workspace", detail=f"name={payload.name}")
    logger.info("workspace created", workspace_id=saved.id, owner_id=owner_id)
    return WorkspaceRecord.model_validate(saved)


async def get_workspace(owner_id: str, workspace_id: str) -> WorkspaceRecord:
    workspace = await workspace_repository.get(workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise AppError(code="not_found", message="Workspace not found", status_code=404)
    return WorkspaceRecord.model_validate(workspace)


async def update_workspace(owner_id: str, workspace_id: str, payload: WorkspaceUpdate) -> WorkspaceRecord:
    workspace = await workspace_repository.get(workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise AppError(code="not_found", message="Workspace not found", status_code=404)
    if payload.name is not None:
        workspace.name = payload.name
    if payload.description is not None:
        workspace.description = payload.description
    saved = await workspace_repository.update(workspace)
    await _audit(workspace_id, owner_id, "update_workspace", detail=str(payload.model_dump(exclude_none=True)))
    return WorkspaceRecord.model_validate(saved)


async def delete_workspace(owner_id: str, workspace_id: str) -> bool:
    workspace = await workspace_repository.get(workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise AppError(code="not_found", message="Workspace not found", status_code=404)
    await node_repository.delete_by_workspace(workspace_id)
    deleted = await workspace_repository.delete_by_id(workspace_id)
    if deleted:
        logger.info("workspace deleted", workspace_id=workspace_id, owner_id=owner_id)
    return deleted


async def list_nodes(owner_id: str, workspace_id: str) -> list[NodeRecord]:
    await get_workspace(owner_id, workspace_id)
    rows = await node_repository.list_by_workspace(workspace_id)
    return [NodeRecord.model_validate(r) for r in rows]


async def _count_file_nodes(workspace_id: str) -> int:
    rows = await node_repository.list_by_workspace(workspace_id)
    return sum(1 for row in rows if row.node_type == "file")


async def _validate_workspace_file_limit(workspace_id: str, file_count: int) -> None:
    limit = max(1, int(settings.workspace_max_files_per_workspace))
    if file_count > limit:
        raise AppError(
            code="workspace_limit_exceeded",
            message=f"Workspace file limit exceeded: {file_count}/{limit}",
            status_code=422,
        )


async def create_node(owner_id: str, workspace_id: str, payload: NodeCreate) -> NodeRecord:
    await get_workspace(owner_id, workspace_id)

    parent_path: str | None = None
    if payload.parent_id:
        parent = await node_repository.get(payload.parent_id)
        if parent is None or parent.workspace_id != workspace_id:
            raise AppError(code="not_found", message="Parent node not found", status_code=404)
        if parent.node_type != "directory":
            raise AppError(code="validation_error", message="Parent must be a directory", status_code=422)
        parent_path = parent.path

    path = _workspace_path(parent_path, payload.name)

    existing = await node_repository.get_by_path(workspace_id, path)
    if existing is not None:
        raise AppError(code="conflict", message=f"Node already exists at path '{path}'", status_code=409)

    if payload.node_type == "file":
        existing_files = await _count_file_nodes(workspace_id)
        await _validate_workspace_file_limit(workspace_id, existing_files + 1)

    content = payload.content if payload.node_type == "file" else ""
    node = WorkspaceNode(
        id=uuid4().hex,
        workspace_id=workspace_id,
        parent_id=payload.parent_id,
        node_type=payload.node_type,
        name=payload.name,
        path=path,
        content=content,
        mime_type=payload.mime_type,
        size_bytes=len(content.encode()),
    )
    saved = await node_repository.insert(node)
    await _audit(workspace_id, owner_id, f"create_{payload.node_type}", node_id=saved.id, node_path=path)
    return NodeRecord.model_validate(saved)


async def get_node(owner_id: str, workspace_id: str, node_id: str) -> NodeRecord:
    await get_workspace(owner_id, workspace_id)
    node = await node_repository.get(node_id)
    if node is None or node.workspace_id != workspace_id:
        raise AppError(code="not_found", message="Node not found", status_code=404)
    return NodeRecord.model_validate(node)


async def update_node(owner_id: str, workspace_id: str, node_id: str, payload: NodeUpdate) -> NodeRecord:
    await get_workspace(owner_id, workspace_id)
    node = await node_repository.get(node_id)
    if node is None or node.workspace_id != workspace_id:
        raise AppError(code="not_found", message="Node not found", status_code=404)

    if payload.name is not None and payload.name != node.name:
        parent_path: str | None = None
        if node.parent_id:
            parent = await node_repository.get(node.parent_id)
            parent_path = parent.path if parent else None
        new_path = _workspace_path(parent_path, payload.name)
        conflict = await node_repository.get_by_path(workspace_id, new_path)
        if conflict and conflict.id != node_id:
            raise AppError(code="conflict", message=f"Node already exists at '{new_path}'", status_code=409)
        node.name = payload.name
        node.path = new_path

    if payload.content is not None:
        node.content = payload.content
        node.size_bytes = len(payload.content.encode())

    if payload.mime_type is not None:
        node.mime_type = payload.mime_type

    if payload.parent_id is not None:
        parent = await node_repository.get(payload.parent_id)
        if parent is None or parent.workspace_id != workspace_id:
            raise AppError(code="not_found", message="New parent node not found", status_code=404)
        if parent.node_type != "directory":
            raise AppError(code="validation_error", message="New parent must be a directory", status_code=422)
        node.parent_id = payload.parent_id
        node.path = _workspace_path(parent.path, node.name)

    saved = await node_repository.update(node)
    await _audit(workspace_id, owner_id, "update_node", node_id=node_id, node_path=saved.path)
    return NodeRecord.model_validate(saved)


async def delete_node(owner_id: str, workspace_id: str, node_id: str) -> bool:
    await get_workspace(owner_id, workspace_id)
    node = await node_repository.get(node_id)
    if node is None or node.workspace_id != workspace_id:
        raise AppError(code="not_found", message="Node not found", status_code=404)
    deleted = await node_repository.delete_by_id(node_id)
    if deleted:
        await _audit(workspace_id, owner_id, "delete_node", node_id=node_id, node_path=node.path)
    return deleted


async def get_workspace_context(owner_id: str, workspace_id: str) -> WorkspaceContextResponse:
    """Returns all file nodes (not directories) for injection into LLM context."""
    await get_workspace(owner_id, workspace_id)
    rows = await node_repository.list_by_workspace(workspace_id)
    files = [NodeRecord.model_validate(r) for r in rows if r.node_type == "file"]
    return WorkspaceContextResponse(workspace_id=workspace_id, files=files)


async def get_node_download(owner_id: str, workspace_id: str, node_id: str) -> tuple[bytes, str, str]:
    await get_workspace(owner_id, workspace_id)
    node = await node_repository.get(node_id)
    if node is None or node.workspace_id != workspace_id:
        raise AppError(code="not_found", message="Node not found", status_code=404)
    if node.node_type != "file":
        raise AppError(code="validation_error", message="Only files can be downloaded", status_code=422)

    filename = _safe_filename(node.name or node.path, f"{node.id}.txt")
    media_type = node.mime_type or "text/plain"
    data = (node.content or "").encode("utf-8")
    return data, filename, media_type


async def get_workspace_download(owner_id: str, workspace_id: str) -> tuple[bytes, str]:
    workspace = await workspace_repository.get(workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise AppError(code="not_found", message="Workspace not found", status_code=404)

    rows = await node_repository.list_by_workspace(workspace_id)
    file_nodes = [row for row in rows if row.node_type == "file"]

    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for node in file_nodes:
            archive.writestr(node.path or node.name or f"{node.id}.txt", node.content or "")

    filename = _safe_filename(workspace.name, f"workspace-{workspace.id[:8]}") + ".zip"
    return buffer.getvalue(), filename


async def run_workspace_agent(
    owner_id: str,
    workspace_id: str,
    payload: WorkspaceAgentRunRequest,
) -> WorkspaceAgentRunResponse:
    await get_workspace(owner_id, workspace_id)
    rows = await node_repository.list_by_workspace(workspace_id)
    workspace_scope_enabled = bool(settings.workspace_enable_workspace_scoping)
    scoped_workspace = {
        row.path: row.content
        for row in rows
        if row.node_type == "file" and isinstance(row.path, str) and row.path.strip()
    }
    current_workspace = _normalize_workspace_file_map(scoped_workspace if workspace_scope_enabled else {})

    user_message = payload.message.strip()
    if not user_message:
        raise AppError(code="validation_error", message="Message is required", status_code=422)

    history_messages = _serialize_history(payload.history)
    selected_model = payload.model.strip() or "autoselect"
    run_id = (payload.run_id or "").strip() or uuid4().hex

    response_text = ""
    next_workspace = current_workspace.copy()
    steps: list[str] = []
    _set_workspace_agent_status(run_id, stage="Подготавливаю запуск", done=False, error="", steps=steps)

    def _set_stage(stage: str, *, add_step: bool = False) -> None:
        if add_step and (not steps or steps[-1] != stage):
            steps.append(stage)
        _set_workspace_agent_status(run_id, stage=stage, done=False, error="", steps=list(steps))

    step_labels = {
        "supervisor": "Координатор планирует шаги",
        "designer": "Дизайнер формирует спецификацию",
        "frontend_dev": "Frontend-агент пишет интерфейс",
        "backend_dev": "Backend-агент пишет серверный код",
        "devops": "DevOps-агент готовит инфраструктуру",
        "qa_tester": "QA-агент запускает проверки",
    }

    try:
        if payload.autopilot:
            from app.agents.graph import create_initial_state, get_agent_graph

            if workspace_scope_enabled and current_workspace:
                _set_stage(f"Прочитал {len(current_workspace)} файлов из workspace", add_step=True)
            elif not workspace_scope_enabled:
                _set_stage("Workspace scoping отключен — запускаю без файлового контекста", add_step=True)
            else:
                _set_stage("Workspace пустой — начинаю с нуля", add_step=True)
            graph = await get_agent_graph()
            graph_input = create_initial_state(
                user_request=user_message,
                user_id=owner_id,
                thread_id=f"workspace_{workspace_id}",
                request_model=selected_model,
                messages=history_messages + [{"role": "user", "content": user_message}],
                memory_context="",
            )
            graph_input["workspace"] = current_workspace.copy()
            config = {
                "configurable": {"thread_id": f"workspace_{workspace_id}"},
                "recursion_limit": settings.langgraph_recursion_limit,
            }

            final_state = None
            seen_nodes: set[str] = set()
            async for state in graph.astream(graph_input, config):
                final_state = state
                if isinstance(state, dict) and state:
                    node_name = next(iter(state.keys()))
                    if node_name not in seen_nodes:
                        seen_nodes.add(node_name)
                        _set_stage(step_labels.get(node_name, f"Выполняю шаг: {node_name}"), add_step=True)

            graph_output = list(final_state.values())[-1] if isinstance(final_state, dict) and final_state else {}
            if not isinstance(graph_output, dict):
                graph_output = {}

            raw_response = str(graph_output.get("final_response") or "Task completed.")
            response_text = _strip_generated_files_section(raw_response)

            generated_workspace = graph_output.get("workspace", current_workspace)
            if not isinstance(generated_workspace, dict):
                generated_workspace = current_workspace
            next_workspace = _normalize_workspace_file_map(generated_workspace)
            if settings.workspace_enable_file_tree_sync:
                _set_stage("Синхронизирую изменения в дерево файлов workspace", add_step=True)
            else:
                _set_stage("File tree sync отключен — изменения не применяются в workspace", add_step=True)
        else:
            if workspace_scope_enabled:
                _set_stage(f"Прочитал {len(current_workspace)} файлов из workspace", add_step=True)
            else:
                _set_stage("Workspace scoping отключен — отвечаю без файлового контекста", add_step=True)
            _set_stage("Готовлю ответ модели с контекстом workspace", add_step=True)
            workspace_context = _build_workspace_context(current_workspace)
            prompt_messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": (
                        "Ты ассистент для редактирования выбранного workspace. "
                        "Отвечай на языке пользователя и не выдумывай несуществующие файлы."
                    ),
                },
            ]
            if workspace_context:
                prompt_messages.append(
                    {
                        "role": "system",
                        "content": f"Контекст файлов workspace:\n{workspace_context}",
                    }
                )
            prompt_messages.extend(history_messages)
            prompt_messages.append({"role": "user", "content": user_message})

            completion = await llm_router.chat_completion(
                messages=prompt_messages,
                model=selected_model,
                temperature=0.4,
                max_tokens=1400,
            )
            response_text = str(completion["choices"][0]["message"]["content"] or "").strip()

        changed_paths = sorted(
            {
                *{path for path in current_workspace.keys() if current_workspace.get(path) != next_workspace.get(path)},
                *{path for path in next_workspace.keys() if next_workspace.get(path) != current_workspace.get(path)},
            }
        )

        if payload.autopilot and settings.workspace_enable_file_tree_sync:
            await _validate_workspace_file_limit(workspace_id, len(next_workspace))
            await _replace_workspace_tree(workspace_id, next_workspace)
            await _audit(
                workspace_id,
                owner_id,
                "agent_apply_workspace",
                detail=f"files={len(next_workspace)}, changed={len(changed_paths)}",
                actor_type="agent",
            )

        _set_workspace_agent_status(run_id, stage="Готово", done=True, error="", steps=list(steps))
        return WorkspaceAgentRunResponse(
            run_id=run_id,
            response=response_text or "Done.",
            applied_files=len(next_workspace) if (payload.autopilot and settings.workspace_enable_file_tree_sync) else 0,
            changed_paths=(
                changed_paths
                if payload.autopilot and settings.workspace_enable_file_tree_sync and settings.workspace_enable_diff_preview
                else []
            ),
            steps=steps,
        )
    except Exception as exc:
        _set_workspace_agent_status(run_id, stage="Ошибка выполнения", done=True, error=str(exc), steps=list(steps))
        raise


async def get_workspace_agent_status(owner_id: str, workspace_id: str, run_id: str) -> WorkspaceAgentStatusResponse:
    await get_workspace(owner_id, workspace_id)
    run_id_value = run_id.strip()
    if not run_id_value:
        raise AppError(code="validation_error", message="run_id is required", status_code=422)
    status = _get_workspace_agent_status(run_id_value)
    if status is None:
        raise AppError(code="not_found", message="Run status not found", status_code=404)
    return WorkspaceAgentStatusResponse.model_validate(status)

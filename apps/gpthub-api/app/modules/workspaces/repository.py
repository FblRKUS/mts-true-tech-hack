from __future__ import annotations

from sqlalchemy import delete, select

from app.core.database import db_manager
from app.modules.workspaces.model import Workspace, WorkspaceAuditLog, WorkspaceNode


class WorkspaceRepository:
    async def list_by_owner(self, owner_id: str) -> list[Workspace]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(Workspace).where(Workspace.owner_id == owner_id).order_by(Workspace.created_at)
            )
            return list(result.scalars().all())

    async def get(self, workspace_id: str) -> Workspace | None:
        async with db_manager.get_session() as session:
            result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
            return result.scalar_one_or_none()

    async def insert(self, workspace: Workspace) -> Workspace:
        async with db_manager.get_session() as session:
            session.add(workspace)
            await session.flush()
            await session.refresh(workspace)
            return workspace

    async def update(self, workspace: Workspace) -> Workspace:
        async with db_manager.get_session() as session:
            merged = await session.merge(workspace)
            await session.flush()
            await session.refresh(merged)
            return merged

    async def delete_by_id(self, workspace_id: str) -> bool:
        async with db_manager.get_session() as session:
            result = await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            return (result.rowcount or 0) > 0


class WorkspaceNodeRepository:
    async def list_by_workspace(self, workspace_id: str) -> list[WorkspaceNode]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(WorkspaceNode)
                .where(WorkspaceNode.workspace_id == workspace_id)
                .order_by(WorkspaceNode.path)
            )
            return list(result.scalars().all())

    async def list_by_parent(self, workspace_id: str, parent_id: str | None) -> list[WorkspaceNode]:
        async with db_manager.get_session() as session:
            stmt = select(WorkspaceNode).where(
                WorkspaceNode.workspace_id == workspace_id,
                WorkspaceNode.parent_id == parent_id,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get(self, node_id: str) -> WorkspaceNode | None:
        async with db_manager.get_session() as session:
            result = await session.execute(select(WorkspaceNode).where(WorkspaceNode.id == node_id))
            return result.scalar_one_or_none()

    async def get_by_path(self, workspace_id: str, path: str) -> WorkspaceNode | None:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(WorkspaceNode).where(
                    WorkspaceNode.workspace_id == workspace_id,
                    WorkspaceNode.path == path,
                )
            )
            return result.scalar_one_or_none()

    async def insert(self, node: WorkspaceNode) -> WorkspaceNode:
        async with db_manager.get_session() as session:
            session.add(node)
            await session.flush()
            await session.refresh(node)
            return node

    async def update(self, node: WorkspaceNode) -> WorkspaceNode:
        async with db_manager.get_session() as session:
            merged = await session.merge(node)
            await session.flush()
            await session.refresh(merged)
            return merged

    async def delete_by_id(self, node_id: str) -> bool:
        async with db_manager.get_session() as session:
            result = await session.execute(delete(WorkspaceNode).where(WorkspaceNode.id == node_id))
            return (result.rowcount or 0) > 0

    async def delete_by_workspace(self, workspace_id: str) -> int:
        async with db_manager.get_session() as session:
            result = await session.execute(
                delete(WorkspaceNode).where(WorkspaceNode.workspace_id == workspace_id)
            )
            return result.rowcount or 0


class WorkspaceAuditRepository:
    async def insert(self, log: WorkspaceAuditLog) -> WorkspaceAuditLog:
        async with db_manager.get_session() as session:
            session.add(log)
            await session.flush()
            await session.refresh(log)
            return log

    async def list_by_workspace(self, workspace_id: str, limit: int = 100) -> list[WorkspaceAuditLog]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(WorkspaceAuditLog)
                .where(WorkspaceAuditLog.workspace_id == workspace_id)
                .order_by(WorkspaceAuditLog.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())


workspace_repository = WorkspaceRepository()
node_repository = WorkspaceNodeRepository()
audit_repository = WorkspaceAuditRepository()

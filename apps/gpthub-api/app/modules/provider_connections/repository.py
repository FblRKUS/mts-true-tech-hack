from __future__ import annotations

from sqlalchemy import delete, select

from app.core.database import db_manager
from app.modules.provider_connections.model import ProviderConnection


class ProviderConnectionRepository:
    async def list_all(self) -> list[ProviderConnection]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ProviderConnection).order_by(ProviderConnection.provider, ProviderConnection.display_name)
            )
            return list(result.scalars().all())

    async def list_enabled(self) -> list[ProviderConnection]:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ProviderConnection)
                .where(ProviderConnection.is_enabled.is_(True))
                .order_by(ProviderConnection.provider, ProviderConnection.display_name)
            )
            return list(result.scalars().all())

    async def get_by_id(self, connection_id: str) -> ProviderConnection | None:
        async with db_manager.get_session() as session:
            result = await session.execute(select(ProviderConnection).where(ProviderConnection.id == connection_id))
            return result.scalar_one_or_none()

    async def get_by_provider_slug(self, provider: str, slug: str) -> ProviderConnection | None:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(ProviderConnection).where(
                    ProviderConnection.provider == provider,
                    ProviderConnection.slug == slug,
                )
            )
            return result.scalar_one_or_none()

    async def insert(self, connection: ProviderConnection) -> ProviderConnection:
        async with db_manager.get_session() as session:
            session.add(connection)
            await session.flush()
            await session.refresh(connection)
            return connection

    async def update(self, connection: ProviderConnection) -> ProviderConnection:
        async with db_manager.get_session() as session:
            merged = await session.merge(connection)
            await session.flush()
            await session.refresh(merged)
            return merged

    async def delete_by_id(self, connection_id: str) -> bool:
        async with db_manager.get_session() as session:
            result = await session.execute(delete(ProviderConnection).where(ProviderConnection.id == connection_id))
            return (result.rowcount or 0) > 0


provider_connection_repository = ProviderConnectionRepository()

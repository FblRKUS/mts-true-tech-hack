from __future__ import annotations

from sqlalchemy import select

from app.core.database import db_manager
from app.modules.feature_settings.model import FeatureSetting


class FeatureSettingsRepository:
    async def list_all(self) -> list[FeatureSetting]:
        async with db_manager.get_session() as session:
            result = await session.execute(select(FeatureSetting).order_by(FeatureSetting.key))
            return list(result.scalars().all())

    async def get(self, key: str) -> FeatureSetting | None:
        async with db_manager.get_session() as session:
            result = await session.execute(select(FeatureSetting).where(FeatureSetting.key == key))
            return result.scalar_one_or_none()

    async def upsert(self, key: str, value: dict) -> FeatureSetting:
        async with db_manager.get_session() as session:
            existing = await session.get(FeatureSetting, key)
            if existing is None:
                existing = FeatureSetting(key=key, value=value)
                session.add(existing)
            else:
                existing.value = value
            await session.flush()
            await session.refresh(existing)
            return existing


feature_settings_repository = FeatureSettingsRepository()

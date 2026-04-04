import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from langgraph.checkpoint.memory import MemorySaver
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages database connections for both SQLAlchemy and LangGraph checkpointer."""
    
    def __init__(self):
        # SQLAlchemy async engine for general DB operations
        self.engine = create_async_engine(
            settings.async_database_url,
            echo=settings.debug,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20
        )
        self.async_session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # MemorySaver for LangGraph checkpointing (in-memory for now)
        self._checkpointer: MemorySaver | None = None
    
    async def initialize_checkpointer(self) -> MemorySaver:
        """Initialize MemorySaver for LangGraph."""
        if self._checkpointer is None:
            logger.info("Initializing LangGraph checkpointer...")
            
            # Create MemorySaver instance
            self._checkpointer = MemorySaver()
            
            logger.info("LangGraph checkpointer initialized successfully")
        
        return self._checkpointer
    
    @asynccontextmanager
    async def get_session(self):
        """Provide async database session."""
        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    async def close(self):
        """Close all database connections."""
        logger.info("Closing database connections...")
        
        # MemorySaver doesn't need explicit closing
        
        await self.engine.dispose()
        logger.info("Database connections closed")


# Global database manager instance
db_manager = DatabaseManager()

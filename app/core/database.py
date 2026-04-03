import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import AsyncConnectionPool
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
        
        # PostgresSaver pool for LangGraph checkpointing (uses psycopg sync API)
        self._checkpointer_pool: AsyncConnectionPool | None = None
        self._checkpointer: PostgresSaver | None = None
    
    async def initialize_checkpointer(self) -> PostgresSaver:
        """Initialize PostgresSaver with connection pool for LangGraph."""
        if self._checkpointer is None:
            logger.info("Initializing LangGraph checkpointer...")
            
            # Create async connection pool for psycopg
            self._checkpointer_pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=10,
                kwargs={"autocommit": True, "prepare_threshold": 0}
            )
            
            # Wait for pool to open
            await self._checkpointer_pool.__aenter__()
            
            # Create PostgresSaver instance
            self._checkpointer = PostgresSaver(self._checkpointer_pool)
            
            # Setup tables
            await self._checkpointer.setup()
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
        
        if self._checkpointer_pool:
            await self._checkpointer_pool.__aexit__(None, None, None)
        
        await self.engine.dispose()
        logger.info("Database connections closed")


# Global database manager instance
db_manager = DatabaseManager()

from fastapi import FastAPI
from contextlib import asynccontextmanager
import structlog
from app.core.config import settings
from app.core.database import db_manager
from app.api import chat

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    
    # Startup
    logger.info("Starting MTS Agentic AI application...")
    
    # Initialize LangGraph checkpointer (PostgresSaver)
    await db_manager.initialize_checkpointer()
    
    logger.info(
        "Application started successfully",
        host=settings.app_host,
        port=settings.app_port
    )
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    await db_manager.close()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="MTS True Tech Hack - Agentic AI",
    description="Multi-agent AI system with OpenAI-compatible API",
    version="1.0.0",
    lifespan=lifespan
)

# Include routers
app.include_router(chat.router, prefix="/v1", tags=["chat"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "mts-agentic-ai",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "MTS Agentic AI API",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "health": "/health",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )

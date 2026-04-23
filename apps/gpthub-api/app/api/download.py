from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Any
import zipfile
import io
import posixpath
import structlog
from app.agents.graph import get_agent_graph

router = APIRouter()
logger = structlog.get_logger(__name__)


def _sanitize_zip_path(file_path: str) -> str:
    """
    Prevent Zip Slip by stripping absolute paths and directory traversal components.

    Normalises the path so that it is always relative and cannot escape the
    extraction directory when the end-user unpacks the archive.
    """
    # Normalise separators and collapse '..', '.', etc.
    normalised = posixpath.normpath(file_path.replace("\\", "/"))
    # Drop any leading '/' or drive-letter prefix that normpath may leave
    normalised = normalised.lstrip("/")
    # After stripping, a pure traversal like '../../etc/passwd' becomes
    # 'etc/passwd'; reject any remaining '..' components as an extra safeguard.
    parts = normalised.split("/")
    safe_parts = [p for p in parts if p and p != ".."]
    return "/".join(safe_parts) if safe_parts else "unnamed_file"


@router.get("/download/{thread_id}")
async def download_project_zip(thread_id: str):
    """
    Download all generated files from a conversation as a ZIP archive.
    
    Retrieves the workspace from LangGraph checkpoint and creates a ZIP file.
    """
    try:
        logger.info("Download request", thread_id=thread_id)
        
        # Get checkpointer from compiled graph (CRITICAL: must be same instance used during execution)
        graph = await get_agent_graph()
        checkpointer = graph.checkpointer
        
        # Get latest state for this thread
        config = {"configurable": {"thread_id": thread_id}}
        
        # Try to get state from checkpoint
        checkpoint = await checkpointer.aget(config)
        
        logger.info("Checkpoint retrieved", has_checkpoint=bool(checkpoint), thread_id=thread_id)
        
        if not checkpoint:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Extract files from checkpoint - collect from ALL sources
        state = checkpoint.get("channel_values", {})
        
        # Merge files from all possible sources
        all_files = {}
        all_files.update(state.get("workspace", {}))
        all_files.update(state.get("design_artifacts", {}))
        all_files.update(state.get("frontend_code", {}))
        all_files.update(state.get("backend_code", {}))
        all_files.update(state.get("devops_configs", {}))
        
        logger.info("Checkpoint state", 
                   keys=list(state.keys()), 
                   workspace_files=len(state.get("workspace", {})),
                   total_files=len(all_files))
        
        if not all_files:
            raise HTTPException(status_code=404, detail="No files generated in this project")
        
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_path, file_content in all_files.items():
                safe_path = _sanitize_zip_path(file_path)
                zip_file.writestr(safe_path, file_content)
        
        # Seek to beginning of buffer
        zip_buffer.seek(0)
        
        logger.info("ZIP archive created", thread_id=thread_id, num_files=len(all_files))
        
        # Return ZIP as downloadable file
        return StreamingResponse(
            iter([zip_buffer.getvalue()]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=project_{thread_id[:8]}.zip"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create ZIP", error=str(e), thread_id=thread_id)
        raise HTTPException(status_code=500, detail="Failed to create ZIP archive")
from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def backend_dev_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backend Developer Agent with Workspace Integration.
    
    CRITICAL: Writes code to shared workspace instead of state messages.
    Reads QA patches and applies fixes iteratively.
    
    Responsibilities:
    - Write server-side code (FastAPI, Flask, etc.)
    - Design and implement API endpoints
    - Create database schemas
    - Apply QA patches when tests fail
    """
    
    logger.info("Backend developer started")
    
    system_prompt = """You are an expert Backend Developer specializing in Python and FastAPI.

**CRITICAL INSTRUCTIONS:**
1. Your code will be saved to a shared workspace (NOT in chat messages)
2. If QA provided patches, you MUST apply them precisely
3. Generate complete, working code with all dependencies in requirements.txt
4. Do NOT include code snippets in your response text - only in the JSON output

**Output Format:**
Respond ONLY with JSON mapping file paths to code content:
{
    "main.py": "<full code here>",
    "api/routes.py": "<full code here>",
    "models/schemas.py": "<full code here>",
    "services/business_logic.py": "<full code here>",
    "requirements.txt": "fastapi==0.109.0\nuvicorn==0.27.0\npydantic==2.5.3"
}

**QA Patches:**
If QA provided patches, apply them to the specified files EXACTLY as instructed.
"""
    
    user_request = state.get("user_request", "")
    task_description = state.get("current_task_description", "Implement backend API")
    design = state.get("design_artifacts", {})
    qa_feedback_list = state.get("qa_feedback", [])
    workspace = state.get("workspace", {})
    
    # Extract latest QA feedback with patches
    latest_qa_feedback = qa_feedback_list[-1] if qa_feedback_list else None
    qa_patches = []
    if latest_qa_feedback and isinstance(latest_qa_feedback, dict):
        qa_patches = latest_qa_feedback.get("patches", [])
        qa_message = latest_qa_feedback.get("message", "")
    
    # Build context from workspace (if code already exists)
    workspace_context = ""
    if workspace:
        workspace_context = "\n**Existing Workspace Files:**\n"
        for filepath in workspace.keys():
            workspace_context += f"- {filepath}\n"
    
    # Build QA patches context
    patches_context = ""
    if qa_patches:
        patches_context = "\n**QA Patches to Apply:**\n"
        for i, patch in enumerate(qa_patches, 1):
            patches_context += f"{i}. File: {patch.get('file_path')}\n"
            patches_context += f"   Issue: {patch.get('issue')}\n"
            patches_context += f"   Fix: {patch.get('fix')}\n\n"
    
    prompt = f"""
User Request: {user_request}

Design Context:
- Components: {design.get('component_structure', [])}
- User Flow: {design.get('user_flow', 'Standard CRUD operations')}

Task: {task_description}
{workspace_context}
{patches_context}

{'**This is a fix iteration. Apply the QA patches above.**' if qa_patches else '**This is the initial implementation.**'}

Generate complete, production-ready backend code with FastAPI.
Include ALL dependencies in requirements.txt.
"""
    
    try:
        # Use model from user request
        model = state.get("request_model", "openai/qwen3-235b-a22b-2507")
        
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model=model,
            temperature=0.5,
            max_tokens=3000,
            system_prompt=system_prompt
        )
        
        # Parse JSON response
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        backend_files = json.loads(response_text.strip())
        
        logger.info("Backend code generated", num_files=len(backend_files))
        
        # CRITICAL: Update workspace instead of backend_code
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(backend_files)
        
        completed_tasks = state.get("completed_tasks", [])
        if "Backend Development" not in completed_tasks:
            completed_tasks.append("Backend Development")
        
        return {
            **state,
            "workspace": updated_workspace,
            "backend_code": backend_files,  # Keep for compatibility
            "completed_tasks": completed_tasks,
            "current_agent": "backend_dev",
            "qa_feedback": []  # CRITICAL: Clear QA feedback after applying patches
        }
    
    except Exception as e:
        logger.error("Backend dev failed", error=str(e))
        
        # Provide fallback minimal code
        fallback_code = {
            "main.py": """
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello World"}
""",
            "requirements.txt": "fastapi==0.109.0\\nuvicorn==0.27.0"
        }
        
        # Update workspace with fallback
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(fallback_code)
        
        return {
            **state,
            "workspace": updated_workspace,
            "backend_code": fallback_code,
            "completed_tasks": state.get("completed_tasks", []) + ["Backend Development (fallback)"],
            "current_agent": "backend_dev",
            "qa_feedback": []  # CRITICAL: Clear QA feedback
        }

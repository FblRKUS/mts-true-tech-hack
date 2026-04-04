from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def devops_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    DevOps Engineer Agent with Workspace Integration.
    
    CRITICAL: Writes deployment configs to shared workspace.
    Reads existing workspace to detect tech stack.
    
    Responsibilities:
    - Create Dockerfile and docker-compose.yml
    - Set up CI/CD configuration
    - Configure environment variables
    - Write deployment scripts
    """
    
    logger.info("DevOps engineer started")
    
    system_prompt = """You are an expert DevOps Engineer.

**CRITICAL INSTRUCTIONS:**
1. Your configs will be saved to a shared workspace
2. Analyze existing workspace files to detect tech stack
3. Generate production-ready deployment configurations

**Output Format:**
Respond ONLY with JSON mapping file paths to config content:
{
    "Dockerfile": "<full dockerfile here>",
    "docker-compose.yml": "<full compose file here>",
    ".env.example": "<full env template here>",
    "README.md": "<deployment instructions here>"
}
"""
    
    user_request = state.get("user_request", "")
    task_description = state.get("current_task_description", "Create deployment configs")
    workspace = state.get("workspace", {})
    
    # Detect tech stack from workspace
    has_python = any(f.endswith('.py') for f in workspace.keys())
    has_react = 'package.json' in workspace or any('jsx' in f for f in workspace.keys())
    has_requirements = 'requirements.txt' in workspace
    
    # Build workspace context
    workspace_files = list(workspace.keys())
    
    prompt = f"""
User Request: {user_request}

Workspace Files:
{', '.join(workspace_files[:20])}  # First 20 files

Detected Stack:
- Python Backend: {has_python}
- React Frontend: {has_react}
- Has requirements.txt: {has_requirements}

Task: {task_description}

Generate production-ready Docker and deployment configurations based on workspace contents.
"""
    
    try:
        # Use model from user request
        model = state.get("request_model", "openai/qwen3-235b-a22b-2507")
        
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model=model,
            temperature=0.4,
            max_tokens=2500,
            system_prompt=system_prompt
        )
        
        # Parse JSON response
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        devops_files = json.loads(response_text.strip())
        
        logger.info("DevOps configs generated", num_files=len(devops_files))
        
        # CRITICAL: Update workspace with deployment configs
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(devops_files)
        
        completed_tasks = state.get("completed_tasks", [])
        if "DevOps Configuration" not in completed_tasks:
            completed_tasks.append("DevOps Configuration")
        
        return {
            **state,
            "workspace": updated_workspace,
            "devops_configs": devops_files,  # Keep for compatibility
            "completed_tasks": completed_tasks,
            "current_agent": "devops",
            "qa_feedback": []  # CRITICAL: Clear QA feedback after applying patches
        }
    
    except Exception as e:
        logger.error("DevOps failed", error=str(e))
        
        # Provide fallback minimal config
        fallback_config = {
            "Dockerfile": "FROM python:3.11-slim\\nWORKDIR /app\\nCOPY . .\\nRUN pip install -r requirements.txt\\nCMD ['python', 'main.py']",
            "docker-compose.yml": "version: '3.8'\\nservices:\\n  app:\\n    build: .\\n    ports:\\n      - '8000:8000'",
            ".env.example": "API_KEY=your-key-here"
        }
        
        # Update workspace with fallback
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(fallback_config)
        
        return {
            **state,
            "workspace": updated_workspace,
            "devops_configs": fallback_config,
            "completed_tasks": state.get("completed_tasks", []) + ["DevOps Configuration (fallback)"],
            "current_agent": "devops",
            "qa_feedback": []  # CRITICAL: Clear QA feedback
        }

from typing import Dict, Any
from app.services.llm_router import llm_router
from app.agents.output_contract import parse_file_map
from app.core.config import settings
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
    
    logger.info("DevOps engineer started", trace_id=state.get("loop_trace_id"))
    
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
{', '.join(workspace_files[:20])}

Detected Stack:
- Python Backend: {has_python}
- React Frontend: {has_react}
- Has requirements.txt: {has_requirements}

Task: {task_description}

Generate production-ready Docker and deployment configurations based on workspace contents.
"""
    
    try:
        model = state.get("request_model", "autoselect")
        devops_files: dict[str, str] | None = None
        parse_errors: list[str] = []

        max_attempts = max(1, int(settings.max_qa_iterations))
        for attempt in range(1, max_attempts + 1):
            attempt_prompt = prompt
            if attempt > 1:
                attempt_prompt += (
                    "\n\nPrevious output failed strict JSON file-map validation. "
                    "Return ONLY a valid JSON object mapping file paths to full file contents."
                )
            response_text = await llm_router.generate_text(
                prompt=attempt_prompt,
                model=model,
                temperature=0.4,
                max_tokens=2500,
                system_prompt=system_prompt,
            )

            try:
                candidate = parse_file_map(response_text)
                if not any(path in candidate for path in ("Dockerfile", "docker-compose.yml", ".env.example")):
                    raise ValueError("No core DevOps files generated")
                devops_files = candidate
                break
            except (json.JSONDecodeError, ValueError) as exc:
                parse_errors.append(f"attempt={attempt}: {exc}")
                logger.warning(
                    "DevOps output validation failed",
                    attempt=attempt,
                    error=str(exc),
                    reason_code="output_contract_invalid",
                    trace_id=state.get("loop_trace_id"),
                )

        if devops_files is None:
            raise ValueError("; ".join(parse_errors) or "DevOps output validation failed")

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
            "qa_feedback": [],  # CRITICAL: Clear QA feedback after applying patches
            "agent_error": None,
        }
    
    except Exception as e:
        logger.error(
            "DevOps failed",
            error=str(e),
            reason_code="devops_agent_failed",
            trace_id=state.get("loop_trace_id"),
        )

        previous_error = state.get("agent_error")
        retries = 0
        if isinstance(previous_error, dict) and previous_error.get("agent") == "devops":
            retries = int(previous_error.get("retries", 0))

        return {
            **state,
            "devops_configs": state.get("devops_configs", {}),
            "current_agent": "devops",
            "agent_error": {
                "agent": "devops",
                "stage": "output_contract",
                "message": str(e),
                "retries": retries,
            },
        }

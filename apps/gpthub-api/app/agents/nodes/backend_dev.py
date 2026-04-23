from typing import Dict, Any
from app.services.llm_router import llm_router
from app.agents.output_contract import parse_file_map
from app.core.config import settings
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
    
    logger.info("Backend developer started", trace_id=state.get("loop_trace_id"))
    
    task_profile = str(state.get("task_profile", ""))
    is_script_game = task_profile == "script_game"

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
    if is_script_game:
        system_prompt = """You are an expert Python game developer.

**CRITICAL INSTRUCTIONS:**
1. Implement a REAL executable snake game (not API/server scaffolding).
2. Output ONLY JSON mapping file paths to full file contents.
3. Prefer a single runnable `main.py` plus `requirements.txt`.
4. If QA provided patches, apply them exactly.
5. Do not output explanations outside JSON.

**Output Format (example):**
{
    "main.py": "<full snake game code>",
    "requirements.txt": "pygame==..."
}
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
    if is_script_game:
        prompt = f"""
User Request: {user_request}

Task: {task_description}
{workspace_context}
{patches_context}

{'**This is a fix iteration. Apply the QA patches above.**' if qa_patches else '**This is the initial implementation.**'}

Build an executable Snake game in Python.
Requirements:
- `main.py` must run the game loop (movement, food spawn, collision, score, game over/restart).
- Use a real runtime library (pygame/turtle/curses) and include dependencies in `requirements.txt`.
- Do NOT generate FastAPI/Flask/server endpoints unless explicitly requested.
"""
    
    try:
        model = state.get("request_model", "autoselect")
        backend_files: dict[str, str] | None = None
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
                temperature=0.5,
                max_tokens=3000,
                system_prompt=system_prompt,
            )

            try:
                candidate = parse_file_map(response_text)
                if "requirements.txt" not in candidate:
                    raise ValueError("requirements.txt is missing")
                if not any(path.endswith(".py") for path in candidate):
                    raise ValueError("No Python source files generated")
                if is_script_game:
                    main_code = str(candidate.get("main.py", "")).lower()
                    if not main_code:
                        raise ValueError("main.py is required for script_game profile")
                    if not any(lib in main_code for lib in ("pygame", "turtle", "curses")):
                        raise ValueError("main.py must use pygame/turtle/curses for snake gameplay")
                    if not all(token in main_code for token in ("snake", "food")):
                        raise ValueError("main.py does not include snake/food gameplay markers")
                backend_files = candidate
                break
            except (json.JSONDecodeError, ValueError) as exc:
                parse_errors.append(f"attempt={attempt}: {exc}")
                logger.warning(
                    "Backend output validation failed",
                    attempt=attempt,
                    error=str(exc),
                    reason_code="output_contract_invalid",
                    trace_id=state.get("loop_trace_id"),
                )

        if backend_files is None:
            raise ValueError("; ".join(parse_errors) or "Backend output validation failed")

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
            "qa_feedback": [],  # CRITICAL: Clear QA feedback after applying patches
            "agent_error": None,
        }
    
    except Exception as e:
        logger.error(
            "Backend dev failed",
            error=str(e),
            reason_code="backend_agent_failed",
            trace_id=state.get("loop_trace_id"),
        )

        previous_error = state.get("agent_error")
        retries = 0
        if isinstance(previous_error, dict) and previous_error.get("agent") == "backend_dev":
            retries = int(previous_error.get("retries", 0))

        return {
            **state,
            "backend_code": state.get("backend_code", {}),
            "current_agent": "backend_dev",
            "agent_error": {
                "agent": "backend_dev",
                "stage": "output_contract",
                "message": str(e),
                "retries": retries,
            },
        }

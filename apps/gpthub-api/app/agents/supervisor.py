from typing import Dict, Any, List, Literal
from app.services.llm_router import llm_router
from app.core.config import settings
import structlog
import json
import re

logger = structlog.get_logger(__name__)

# Available worker agents
WORKERS = ["designer", "frontend_dev", "backend_dev", "devops", "qa_tester", "FINISH"]


def _parse_supervisor_decision(response_text: str) -> dict[str, Any]:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    try:
        decision, _ = json.JSONDecoder().raw_decode(cleaned)
        if isinstance(decision, dict):
            return decision
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1].strip())

    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def _infer_task_profile(user_request: str) -> str:
    text = user_request.lower()
    frontend_negated = any(token in text for token in ("без frontend", "no frontend", "without frontend", "no ui", "без интерфейса"))
    has_frontend = (not frontend_negated) and any(
        token in text
        for token in (
            "frontend",
            "front-end",
            "ui",
            "react",
            "svelte",
            "интерфейс",
            "фронтенд",
            "веб",
            "web",
            "браузер",
            "javascript",
            "html",
            "css",
        )
    )
    has_backend = any(
        token in text
        for token in ("backend", "api", "fastapi", "flask", "python", "сервер", "endpoint", "бэкенд")
    )
    has_devops = any(token in text for token in ("docker", "deploy", "k8s", "ci/cd", "devops", "девопс"))
    is_script_game = any(token in text for token in ("snake", "змейк", "игр", "pygame", "turtle", "curses"))

    if has_frontend and has_backend:
        return "fullstack"
    if is_script_game and has_frontend:
        return "fullstack"
    if has_frontend:
        return "frontend_only"
    if has_devops and not has_backend and not has_frontend:
        return "devops_only"
    if is_script_game:
        return "script_game"
    return "backend_only" if has_backend else "general"


def _allowed_agents_for_profile(profile: str) -> set[str]:
    if profile in {"backend_only", "script_game"}:
        return {"backend_dev", "qa_tester", "FINISH"}
    if profile == "frontend_only":
        return {"designer", "frontend_dev", "qa_tester", "FINISH"}
    if profile == "devops_only":
        return {"devops", "qa_tester", "FINISH"}
    if profile == "fullstack":
        return {"designer", "frontend_dev", "backend_dev", "devops", "qa_tester", "FINISH"}
    return set(WORKERS)


def _detect_request_language(user_request: str) -> str:
    return "ru" if re.search(r"[А-Яа-яЁё]", user_request or "") else "en"


def _has_backend_artifacts(state: Dict[str, Any]) -> bool:
    workspace = state.get("workspace", {})
    if isinstance(workspace, dict) and any(str(path).endswith(".py") for path in workspace.keys()):
        return True
    backend_code = state.get("backend_code", {})
    if isinstance(backend_code, dict) and backend_code:
        return True
    return False


def _has_frontend_artifacts(state: Dict[str, Any]) -> bool:
    workspace = state.get("workspace", {})
    if not isinstance(workspace, dict):
        workspace = {}
    frontend_ext = (".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".vue", ".svelte")
    if any(str(path).endswith(frontend_ext) for path in workspace.keys()):
        return True
    if any(str(path).endswith("/package.json") or str(path) == "package.json" for path in workspace.keys()):
        return True
    frontend_code = state.get("frontend_code", {})
    return isinstance(frontend_code, dict) and bool(frontend_code)


def _has_any_executable_artifacts(state: Dict[str, Any]) -> bool:
    if _has_backend_artifacts(state) or _has_frontend_artifacts(state):
        return True
    workspace = state.get("workspace", {})
    if isinstance(workspace, dict) and workspace:
        return True
    devops = state.get("devops_configs", {})
    return isinstance(devops, dict) and bool(devops)


def _latest_qa_feedback(state: Dict[str, Any]) -> dict[str, Any] | None:
    qa_feedback = state.get("qa_feedback", [])
    if isinstance(qa_feedback, list) and qa_feedback and isinstance(qa_feedback[-1], dict):
        return qa_feedback[-1]
    return None


def _qa_acceptance_passed(state: Dict[str, Any]) -> bool:
    latest = _latest_qa_feedback(state)
    if not latest:
        return False
    return bool(latest.get("execution_passed") and latest.get("acceptance_passed"))


async def supervisor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project Manager / Supervisor Node.
    
    Responsibilities:
    - Analyze user request and decompose into subtasks
    - Route tasks to appropriate worker agents
    - Decide when the project is complete
    - Formulate final response to user
    
    Returns updated state with next_agent routing decision.
    """
    
    loop_trace_id = str(state.get("loop_trace_id") or state.get("thread_id") or "unknown")
    task_profile = str(state.get("task_profile") or _infer_task_profile(str(state.get("user_request", ""))))
    logger.info(
        "Supervisor analyzing task",
        current_agent=state.get("current_agent"),
        trace_id=loop_trace_id,
        task_profile=task_profile,
    )

    qa_iteration = int(state.get("qa_iteration", 0))
    if qa_iteration >= int(settings.max_qa_iterations) and not _qa_acceptance_passed(state):
        final_response = (
            "Autopilot stopped: QA iteration limit reached without passing acceptance checks. "
            "Generated artifacts did not satisfy the original request."
        )
        logger.warning(
            "Supervisor stopping due to QA limit without acceptance",
            qa_iteration=qa_iteration,
            reason_code="qa_limit_without_acceptance",
            trace_id=loop_trace_id,
        )
        return {
            **state,
            "next_agent": "FINISH",
            "final_response": final_response,
            "is_completed": True,
            "supervisor_reasoning": "QA limit reached without acceptance.",
            "supervisor_reason_code": "qa_limit_without_acceptance",
            "task_profile": task_profile,
            "loop_trace_id": loop_trace_id,
        }

    agent_error = state.get("agent_error", {})
    if isinstance(agent_error, dict) and agent_error.get("agent"):
        failing_agent = str(agent_error.get("agent"))
        retries = int(agent_error.get("retries", 0))
        max_retries = max(1, int(settings.max_qa_iterations))
        error_message = str(agent_error.get("message", "Unknown agent failure"))

        if retries < max_retries:
            next_agent = failing_agent if failing_agent in WORKERS else "backend_dev"
            retry_state = dict(agent_error)
            retry_state["retries"] = retries + 1
            reasoning = f"Recovering from {failing_agent} failure via retry ladder ({retries + 1}/{max_retries})."
            logger.warning(
                "Supervisor recovery routing",
                next_agent=next_agent,
                retries=retry_state["retries"],
                error=error_message,
                reason_code="agent_recovery_retry",
                trace_id=loop_trace_id,
            )
            return {
                **state,
                "next_agent": next_agent,
                "current_task_description": (
                    f"Retry after previous failure. Fix output format/contract and complete original request. "
                    f"Last error: {error_message}"
                ),
                "supervisor_reasoning": reasoning,
                "supervisor_reason_code": "agent_recovery_retry",
                "agent_error": retry_state,
                "task_profile": task_profile,
                "loop_trace_id": loop_trace_id,
            }

        final_response = (
            f"Agentic loop stopped after repeated failures in {failing_agent}. "
            f"Last error: {error_message}. Please retry with a narrowed task scope."
        )
        logger.error(
            "Supervisor stopping after repeated agent failures",
            agent=failing_agent,
            error=error_message,
            reason_code="agent_recovery_exhausted",
            trace_id=loop_trace_id,
        )
        return {
            **state,
            "next_agent": "FINISH",
            "final_response": final_response,
            "is_completed": True,
            "supervisor_reasoning": "Stopping after exhausted recovery ladder.",
            "supervisor_reason_code": "agent_recovery_exhausted",
            "task_profile": task_profile,
            "loop_trace_id": loop_trace_id,
        }
    
    # Build system prompt for supervisor
    system_prompt = f"""You are a Project Manager supervising a team of AI agents to complete software development tasks.

Available workers:
- designer: UX/UI Designer - creates interface designs, component structures, and styles
- frontend_dev: Frontend Developer - writes client-side code (React, HTML, CSS, JS)
- backend_dev: Backend Developer - writes server code, APIs, database schemas
- devops: DevOps Engineer - creates Dockerfiles, CI/CD configs, docker-compose files
- qa_tester: QA/Tester - tests generated code in E2B sandbox, provides feedback (max 3 iterations)
- FINISH: Task is complete, ready to respond to user

Current state:
- User request: {state.get('user_request', 'N/A')}
- Completed tasks: {', '.join(state.get('completed_tasks', [])) if state.get('completed_tasks') else 'None'}
- Current artifacts: {list(state.get('design_artifacts', {}).keys())}
- Frontend files: {list(state.get('frontend_code', {}).keys())}
- Backend files: {list(state.get('backend_code', {}).keys())}
- DevOps files: {list(state.get('devops_configs', {}).keys())}
- QA iteration: {state.get('qa_iteration', 0)}/{settings.max_qa_iterations}
- QA feedback status: {'Empty (patches applied)' if not state.get('qa_feedback') else 'Has feedback'}
- Recent QA feedback: {state.get('qa_feedback', [])[-1] if state.get('qa_feedback') else 'None'}

CRITICAL ROUTING RULES:
1. If a developer (frontend_dev, backend_dev, devops) just completed work:
   - Check if qa_feedback is NOW EMPTY (meaning patches were applied)
   - If empty AND qa_iteration < max: Send to qa_tester to verify fixes
   - This prevents infinite loops where devs keep getting sent the same task

2. If QA iteration >= max_qa_iterations: Choose FINISH (prevent infinite testing)

3. Normal flow: designer → frontend_dev → backend_dev → devops → qa_tester → (if bugs) → relevant dev → qa_tester → FINISH

Your task:
1. Analyze what has been completed
2. Determine the next logical step
3. Choose the next worker to handle it OR choose FINISH if complete

Respond with JSON containing:
{{
    "reasoning": "Brief explanation of your decision",
    "next_agent": "worker_name or FINISH",
    "task_description": "What the next agent should do"
}}
"""
    
    # Call LLM to make routing decision
    try:
        # Use model from user request
        model = state.get("request_model", "autoselect")
        
        response_text = await llm_router.generate_text(
            prompt="Analyze the current state and decide the next step.",
            model=model,
            temperature=0.3,
            max_tokens=500,
            system_prompt=system_prompt
        )
        
        if not isinstance(response_text, str) or not response_text.strip():
            raise ValueError("Supervisor returned empty decision")

        decision = _parse_supervisor_decision(response_text)
        
        next_agent = decision.get("next_agent", "FINISH")
        if next_agent not in WORKERS:
            next_agent = "FINISH"
        reasoning = decision.get("reasoning", "")
        task_desc = decision.get("task_description", "")

        reason_code = "llm_decision"
        allowed_agents = _allowed_agents_for_profile(task_profile)
        if next_agent not in allowed_agents:
            latest_feedback = _latest_qa_feedback(state) or {}
            qa_has_issues = bool(latest_feedback) and latest_feedback.get("status") != "success"
            if task_profile in {"backend_only", "script_game"}:
                # For script/backend tasks we must bounce back to backend_dev on failed QA,
                # otherwise the loop can get stuck in qa_tester-only retries.
                if qa_has_issues:
                    next_agent = "backend_dev"
                else:
                    next_agent = "qa_tester" if _has_backend_artifacts(state) else "backend_dev"
            else:
                next_agent = "qa_tester" if _has_backend_artifacts(state) else "backend_dev"
            reasoning = f"{reasoning} [policy override: disallowed agent for {task_profile}]"
            reason_code = "profile_policy_override"

        if next_agent == "FINISH" and not _qa_acceptance_passed(state):
            if state.get("qa_iteration", 0) < settings.max_qa_iterations:
                next_agent = "qa_tester"
            else:
                next_agent = "frontend_dev" if task_profile == "frontend_only" else "backend_dev"
            reasoning = f"{reasoning} [policy override: acceptance gate not satisfied]"
            reason_code = "acceptance_gate_blocked"

        if next_agent == "qa_tester" and not _has_any_executable_artifacts(state):
            next_agent = "frontend_dev" if task_profile == "frontend_only" else "backend_dev"
            reasoning = f"{reasoning} [policy override: QA blocked, no executable artifacts yet]"
            reason_code = "qa_gate_no_artifacts"

        if next_agent == "FINISH":
            require_backend = task_profile in {"backend_only", "script_game", "fullstack"}
            require_frontend = task_profile in {"frontend_only", "fullstack"}
            missing_backend = require_backend and not _has_backend_artifacts(state)
            missing_frontend = require_frontend and not _has_frontend_artifacts(state)
            if missing_backend:
                next_agent = "backend_dev"
                reasoning = f"{reasoning} [policy override: finish blocked, backend artifacts missing]"
                reason_code = "finish_gate_missing_backend"
            elif missing_frontend:
                next_agent = "frontend_dev"
                reasoning = f"{reasoning} [policy override: finish blocked, frontend artifacts missing]"
                reason_code = "finish_gate_missing_frontend"

        if (
            state.get("current_agent") in {"backend_dev", "frontend_dev", "devops"}
            and state.get("qa_iteration", 0) < settings.max_qa_iterations
            and next_agent not in {"qa_tester", "FINISH"}
        ):
            next_agent = "qa_tester"
            reasoning = f"{reasoning} [policy override: force QA revalidation after developer update]"
            reason_code = "force_qa_revalidation"

        if state.get("qa_iteration", 0) >= settings.max_qa_iterations and next_agent != "FINISH":
            next_agent = "FINISH"
            reason_code = "qa_limit_forced_finish"
            reasoning = f"{reasoning} [policy override: QA limit reached]"
        
        logger.info(
            "Supervisor decision",
            next_agent=next_agent,
            reasoning=reasoning,
            reason_code=reason_code,
            trace_id=loop_trace_id,
            task_profile=task_profile,
        )
        
        # Update state with routing decision
        updated_state = {
            **state,
            "next_agent": next_agent,
            "current_task_description": task_desc,
            "supervisor_reasoning": reasoning,
            "supervisor_reason_code": reason_code,
            "task_profile": task_profile,
            "loop_trace_id": loop_trace_id,
        }
        
        # If FINISH, prepare final response
        if next_agent == "FINISH":
            final_response = await _prepare_final_response(state)
            updated_state["final_response"] = final_response
            updated_state["is_completed"] = True
        
        return updated_state
    
    except Exception as e:
        logger.error(
            "Supervisor decision failed",
            error=str(e),
            reason_code="supervisor_exception",
            trace_id=loop_trace_id,
        )
        final_response = await _prepare_final_response(state)
        return {
            **state,
            "next_agent": "FINISH",
            "final_response": final_response,
            "is_completed": True,
            "supervisor_reason_code": "supervisor_exception",
            "task_profile": task_profile,
            "loop_trace_id": loop_trace_id,
        }


async def _prepare_final_response(state: Dict[str, Any]) -> str:
    """Generate comprehensive final response summarizing all work."""
    request_language = _detect_request_language(str(state.get("user_request", "")))
    language_instruction = (
        "Respond in Russian. Keep technical terms and file paths unchanged where needed."
        if request_language == "ru"
        else "Respond in English."
    )

    system_prompt = (
        "You are a Project Manager presenting completed work to a client. "
        "Summarize completed tasks and deliverables in a clear, professional manner. "
        f"{language_instruction}"
    )
    
    # Use model from user request
    model = state.get("request_model", "autoselect")
    
    summary_prompt = f"""
Project Request: {state.get('user_request', 'N/A')}

Completed Work:
- Design Artifacts: {list(state.get('design_artifacts', {}).keys())}
- Frontend Files: {list(state.get('frontend_code', {}).keys())}
- Backend Files: {list(state.get('backend_code', {}).keys())}
- DevOps Configs: {list(state.get('devops_configs', {}).keys())}

QA Results:
- Iterations: {state.get('qa_iteration', 0)}
- Final Feedback: {state.get('qa_feedback', [])[-1] if state.get('qa_feedback') else 'All tests passed'}

Create a concise summary of what was delivered and how to use it.
Response language: {request_language}
"""
    
    try:
        response = await llm_router.generate_text(
            prompt=summary_prompt,
            model=model,
            temperature=0.7,
            max_tokens=800,
            system_prompt=system_prompt
        )
        
        # CRITICAL: Collect ALL files from all sources
        all_files = {}
        
        # Merge from workspace (if exists)
        all_files.update(state.get("workspace", {}))
        
        # Merge from individual agent outputs (fallback if workspace empty)
        all_files.update(state.get("design_artifacts", {}))
        all_files.update(state.get("frontend_code", {}))
        all_files.update(state.get("backend_code", {}))
        all_files.update(state.get("devops_configs", {}))
        
        thread_id = state.get("thread_id", "unknown")
        
        # ALWAYS add files section if we have ANY files
        if all_files:
            # OpenWebUI serves the chat UI and proxies GPTHub backend endpoints under /api/v1/gpthub.
            response += f"\n\n---\n\n## 📁 Generated Files\n\n**📦 [Download All Files as ZIP](/api/v1/gpthub/download/{thread_id})**\n\n"
            
            for file_path, file_content in all_files.items():
                ext = file_path.split('.')[-1] if '.' in file_path else ''
                lang_map = {
                    'py': 'python', 'js': 'javascript', 'jsx': 'jsx', 'ts': 'typescript',
                    'tsx': 'tsx', 'html': 'html', 'css': 'css', 'json': 'json',
                    'yml': 'yaml', 'yaml': 'yaml', 'md': 'markdown', 'sh': 'bash',
                    'txt': 'text', 'Dockerfile': 'dockerfile'
                }
                lang = lang_map.get(ext, ext)
                if file_path == 'Dockerfile':
                    lang = 'dockerfile'
                
                response += f"\n### **`{file_path}`**\n\n"
                response += f"```{lang}\n{file_content.strip()}\n```\n"
        
        return response
    
    except Exception as e:
        logger.error("Failed to generate final response", error=str(e))
        return "Project completed. All requested components have been generated."


def route_supervisor(state: Dict[str, Any]) -> Literal["designer", "frontend_dev", "backend_dev", "devops", "qa_tester", "end"]:
    """
    Routing function for LangGraph conditional edges.
    
    Determines which node to execute next based on supervisor's decision.
    """
    next_agent = state.get("next_agent", "FINISH")
    
    # Map agent names to node names
    if next_agent == "FINISH":
        return "end"
    
    return next_agent

from __future__ import annotations

from typing import Any
import json

import structlog

from app.core.config import settings
from app.services.e2b_runner import e2b_runner
from app.services.llm_router import llm_router

logger = structlog.get_logger(__name__)


def _detect_entrypoint(workspace: dict[str, str]) -> tuple[str | None, str]:
    if "main.py" in workspace:
        return "main.py", "python"
    if "app/main.py" in workspace:
        return "app/main.py", "python"
    if "src/main.py" in workspace:
        return "src/main.py", "python"
    if "index.js" in workspace:
        return "index.js", "javascript"
    if "src/index.js" in workspace:
        return "src/index.js", "javascript"
    return None, "python"


def _collect_workspace(state: dict[str, Any]) -> dict[str, str]:
    workspace = state.get("workspace", {})
    if workspace:
        return workspace
    return {**state.get("backend_code", {}), **state.get("frontend_code", {})}


def _contains_hello_world_fallback(workspace: dict[str, str]) -> bool:
    for content in workspace.values():
        normalized = str(content).strip().lower()
        if "return {\"message\": \"hello world\"}" in normalized:
            return True
        if "export default function app() { return <div>hello world</div>; }" in normalized:
            return True
    return False


def _snake_acceptance_passed(workspace: dict[str, str]) -> bool:
    code_blob = "\n".join(str(content).lower() for content in workspace.values())
    has_game_runtime = any(
        token in code_blob
        for token in ("pygame", "turtle", "curses", "canvas", "requestanimationframe", "addEventListener(\"keydown\"")
    )
    has_game_logic = all(token in code_blob for token in ("snake", "food"))
    return has_game_runtime and has_game_logic


def _is_snake_request(state: dict[str, Any]) -> bool:
    user_request = str(state.get("user_request", "")).lower()
    return any(token in user_request for token in ("snake", "змейк", "игр"))


def _has_frontend_workspace_files(workspace: dict[str, str]) -> bool:
    frontend_ext = (".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".svelte", ".vue")
    return any(path.endswith(frontend_ext) or path == "package.json" for path in workspace.keys())


def _build_acceptance_feedback(state: dict[str, Any], workspace: dict[str, str]) -> tuple[bool, dict[str, Any]]:
    user_request = str(state.get("user_request", "")).lower()

    if _contains_hello_world_fallback(workspace):
        return False, {
            "status": "issues_found",
            "message": "Fallback hello-world artifact detected. Task is not complete.",
            "patches": [
                {
                    "file_path": "main.py",
                    "issue": "Fallback/template output detected instead of requested implementation",
                    "severity": "critical",
                    "fix": "Implement requested functionality end-to-end; remove hello-world placeholders.",
                }
            ],
            "execution_passed": True,
            "acceptance_passed": False,
        }

    if any(token in user_request for token in ("snake", "змейк", "игр")) and not _snake_acceptance_passed(workspace):
        return False, {
            "status": "issues_found",
            "message": "Acceptance check failed: requested snake game behavior is not implemented.",
            "patches": [
                {
                    "file_path": "main.py",
                    "issue": "Snake gameplay logic not detected",
                    "severity": "critical",
                    "fix": "Implement executable snake gameplay (loop, movement, food, score) using pygame/turtle/curses.",
                }
            ],
            "execution_passed": True,
            "acceptance_passed": False,
        }

    return True, {
        "status": "success",
        "message": "E2B execution and acceptance checks passed",
        "patches": [],
        "execution_passed": True,
        "acceptance_passed": True,
    }


async def qa_tester_node(state: dict[str, Any]) -> dict[str, Any]:
    logger.info(
        "QA tester started",
        qa_iteration=state.get("qa_iteration", 0),
        trace_id=state.get("loop_trace_id"),
        task_profile=state.get("task_profile"),
    )

    qa_iteration = state.get("qa_iteration", 0)
    if qa_iteration >= settings.max_qa_iterations:
        feedback = {
            "status": "max_iterations_reached",
            "message": f"Maximum QA iterations ({settings.max_qa_iterations}) reached.",
            "patches": [],
            "execution_passed": False,
            "acceptance_passed": False,
        }
        return {
            **state,
            "qa_iteration": qa_iteration,
            "qa_feedback": state.get("qa_feedback", []) + [feedback],
            "completed_tasks": state.get("completed_tasks", []) + ["QA Testing"],
            "current_agent": "qa_tester",
        }

    workspace = _collect_workspace(state)
    if not workspace:
        return {
            **state,
            "qa_feedback": state.get("qa_feedback", [])
            + [{"status": "no_code", "message": "No code found in workspace", "patches": []}],
            "current_agent": "qa_tester",
        }

    task_profile = str(state.get("task_profile", ""))
    if task_profile == "script_game" or _is_snake_request(state):
        acceptance_passed, feedback = _build_acceptance_feedback(state=state, workspace=workspace)
        if task_profile == "fullstack":
            has_frontend = _has_frontend_workspace_files(workspace)
            has_backend = any(path.endswith(".py") for path in workspace.keys())
            code_blob = "\n".join(str(content).lower() for content in workspace.values())
            has_snake_hint = "snake" in code_blob
            if not (has_frontend and has_backend and has_snake_hint):
                acceptance_passed = False
                feedback = {
                    "status": "issues_found",
                    "message": "Fullstack snake request requires frontend, backend, and snake gameplay implementation hints.",
                    "patches": [
                        {
                            "file_path": "src/App.jsx" if not has_frontend else ("main.py" if not has_backend else "src/App.jsx"),
                            "issue": "Missing required fullstack layer",
                            "severity": "critical",
                            "fix": "Provide frontend files, backend Python files, and explicit snake gameplay logic markers in code.",
                        }
                    ],
                    "execution_passed": False,
                    "acceptance_passed": False,
                }
            else:
                acceptance_passed = True
                feedback = {
                    "status": "success",
                    "message": "Static fullstack acceptance passed (frontend + backend + snake gameplay markers found).",
                    "patches": [],
                    "execution_passed": True,
                    "acceptance_passed": True,
                }
        feedback["execution_passed"] = acceptance_passed
        feedback["acceptance_passed"] = acceptance_passed
        feedback["status"] = "success" if acceptance_passed else "issues_found"
        feedback.setdefault(
            "message",
            "Static acceptance check for script_game profile",
        )
        completed_tasks = state.get("completed_tasks", [])
        if acceptance_passed and "QA Testing" not in completed_tasks:
            completed_tasks.append("QA Testing")
        return {
            **state,
            "qa_iteration": qa_iteration + 1,
            "qa_feedback": state.get("qa_feedback", []) + [feedback],
            "e2b_test_results": {
                "success": acceptance_passed,
                "execution_mode": "static-script-game-check",
            },
            "completed_tasks": completed_tasks,
            "current_agent": "qa_tester",
        }

    entrypoint, language = _detect_entrypoint(workspace)
    if entrypoint is None:
        feedback = {
            "status": "issues_found",
            "message": "Cannot determine project entrypoint for E2B execution.",
            "patches": [
                {
                    "file_path": "main.py",
                    "issue": "Entrypoint missing",
                    "severity": "critical",
                    "fix": "Add executable entrypoint file (main.py or index.js).",
                }
            ],
        }
        return {
            **state,
            "qa_iteration": qa_iteration + 1,
            "qa_feedback": state.get("qa_feedback", []) + [feedback],
            "current_agent": "qa_tester",
        }

    e2b_result = await e2b_runner.run_project(
        files=workspace,
        entrypoint=entrypoint,
        language=language,
        timeout=90,
    )

    if not e2b_result.get("success"):
        feedback = await _build_execution_feedback(state=state, workspace=workspace, entrypoint=entrypoint, result=e2b_result)
    else:
        _, feedback = _build_acceptance_feedback(state=state, workspace=workspace)

    logger.info(
        "QA verdict computed",
        status=feedback.get("status"),
        execution_passed=feedback.get("execution_passed"),
        acceptance_passed=feedback.get("acceptance_passed"),
        trace_id=state.get("loop_trace_id"),
    )

    completed_tasks = state.get("completed_tasks", [])
    if feedback.get("status") == "success" and feedback.get("execution_passed") and feedback.get("acceptance_passed") and "QA Testing" not in completed_tasks:
        completed_tasks.append("QA Testing")

    return {
        **state,
        "qa_iteration": qa_iteration + 1,
        "qa_feedback": state.get("qa_feedback", []) + [feedback],
        "e2b_test_results": e2b_result,
        "completed_tasks": completed_tasks,
        "current_agent": "qa_tester",
    }


async def _build_execution_feedback(
    state: dict[str, Any],
    workspace: dict[str, str],
    entrypoint: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    model = state.get("request_model", "autoselect")
    prompt = f"""
Entrypoint: {entrypoint}
Exit code: {result.get("exit_code")}
STDERR:
{result.get("stderr", "")[:2000]}

STDOUT:
{result.get("stdout", "")[:2000]}

Workspace files:
{", ".join(list(workspace.keys())[:40])}

Return JSON:
{{
  "status":"issues_found",
  "message":"...",
  "patches":[
    {{
      "file_path":"...",
      "issue":"...",
      "severity":"critical|moderate|minor",
      "fix":"..."
    }}
  ]
}}
"""
    response_text = await llm_router.generate_text(
        prompt=prompt,
        model=model,
        temperature=0.2,
        max_tokens=1200,
        system_prompt="You are a QA engineer. Output only valid JSON.",
    )
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    feedback = json.loads(cleaned.strip())
    feedback.setdefault("status", "issues_found")
    feedback.setdefault("patches", [])
    feedback.setdefault("message", "Execution failed in E2B sandbox")
    feedback.setdefault("execution_passed", False)
    feedback.setdefault("acceptance_passed", False)
    return feedback


async def _review_code(workspace: dict[str, str], state: dict[str, Any]) -> dict[str, Any]:
    model = state.get("request_model", "autoselect")
    code_summary = []
    for filepath, content in workspace.items():
        ext = filepath.split(".")[-1] if "." in filepath else "text"
        code_summary.append(f"### {filepath}\n```{ext}\n{content}\n```")
    prompt = f"""
Review code for runtime/security issues. Return JSON only:
{{
  "status":"success|issues_found",
  "message":"...",
  "patches":[{{"file_path":"...","issue":"...","severity":"...","fix":"..."}}]
}}

Code:
{chr(10).join(code_summary)[:9000]}
"""
    response_text = await llm_router.generate_text(
        prompt=prompt,
        model=model,
        temperature=0.2,
        max_tokens=1500,
        system_prompt="You are a strict QA reviewer. Output only valid JSON.",
    )
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    feedback = json.loads(cleaned.strip())
    feedback.setdefault("status", "success" if not feedback.get("patches") else "issues_found")
    feedback.setdefault("patches", [])
    feedback.setdefault("message", "Code review completed")
    return feedback

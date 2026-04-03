from typing import Dict, Any
from app.services.e2b_runner import e2b_runner
from app.services.llm_router import llm_router
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


async def qa_tester_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    QA/Tester Agent with E2B Sandbox Integration and Patch-based Feedback.
    
    CRITICAL: No longer just returns error logs. Analyzes failures and generates
    specific code patches for developers to apply.
    
    Responsibilities:
    - Execute generated code from workspace in E2B sandbox
    - Analyze stdout/stderr output
    - Generate specific patches (file, line, fix) when code fails
    - Provide actionable feedback to developers
    - Enforce max iteration limit (3 by default)
    """
    
    logger.info("QA tester started", qa_iteration=state.get("qa_iteration", 0))
    
    qa_iteration = state.get("qa_iteration", 0)
    max_iterations = settings.max_qa_iterations
    
    # Check if we've exceeded max iterations
    if qa_iteration >= max_iterations:
        logger.warning("Max QA iterations reached", iterations=qa_iteration)
        
        feedback = {
            "status": "max_iterations_reached",
            "message": f"Maximum QA iterations ({max_iterations}) reached. Proceeding with current implementation.",
            "patches": []
        }
        
        completed_tasks = state.get("completed_tasks", [])
        if "QA Testing" not in completed_tasks:
            completed_tasks.append("QA Testing")
        
        return {
            **state,
            "qa_iteration": qa_iteration,
            "qa_feedback": state.get("qa_feedback", []) + [feedback],
            "completed_tasks": completed_tasks,
            "current_agent": "qa_tester"
        }
    
    # Get code from workspace (new approach) or legacy fields
    workspace = state.get("workspace", {})
    
    # Fallback to legacy fields if workspace is empty
    if not workspace:
        backend_code = state.get("backend_code", {})
        frontend_code = state.get("frontend_code", {})
        workspace = {**backend_code, **frontend_code}
    
    if not workspace:
        logger.warning("No code to test in workspace")
        return {
            **state,
            "qa_feedback": state.get("qa_feedback", []) + [{
                "status": "no_code",
                "message": "No code found in workspace to test",
                "patches": []
            }],
            "current_agent": "qa_tester"
        }
    
    # Run tests in E2B with full workspace
    test_result = await _test_workspace(workspace)
    
    # Generate patch-based feedback if tests failed
    if not test_result.get("success", False):
        feedback = await _generate_patch_feedback(test_result, workspace, state)
    else:
        feedback = {
            "status": "success",
            "message": "All tests passed successfully! Code is ready.",
            "patches": []
        }
    
    # Increment QA iteration
    new_qa_iteration = qa_iteration + 1
    
    # Determine if tests passed
    all_passed = test_result.get("success", False)
    
    completed_tasks = state.get("completed_tasks", [])
    if all_passed and "QA Testing" not in completed_tasks:
        completed_tasks.append("QA Testing")
    
    logger.info(
        "QA testing completed",
        iteration=new_qa_iteration,
        all_passed=all_passed,
        has_patches=len(feedback.get("patches", [])) > 0
    )
    
    return {
        **state,
        "qa_iteration": new_qa_iteration,
        "qa_feedback": state.get("qa_feedback", []) + [feedback],
        "e2b_test_results": test_result,
        "completed_tasks": completed_tasks,
        "current_agent": "qa_tester"
    }


async def _test_workspace(workspace: Dict[str, str]) -> Dict[str, Any]:
    """
    Test entire workspace in E2B sandbox.
    
    CRITICAL: Uses workspace instead of separate code dicts.
    Automatically installs dependencies from requirements.txt/package.json.
    """
    
    logger.info("Testing workspace", num_files=len(workspace))
    
    # Detect language and entrypoint
    language = "python"
    entrypoint = None
    
    # Check for Python project
    if "main.py" in workspace:
        entrypoint = "main.py"
        language = "python"
    elif "app.py" in workspace:
        entrypoint = "app.py"
        language = "python"
    elif any(f.endswith(".py") for f in workspace.keys()):
        py_files = [f for f in workspace.keys() if f.endswith(".py")]
        entrypoint = py_files[0]
        language = "python"
    
    # Check for Node.js project
    elif "index.js" in workspace:
        entrypoint = "index.js"
        language = "javascript"
    elif "server.js" in workspace:
        entrypoint = "server.js"
        language = "javascript"
    
    if not entrypoint:
        return {
            "success": False,
            "error": "No entrypoint found in workspace",
            "stdout": "",
            "stderr": "Could not detect main.py, app.py, index.js, or server.js",
            "exit_code": -1
        }
    
    try:
        # Run project in E2B (dependencies will be auto-installed)
        result = await e2b_runner.run_project(
            files=workspace,
            entrypoint=entrypoint,
            language=language,
            timeout=60
        )
        
        logger.info(
            "E2B execution result",
            success=result.get("success"),
            exit_code=result.get("exit_code"),
            stderr_length=len(result.get("stderr", ""))
        )
        
        return result
    
    except Exception as e:
        logger.error("Workspace test failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1
        }


async def _generate_patch_feedback(
    test_result: Dict[str, Any],
    workspace: Dict[str, str],
    state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate patch-based feedback from test failures.
    
    CRITICAL: QA agent MUST analyze stderr and provide specific patches.
    NO LONGER just returns error logs - provides actionable fixes.
    """
    
    stderr = test_result.get("stderr", "")
    stdout = test_result.get("stdout", "")
    error = test_result.get("error", "")
    
    # Build strict system prompt
    system_prompt = """You are a Senior QA Engineer with code analysis expertise.

**CRITICAL RULES:**
1. NEVER just repeat error messages back to developers
2. ALWAYS analyze the stderr/error and identify the root cause
3. ALWAYS provide specific patches: which file, which line, what to change
4. If it's a ModuleNotFoundError, specify which dependency to add to requirements.txt
5. If it's a syntax error, specify the exact line and corrected code
6. Be precise and actionable

**FORBIDDEN:**
- "Check the error logs above" - NO, YOU analyze them
- "There is an error in the code" - NO, specify WHERE and WHAT
- Returning raw stack traces - NO, provide fixes

Output JSON with this structure:
{
  "analysis": "Brief root cause analysis",
  "patches": [
    {
      "file_path": "path/to/file.py",
      "issue": "What's wrong",
      "fix": "Specific code change or dependency to add",
      "line_number": 10 (optional)
    }
  ]
}"""
    
    # Build context about workspace
    workspace_summary = "\n".join([
        f"- {filepath} ({len(content)} chars)"
        for filepath, content in workspace.items()
    ])
    
    prompt = f"""Test execution FAILED. Analyze and provide specific patches.

**Workspace Files:**
{workspace_summary}

**Error Output (stderr):**
{stderr[:1000]}

**Standard Output (stdout):**
{stdout[:500]}

**Exit Code:** {test_result.get('exit_code', -1)}

**QA Iteration:** {state.get('qa_iteration', 0) + 1}/{settings.max_qa_iterations}

Analyze the error and provide SPECIFIC patches for developers to apply.
Do NOT just repeat the error - provide the solution.
"""
    
    try:
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model="gpt-4",
            temperature=0.2,  # Low temperature for precise analysis
            max_tokens=1500,
            system_prompt=system_prompt
        )
        
        # Parse JSON response
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        import json
        feedback = json.loads(response_text.strip())
        
        # Add status
        feedback["status"] = "failed"
        feedback["message"] = feedback.get("analysis", "Tests failed - see patches")
        
        logger.info(
            "Generated patch-based feedback",
            num_patches=len(feedback.get("patches", []))
        )
        
        return feedback
    
    except Exception as e:
        logger.error("Failed to generate patch feedback", error=str(e))
        
        # Fallback: at least try to extract useful info from stderr
        fallback_patches = []
        
        # Check for common errors
        if "ModuleNotFoundError" in stderr or "No module named" in stderr:
            # Extract module name
            import re
            match = re.search(r"No module named '([^']+)'", stderr)
            if match:
                module = match.group(1)
                fallback_patches.append({
                    "file_path": "requirements.txt",
                    "issue": f"Missing dependency: {module}",
                    "fix": f"Add '{module}' to requirements.txt",
                    "line_number": None
                })
        
        return {
            "status": "failed",
            "message": f"Tests failed. Error: {stderr[:200]}",
            "analysis": "Could not generate detailed analysis",
            "patches": fallback_patches
        }


# Legacy function removed - replaced with _generate_patch_feedback

from typing import Dict, Any, List, Literal
from app.services.llm_router import llm_router
from app.core.config import settings
import structlog
import json

logger = structlog.get_logger(__name__)

# Available worker agents
WORKERS = ["designer", "frontend_dev", "backend_dev", "devops", "qa_tester", "FINISH"]


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
    
    logger.info("Supervisor analyzing task", current_agent=state.get("current_agent"))
    
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
- Recent QA feedback: {state.get('qa_feedback', [])[-1] if state.get('qa_feedback') else 'None'}

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
        response_text = await llm_router.generate_text(
            prompt="Analyze the current state and decide the next step.",
            model="gpt-4",
            temperature=0.3,
            max_tokens=500,
            system_prompt=system_prompt
        )
        
        # Parse JSON response
        # Clean markdown code blocks if present
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        decision = json.loads(response_text.strip())
        
        next_agent = decision.get("next_agent", "FINISH")
        reasoning = decision.get("reasoning", "")
        task_desc = decision.get("task_description", "")
        
        logger.info(
            "Supervisor decision",
            next_agent=next_agent,
            reasoning=reasoning
        )
        
        # Update state with routing decision
        updated_state = {
            **state,
            "next_agent": next_agent,
            "current_task_description": task_desc,
            "supervisor_reasoning": reasoning
        }
        
        # If FINISH, prepare final response
        if next_agent == "FINISH":
            final_response = await _prepare_final_response(state)
            updated_state["final_response"] = final_response
            updated_state["is_completed"] = True
        
        return updated_state
    
    except Exception as e:
        logger.error("Supervisor decision failed", error=str(e))
        # Default to FINISH on error
        return {
            **state,
            "next_agent": "FINISH",
            "final_response": "I encountered an issue coordinating the team. Please try again.",
            "is_completed": True
        }


async def _prepare_final_response(state: Dict[str, Any]) -> str:
    """Generate comprehensive final response summarizing all work."""
    
    system_prompt = """You are a Project Manager presenting completed work to a client.
Summarize the completed tasks and deliverables in a clear, professional manner."""
    
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
"""
    
    try:
        response = await llm_router.generate_text(
            prompt=summary_prompt,
            model="gpt-4",
            temperature=0.7,
            max_tokens=800,
            system_prompt=system_prompt
        )
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

from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def designer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    UX/UI Designer Agent.
    
    Responsibilities:
    - Design user interface layouts
    - Define component structure
    - Specify styling guidelines
    - Create design specifications for frontend dev
    """
    
    logger.info("Designer agent started", user_request=state.get("user_request"))
    
    system_prompt = """You are an expert UX/UI Designer.

Your task is to design the user interface for the requested application.

Provide:
1. Component hierarchy (which components are needed)
2. Layout structure (how components are arranged)
3. Styling guidelines (color scheme, typography, spacing)
4. User flow (how users interact with the app)

Respond with JSON:
{
    "component_structure": ["Component1", "Component2", ...],
    "layout_description": "Description of the layout",
    "styling_guidelines": {
        "colors": {...},
        "typography": {...},
        "spacing": {...}
    },
    "user_flow": "Description of user interactions"
}
"""
    
    task_description = state.get("current_task_description", "Design the user interface")
    user_request = state.get("user_request", "")
    memory_context = state.get("memory_context", "")
    
    prompt = f"""
User Request: {user_request}

{memory_context}

Task: {task_description}

Design a modern, user-friendly interface that meets these requirements.
"""
    
    try:
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model="gpt-4",
            temperature=0.7,
            max_tokens=1500,
            system_prompt=system_prompt
        )
        
        # Parse JSON response
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        design_artifacts = json.loads(response_text.strip())
        
        logger.info(
            "Design completed",
            num_components=len(design_artifacts.get("component_structure", []))
        )
        
        # Update state with design artifacts
        completed_tasks = state.get("completed_tasks", [])
        completed_tasks.append("UI/UX Design")
        
        return {
            **state,
            "design_artifacts": design_artifacts,
            "completed_tasks": completed_tasks,
            "current_agent": "designer"
        }
    
    except Exception as e:
        logger.error("Designer failed", error=str(e))
        return {
            **state,
            "design_artifacts": {
                "component_structure": ["App", "Header", "MainContent", "Footer"],
                "layout_description": "Standard web layout",
                "error": str(e)
            },
            "completed_tasks": state.get("completed_tasks", []) + ["UI/UX Design (with errors)"],
            "current_agent": "designer"
        }

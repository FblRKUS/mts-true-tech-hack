from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def designer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    UX/UI Designer Agent with Workspace Integration.
    
    CRITICAL: Saves design specifications to workspace as design_spec.json.
    This file is read by Frontend Developer to implement the UI.
    
    Responsibilities:
    - Design user interface layouts
    - Define component structure
    - Specify styling guidelines
    - Create design specifications for frontend dev
    """
    
    logger.info("Designer agent started", user_request=state.get("user_request"))
    
    system_prompt = """You are an expert UX/UI Designer.

**CRITICAL INSTRUCTIONS:**
1. Your design will be saved to workspace as design_spec.json
2. Frontend Developer will read this file to implement the UI
3. Be specific and detailed in component descriptions

**Output Format:**
Respond with JSON design specification:
{
    "component_structure": ["Component1", "Component2", ...],
    "layout_description": "Description of the layout",
    "styling_guidelines": {
        "colors": {"primary": "#...", "secondary": "#..."},
        "typography": {"headings": "...", "body": "..."},
        "spacing": {"base": "8px", "scale": "1.5"}
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
        # Use model from user request
        model = state.get("request_model", "openai/qwen3-235b-a22b-2507")
        
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model=model,
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
        
        # CRITICAL: Save design to workspace as design_spec.json
        design_json = json.dumps(design_artifacts, indent=2)
        
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace["design_spec.json"] = design_json
        
        # Update state with design artifacts
        completed_tasks = state.get("completed_tasks", [])
        completed_tasks.append("UI/UX Design")
        
        return {
            **state,
            "workspace": updated_workspace,
            "design_artifacts": design_artifacts,  # Keep for compatibility
            "completed_tasks": completed_tasks,
            "current_agent": "designer",
            "qa_feedback": []  # Clear QA feedback (design is first step usually)
        }
    
    except Exception as e:
        logger.error("Designer failed", error=str(e))
        
        # Fallback design
        fallback_design = {
            "component_structure": ["App", "Header", "MainContent", "Footer"],
            "layout_description": "Standard web layout",
            "styling_guidelines": {
                "colors": {"primary": "#007bff", "secondary": "#6c757d"},
                "typography": {"headings": "sans-serif", "body": "system-ui"},
                "spacing": {"base": "8px"}
            },
            "user_flow": "Standard navigation flow"
        }
        
        # Save fallback to workspace
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace["design_spec.json"] = json.dumps(fallback_design, indent=2)
        
        return {
            **state,
            "workspace": updated_workspace,
            "design_artifacts": fallback_design,
            "completed_tasks": state.get("completed_tasks", []) + ["UI/UX Design (with errors)"],
            "current_agent": "designer",
            "qa_feedback": []  # Clear QA feedback
        }

from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def frontend_dev_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Frontend Developer Agent with Workspace Integration.
    
    CRITICAL: Writes code to shared workspace instead of state messages.
    Reads QA patches and applies fixes iteratively.
    
    Responsibilities:
    - Write client-side code (React, HTML, CSS, JavaScript)
    - Implement UI components based on design
    - Handle user interactions and state management
    - Apply QA patches when tests fail
    """
    
    logger.info("Frontend developer started")
    
    system_prompt = """You are an expert Frontend Developer specializing in React.

**CRITICAL INSTRUCTIONS:**
1. Your code will be saved to a shared workspace (NOT in chat messages)
2. If QA provided patches, you MUST apply them precisely
3. Generate complete, working code with all dependencies in package.json
4. Do NOT include code snippets in your response text - only in the JSON output

**Output Format:**
Respond ONLY with JSON mapping file paths to code content:
{
    "src/App.jsx": "<full code here>",
    "src/components/Header.jsx": "<full code here>",
    "src/styles/global.css": "<full code here>",
    "package.json": "<full package.json here>"
}

**QA Patches:**
If QA provided patches, apply them to the specified files EXACTLY as instructed.
"""
    
    design = state.get("design_artifacts", {})
    user_request = state.get("user_request", "")
    task_description = state.get("current_task_description", "Implement frontend")
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

Design Specifications:
- Components: {design.get('component_structure', [])}
- Layout: {design.get('layout_description', 'Standard layout')}
- Styling: {json.dumps(design.get('styling_guidelines', {}), indent=2)}

Task: {task_description}
{workspace_context}
{patches_context}

{'**This is a fix iteration. Apply the QA patches above.**' if qa_patches else '**This is the initial implementation.**'}

Generate complete, production-ready React code.
Include ALL dependencies in package.json.
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
        
        frontend_files = json.loads(response_text.strip())
        
        logger.info("Frontend code generated", num_files=len(frontend_files))
        
        # CRITICAL: Update workspace instead of frontend_code
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(frontend_files)
        
        completed_tasks = state.get("completed_tasks", [])
        if "Frontend Development" not in completed_tasks:
            completed_tasks.append("Frontend Development")
        
        return {
            **state,
            "workspace": updated_workspace,
            "frontend_code": frontend_files,  # Keep for compatibility
            "completed_tasks": completed_tasks,
            "current_agent": "frontend_dev",
            "qa_feedback": []  # CRITICAL: Clear QA feedback after applying patches
        }
    
    except Exception as e:
        logger.error("Frontend dev failed", error=str(e))
        
        # Provide fallback minimal code
        fallback_code = {
            "src/App.jsx": "export default function App() { return <div>Hello World</div>; }",
            "package.json": json.dumps({
                "name": "frontend-app",
                "version": "1.0.0",
                "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"}
            }, indent=2)
        }
        
        # Update workspace with fallback
        updated_workspace = state.get("workspace", {}).copy()
        updated_workspace.update(fallback_code)
        
        return {
            **state,
            "workspace": updated_workspace,
            "frontend_code": fallback_code,
            "completed_tasks": state.get("completed_tasks", []) + ["Frontend Development (fallback)"],
            "current_agent": "frontend_dev",
            "qa_feedback": []  # CRITICAL: Clear QA feedback
        }

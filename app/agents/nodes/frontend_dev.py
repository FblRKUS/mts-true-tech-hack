from typing import Dict, Any
from app.services.llm_router import llm_router
import structlog
import json

logger = structlog.get_logger(__name__)


async def frontend_dev_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Frontend Developer Agent.
    
    Responsibilities:
    - Write client-side code (React, HTML, CSS, JavaScript)
    - Implement UI components based on design
    - Handle user interactions and state management
    - Integrate with backend API
    """
    
    logger.info("Frontend developer started")
    
    system_prompt = """You are an expert Frontend Developer specializing in React.

Your task is to implement the frontend based on the design specifications.

Use modern best practices:
- Functional components with hooks
- Clean, readable code with comments
- Responsive design with Tailwind CSS
- Proper error handling

Respond with JSON mapping filenames to code:
{
    "src/App.jsx": "...",
    "src/components/Header.jsx": "...",
    "src/styles/global.css": "...",
    "package.json": "..."
}
"""
    
    design = state.get("design_artifacts", {})
    user_request = state.get("user_request", "")
    task_description = state.get("current_task_description", "Implement frontend")
    qa_feedback = state.get("qa_feedback", [])
    
    prompt = f"""
User Request: {user_request}

Design Specifications:
- Components: {design.get('component_structure', [])}
- Layout: {design.get('layout_description', 'Standard layout')}
- Styling: {json.dumps(design.get('styling_guidelines', {}), indent=2)}

Task: {task_description}

QA Feedback (if any):
{qa_feedback[-1] if qa_feedback else 'None - first iteration'}

Generate complete, production-ready React code.
"""
    
    try:
        response_text = await llm_router.generate_text(
            prompt=prompt,
            model="gpt-4",
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
        
        completed_tasks = state.get("completed_tasks", [])
        if "Frontend Development" not in completed_tasks:
            completed_tasks.append("Frontend Development")
        
        return {
            **state,
            "frontend_code": frontend_files,
            "completed_tasks": completed_tasks,
            "current_agent": "frontend_dev"
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
        
        return {
            **state,
            "frontend_code": fallback_code,
            "completed_tasks": state.get("completed_tasks", []) + ["Frontend Development (fallback)"],
            "current_agent": "frontend_dev"
        }

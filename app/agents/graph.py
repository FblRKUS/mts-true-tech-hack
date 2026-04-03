from typing import Annotated, TypedDict, Sequence
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from app.core.database import db_manager
from app.agents.supervisor import supervisor_node, route_supervisor
from app.agents.nodes import (
    designer_node,
    frontend_dev_node,
    backend_dev_node,
    devops_node,
    qa_tester_node
)
import structlog

logger = structlog.get_logger(__name__)


# Define state schema with message accumulation
class AgentGraphState(TypedDict):
    """State schema for the multi-agent graph."""
    
    # Messages with automatic accumulation
    messages: Annotated[Sequence[dict], add_messages]
    
    # User context
    user_request: str
    thread_id: str
    user_id: str
    memory_context: str
    
    # Routing
    next_agent: str
    current_agent: str
    current_task_description: str
    supervisor_reasoning: str
    
    # Task management
    task_plan: list[str]
    completed_tasks: list[str]
    
    # Generated artifacts
    design_artifacts: dict
    frontend_code: dict
    backend_code: dict
    devops_configs: dict
    
    # QA loop
    qa_iteration: int
    qa_feedback: list[str]
    e2b_test_results: dict
    
    # Output
    is_completed: bool
    final_response: str


# Global graph instance (compiled once)
_compiled_graph = None


async def get_agent_graph():
    """
    Get or create the compiled LangGraph.
    
    Returns compiled StateGraph with PostgresSaver checkpointer.
    Caches the graph instance for reuse across requests.
    """
    global _compiled_graph
    
    if _compiled_graph is not None:
        return _compiled_graph
    
    logger.info("Building LangGraph agent graph...")
    
    # Initialize PostgresSaver checkpointer
    checkpointer = await db_manager.initialize_checkpointer()
    
    # Create graph with typed state
    graph = StateGraph(AgentGraphState)
    
    # Add all nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("designer", designer_node)
    graph.add_node("frontend_dev", frontend_dev_node)
    graph.add_node("backend_dev", backend_dev_node)
    graph.add_node("devops", devops_node)
    graph.add_node("qa_tester", qa_tester_node)
    
    # Set entry point (supervisor decides first action)
    graph.set_entry_point("supervisor")
    
    # Supervisor routes to workers or END
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "designer": "designer",
            "frontend_dev": "frontend_dev",
            "backend_dev": "backend_dev",
            "devops": "devops",
            "qa_tester": "qa_tester",
            "end": END
        }
    )
    
    # All workers return to supervisor for next decision
    graph.add_edge("designer", "supervisor")
    graph.add_edge("frontend_dev", "supervisor")
    graph.add_edge("backend_dev", "supervisor")
    graph.add_edge("devops", "supervisor")
    graph.add_edge("qa_tester", "supervisor")
    
    # Compile graph with checkpointer for persistence
    _compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info(
        "LangGraph compiled successfully",
        num_nodes=6,
        checkpointer="PostgresSaver"
    )
    
    return _compiled_graph


async def visualize_graph(output_path: str = "graph.png"):
    """
    Generate visualization of the agent graph.
    
    Args:
        output_path: Path to save the graph image
    """
    try:
        graph = await get_agent_graph()
        
        # LangGraph can generate Mermaid diagram
        from IPython.display import Image, display
        
        display(Image(graph.get_graph().draw_mermaid_png()))
        logger.info("Graph visualization generated", path=output_path)
    
    except Exception as e:
        logger.warning("Could not generate graph visualization", error=str(e))


# Initialize default state values
def create_initial_state(
    user_request: str,
    user_id: str,
    thread_id: str,
    messages: list = None,
    memory_context: str = ""
) -> AgentGraphState:
    """
    Create initial state for graph execution.
    
    Args:
        user_request: User's request text
        user_id: User identifier
        thread_id: Conversation thread ID
        messages: Initial messages (optional)
        memory_context: Retrieved memory context
    
    Returns:
        Initialized AgentGraphState
    """
    return AgentGraphState(
        messages=messages or [],
        user_request=user_request,
        thread_id=thread_id,
        user_id=user_id,
        memory_context=memory_context,
        next_agent="",
        current_agent="",
        current_task_description="",
        supervisor_reasoning="",
        task_plan=[],
        completed_tasks=[],
        design_artifacts={},
        frontend_code={},
        backend_code={},
        devops_configs={},
        qa_iteration=0,
        qa_feedback=[],
        e2b_test_results={},
        is_completed=False,
        final_response=""
    )

"""Graph builder for the orchestrator."""

from typing import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.types import Checkpointer

from .state import OrchestratorState
from .router import router, post_agent_router
from app.supervisor.agents import (
    create_agent,
    create_master_node,
    create_concept_tutor_node,
    create_lab_mentor_node,
)
from app.supervisor.prompts import (
    MASTER_PROMPT,
    CONCEPT_TUTOR_PROMPT,
    LAB_MENTOR_PROMPT,
)
from app.supervisor.tools.handoff import (
    delegate_to_agent,
    hand_back_to_master,
)
from app.supervisor.tools.course import get_steps, get_sub_steps, get_questions
from app.supervisor.tools.plan_tools import plan_tools


def build_graph(
    model: BaseChatModel,
    checkpointer: Checkpointer | None = None,
    *,
    master_tools: Sequence[BaseTool] | None = None,
    concept_tutor_tools: Sequence[BaseTool] | None = None,
    lab_mentor_tools: Sequence[BaseTool] | None = None,
) -> StateGraph:
    """Build and compile the orchestrator graph with loop support.
    
    The graph supports same-turn re-delegation: when a sub-agent hands
    back or Master delegates, the graph loops back to the router instead
    of ending. This allows multi-hop agent chains within a single user
    message turn (e.g., sub-agent handback → Master → new delegation).
    
    Graph structure:
        START → router(initial) → agent → post_agent_router
            ↳ if handoff happened → router_node → agent → post_agent_router → ...
            ↳ if no handoff or max iterations → END
    
    Args:
        model: LLM to use for all agents
        checkpointer: State persistence checkpointer
        master_tools: Additional tools for master agent
        concept_tutor_tools: Additional tools for concept tutor
        lab_mentor_tools: Additional tools for lab mentor
        
    Returns:
        Compiled StateGraph
    """
    from app.supervisor.tools.memory import memory_tools

    # Build tool lists with required handoff tools
    master_tool_list = list(master_tools or []) + [
        get_steps, get_sub_steps, get_questions,
        delegate_to_agent,
        *plan_tools,  # check_plan_status, get_student_progress, request_plan_update
        *memory_tools, # list_recent_sessions, update_session_note, get_session_detail
    ]
    concept_tutor_tool_list = list(concept_tutor_tools or []) + [hand_back_to_master, *memory_tools]
    lab_mentor_tool_list = list(lab_mentor_tools or []) + [hand_back_to_master, *memory_tools]
    
    # Create agents
    master_agent = create_agent(model, MASTER_PROMPT, master_tool_list)
    concept_tutor_agent = create_agent(model, CONCEPT_TUTOR_PROMPT, concept_tutor_tool_list)
    lab_mentor_agent = create_agent(model, LAB_MENTOR_PROMPT, lab_mentor_tool_list)
    
    # Build graph
    graph = StateGraph(OrchestratorState)
    
    # ── Agent nodes ──
    graph.add_node("master", create_master_node(master_agent))
    graph.add_node("concept_tutor", create_concept_tutor_node(concept_tutor_agent))
    graph.add_node("lab_mentor", create_lab_mentor_node(lab_mentor_agent))
    
    # ── Router node (for loop re-entry) ──
    # This is separate from the START conditional edge. It increments
    # the iteration counter and routes to the next agent.
    def router_node(state: OrchestratorState) -> dict:
        """Increment iteration counter and clear the pending_handoff flag."""
        import json
        files = dict(state.get("files", {}))
        
        # Clear pending_handoff so the next agent starts fresh
        routing_file = files.get("/routing.json", {})
        if isinstance(routing_file, dict) and "content" in routing_file:
            try:
                routing = json.loads(routing_file["content"])
                routing.pop("pending_handoff", None)
                files["/routing.json"] = {
                    "content": json.dumps(routing),
                    "metadata": {"type": "json"},
                }
            except (json.JSONDecodeError, TypeError):
                pass
        
        return {
            "iteration": state.get("iteration", 0) + 1,
            "files": files,
        }
    
    graph.add_node("router_node", router_node)
    
    # ── Edges ──
    
    # Initial entry: START → route to first agent
    graph.add_conditional_edges(
        START,
        router,
        {
            "master": "master",
            "concept_tutor": "concept_tutor",
            "lab_mentor": "lab_mentor",
        }
    )
    
    # After each agent: decide loop vs END
    for agent_name in ["master", "concept_tutor", "lab_mentor"]:
        graph.add_conditional_edges(
            agent_name,
            post_agent_router,
            {
                "router": "router_node",
                "__end__": END,
            }
        )
    
    # Router node → route to next agent
    graph.add_conditional_edges(
        "router_node",
        router,
        {
            "master": "master",
            "concept_tutor": "concept_tutor",
            "lab_mentor": "lab_mentor",
        }
    )
    
    return graph.compile(checkpointer=checkpointer)

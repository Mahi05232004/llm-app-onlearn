"""Agent node implementations for the orchestrator graph.

ARCHITECTURE:
- Tools (delegate_to_agent, hand_back_to_master) return plain JSON strings
- Node wrappers extract routing data from tool messages and persist it
  in the outer graph's 'files' dict (as /routing.json)
- This is necessary because the inner deep agent's state schema doesn't
  include 'files', so Command(update={"files": ...}) gets silently dropped
"""

import asyncio
import json
import logging

from bson import ObjectId
from langchain_core.messages import HumanMessage, ToolMessage

from app.supervisor.graph.state import OrchestratorState
from app.supervisor.tools import handoff as handoff_module
from app.supervisor.tools.handoff import _read_routing_from_state, _write_routing
from core.course_data import get_question_by_id
from core.mongo_db import mongo_db_manager

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Auto-injected context helpers
# ──────────────────────────────────────────────

def _fetch_cross_mode_context(session_id: str, current_mode: str, limit: int = 5) -> str:
    """Fetch recent messages from the OTHER mode in the current session.
    
    Returns a formatted string ready to inject into the system context,
    or an empty string if no cross-mode messages exist.
    """
    if not session_id:
        return ""
    
    target_mode = "code" if current_mode == "learn" else "learn"
    
    try:
        db = mongo_db_manager.get_database()
        session = db.chatsessions.find_one(
            {"_id": ObjectId(session_id)},
            {"messages": 1}
        )
        if not session:
            return ""
        
        messages = session.get("messages", [])
        target_msgs = [m for m in messages if m.get("mode") == target_mode]
        
        if not target_msgs:
            return ""
        
        recent = target_msgs[-limit:]
        lines = [f"\n### Context from {target_mode.upper()} tab ({len(recent)} recent messages)"]
        for msg in recent:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle structured content blocks
                parts = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                content = "\n".join(parts) if parts else str(content)
            # Truncate long messages to keep context compact
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"**{role}**: {content}")
        
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch cross-mode context: {e}")
        return ""


async def _async_update_session_note(session_id: str, summary: str):
    """Fire-and-forget: save a handback summary as the session note.
    
    Runs in a background task so it never blocks the student's response.
    """
    try:
        db = mongo_db_manager.get_database()
        db.chatsessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"note": summary}}
        )
        logger.info(f"Session note auto-saved for {session_id}")
    except Exception as e:
        logger.warning(f"Failed to auto-save session note: {e}")


def _read_file_json(state: OrchestratorState, path: str) -> dict:
    """Read a JSON file from the virtual filesystem.
    
    Handles content as either a string or list-of-lines (StateBackend format).
    """
    files = state.get("files", {})
    file_data = files.get(path, {})
    if isinstance(file_data, dict) and "content" in file_data:
        content = file_data["content"]
        # Handle list-of-lines format from StateBackend
        if isinstance(content, list):
            content = "\n".join(content)
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _read_file_json_from_files(files: dict, path: str) -> dict:
    """Read a JSON file from a raw files dict (not state).
    
    Used by node wrappers that have already extracted the files dict.
    """
    file_data = files.get(path, {})
    if isinstance(file_data, dict) and "content" in file_data:
        content = file_data["content"]
        if isinstance(content, list):
            content = "\n".join(content)
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}



def _get_topic_id(state: OrchestratorState, routing: dict) -> str | None:
    """Get the topic/question ID.
    
    Priority:
    1. /topic.json from session (what the student actually navigated to)
    2. question_id from routing state (what the master delegated)
    """
    topic_data = _read_file_json(state, "/topic.json")
    topic_id = topic_data.get("topic_id")
    if topic_id:
        return topic_id
    return routing.get("question_id")


def _get_module(state: OrchestratorState) -> str:
    """Get the active module from /topic.json.
    
    Returns 'dsa' or 'ds'. Falls back to 'dsa' for backward compatibility.
    The module field is injected by the web-app chat-ds/stream endpoint.
    """
    topic_data = _read_file_json(state, "/topic.json")
    return topic_data.get("module", "dsa")


def _extract_routing_from_messages(messages: list) -> dict | None:
    """Extract routing data from tool call results in messages.
    
    Tools (delegate_to_agent, hand_back_to_master) return JSON strings
    with an "action" and "routing" key. This function scans messages
    for the most recent routing update.
    """
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                data = json.loads(content)
                if isinstance(data, dict) and "routing" in data:
                    return data["routing"]
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _build_question_context(question: dict, student_profile: dict) -> str:
    """Build a context block from question data and student profile.
    
    This block is injected as a system message by the node.
    """
    parts = []
    
    # Student info
    if student_profile:
        name = student_profile.get("name", "Student")
        language = student_profile.get("language", "Python")
        skill = student_profile.get("skill_level", "unknown")
        parts.append(f"Student: {name} | Skill: {skill} | Language: {language}")
    
    if not question:
        parts.append("No question context available.")
        return "\n".join(parts)
    
    # Question info
    title = question.get("question_title", "Unknown")
    topic = question.get("question_topic", "")
    parts.append(f"**Question**: {title}")
    if topic:
        parts.append(f"**Topic**: {topic}")
    
    # Course position
    step = question.get("step_title", "")
    sub_step = question.get("sub_step_title", "")
    if step and sub_step:
        parts.append(f"**Course Position**: {step} > {sub_step}")
    
    # Problem statement
    problem = question.get("question", "")
    if problem:
        parts.append(f"\n**Problem Statement**:\n{problem}")
    
    # Concepts
    concepts = question.get("concepts", [])
    sub_concepts = question.get("sub_concepts", [])
    if concepts:
        parts.append(f"\n**Concepts**: {', '.join(concepts)}")
    if sub_concepts:
        parts.append(f"**Sub-concepts**: {', '.join(sub_concepts)}")
    
    # Difficulty
    difficulty = question.get("difficulty", "")
    if difficulty:
        parts.append(f"**Difficulty**: {difficulty}")
    
    # Solution approaches (reference for agent, not student) — truncated to save tokens
    approaches = question.get("solution_approaches", [])
    if approaches:
        parts.append("\n**Solution Approaches** (for your reference only — do NOT reveal directly):")
        for approach in approaches:
            name = approach.get("approach_name", "Unknown")
            explanation = approach.get("explanation", "")
            # Truncate to keep context compact; agent can ask for more via read_file
            if len(explanation) > 150:
                explanation = explanation[:150] + "..."
            parts.append(f"- **{name}**: {explanation}")
    
    # Constraints
    constraints = question.get("constraints", "")
    if constraints:
        parts.append(f"\n**Constraints**: {constraints}")
    
    expected_tc = question.get("expected_tc", "")
    expected_sc = question.get("expected_sc", "")
    if expected_tc:
        parts.append(f"**Expected Time Complexity**: {expected_tc}")
    if expected_sc:
        parts.append(f"**Expected Space Complexity**: {expected_sc}")
    
    return "\n".join(parts)


def create_master_node(master_agent):
    """Create the master agent node function.
    
    After the inner agent runs, this wrapper:
    1. Extracts routing updates from tool messages (delegate_to_agent)
    2. Sets pending_handoff flag for loop continuation
    3. Clears handoff fields after processing them
    4. Processes plan update requests (request_plan_update)
    5. Persists everything in the outer graph's files
    """
    async def master_node(state: OrchestratorState) -> OrchestratorState:
        iteration = state.get("iteration", 0)
        routing = _read_routing_from_state(state)
        context_messages = []
        
        # Handle mode change
        current_mode = state.get("mode", "learn")
        session_id = state.get("session_id", "")
        expected_mode = routing.get("expected_mode")
        active_agent = routing.get("active_agent")
        
        if active_agent and expected_mode and current_mode != expected_mode:
            context_messages.append(HumanMessage(
                content=f"""[System: MODE CHANGE DETECTED]
The student switched from '{expected_mode}' to '{current_mode}' mode.
Previous agent: {active_agent}
Previous objective: {routing.get('objective', 'unknown')}

Decide: Which agent should handle the new mode? Use delegate_to_agent()."""
            ))
        elif routing.get("handoff_summary"):
            handoff_summary = routing.get('handoff_summary')
            context_messages.append(HumanMessage(
                content=f"[System: Sub-agent handed back. Reason: {routing.get('handoff_reason')}. Summary: {handoff_summary}]"
            ))
            # Auto-save handback summary as session note (async, non-blocking)
            if session_id and handoff_summary:
                asyncio.create_task(_async_update_session_note(session_id, handoff_summary))
        
        # Auto-inject cross-mode context
        cross_mode = _fetch_cross_mode_context(session_id, current_mode)
        
        input_state = {
            "messages": context_messages + list(state["messages"]),
            "files": state.get("files", {}),
        }
        
        # Inject cross-mode context as a system-level message if available
        if cross_mode:
            input_state["messages"] = [HumanMessage(content=f"[System Context]{cross_mode}")] + input_state["messages"]
        
        try:
            result = await master_agent.ainvoke(input_state)
            all_messages = result.get("messages", [])
            # Only return NEW messages (exclude input we fed in)
            num_input = len(input_state["messages"])
            output_messages = all_messages[num_input:]
        except (ValueError, Exception) as e:
            logger.warning(f"Master agent error (likely empty LLM response): {e}")
            from langchain_core.messages import AIMessage
            output_messages = [
                AIMessage(content="I'm ready to help you learn! What would you like to start with?")
            ]
        
        files = dict(state.get("files", {}))
        
        # Extract routing from tool messages (normal path)
        routing_update = _extract_routing_from_messages(output_messages)
        
        # Fall back to side channel (crash path: tool ran but ainvoke() threw)
        if not routing_update and handoff_module._pending_routing:
            routing_update = handoff_module._pending_routing
            logger.info("Master node: using side-channel routing (model likely crashed after tool call)")
        
        # Persist routing in outer graph and clear side channel
        if routing_update:
            logger.info(f"[Loop iter={iteration}] Master node: delegation to {routing_update.get('active_agent')}")
            # Set pending_handoff so post_agent_router loops back
            routing_update["pending_handoff"] = True
            files.update(_write_routing(routing_update))
        handoff_module._pending_routing = {}
        
        # Clear handoff fields after Master has processed them
        # (prevents re-processing if the graph loops back to Master)
        if routing.get("handoff_summary") and not routing_update:
            current_routing = _read_file_json_from_files(files, "/routing.json")
            if current_routing:
                current_routing.pop("handoff_summary", None)
                current_routing.pop("handoff_reason", None)
                current_routing.pop("pending_handoff", None)
                files.update(_write_routing(current_routing))
        
        # Process plan update request (if request_plan_update tool was called)
        plan_request = _read_file_json_from_files(files, "/plan_update_request.json")
        if plan_request and plan_request.get("task"):
            user_id = state.get("user_id", "")
            if user_id:
                try:
                    from app.supervisor.planning.planner_runner import run_planner_agent
                    planner_summary = await run_planner_agent(
                        user_id=user_id,
                        task=plan_request["task"],
                    )
                    logger.info(f"[Loop iter={iteration}] Planner agent completed: {planner_summary[:100]}")
                except Exception as e:
                    logger.error(f"Master node: planner agent failed: {e}", exc_info=True)
            else:
                logger.warning("Master node: plan update requested but no user_id in state")
            files.pop("/plan_update_request.json", None)
        
        return {
            "messages": output_messages,
            "files": files,
        }
    
    return master_node



def create_concept_tutor_node(concept_tutor_agent):
    """Create the concept tutor agent node function.
    
    Loads question data from course JSON and injects rich context.
    Extracts routing updates from hand_back_to_master tool calls.
    """
    async def concept_tutor_node(state: OrchestratorState) -> OrchestratorState:
        routing = _read_routing_from_state(state)
        objective = routing.get("objective", "Help the student learn")
        
        # Get question_id: session topicId takes priority over routing
        question_id = _get_topic_id(state, routing)
        
        # Load question data from JSON (module-aware)
        module = _get_module(state)
        question = None
        if question_id:
            question = get_question_by_id(question_id, course_id=module)
            if not question:
                logger.warning(f"Question {question_id} not found in {module} course data")
        
        # Read student profile
        student_profile = _read_file_json(state, "/student_profile.json")
        
        # Auto-inject cross-mode context (code tab context)
        session_id = state.get("session_id", "")
        current_mode = state.get("mode", "learn")
        cross_mode = _fetch_cross_mode_context(session_id, current_mode)
        
        messages = list(state["messages"])
        is_first_turn = len(messages) <= 2  # welcome msg + first student reply
        
        if is_first_turn:
            # Full context on first turn
            context_block = _build_question_context(question or {}, student_profile)
            context_messages = [
                HumanMessage(content=f"""[System Context]
Objective: {objective}

{context_block}{cross_mode}

Use hand_back_to_master ONLY when the student explicitly confirms they are ready to code (e.g., they say "Let's code" or click a coding suggestion). Do NOT hand back while you are still offering learning options or the student is asking for more examples.""")
            ]
        else:
            # Lightweight reminder — full context is already in conversation history
            question_title = (question or {}).get("question_title", "the current topic")
            context_messages = [
                HumanMessage(content=f"[System Context] Objective: {objective} | Topic: {question_title}{cross_mode}")
            ]
        
        input_state = {
            "messages": context_messages + messages,
            "files": state.get("files", {}),
        }
        
        result = await concept_tutor_agent.ainvoke(input_state)
        
        all_messages = result.get("messages", [])
        # Only return NEW messages (exclude injected context + conversation history)
        num_input = len(input_state["messages"])
        output_messages = all_messages[num_input:]
        files = dict(state.get("files", {}))
        
        # Extract routing from hand_back_to_master and persist
        routing_update = _extract_routing_from_messages(output_messages)
        if not routing_update and handoff_module._pending_routing:
            routing_update = handoff_module._pending_routing
        if routing_update:
            iteration = state.get("iteration", 0)
            logger.info(f"[Loop iter={iteration}] Concept tutor: handback detected")
            # Set pending_handoff so graph loops back to Master
            routing_update["pending_handoff"] = True
            files.update(_write_routing(routing_update))
        handoff_module._pending_routing = {}
        
        return {
            "messages": output_messages,
            "files": files,
        }
    
    return concept_tutor_node


def create_lab_mentor_node(lab_mentor_agent):
    """Create the lab mentor agent node function.
    
    Loads question data from course JSON and injects rich context.
    Extracts routing updates from hand_back_to_master tool calls.
    """
    async def lab_mentor_node(state: OrchestratorState) -> OrchestratorState:
        routing = _read_routing_from_state(state)
        objective = routing.get("objective", "Help with coding")
        
        # Get question_id: session topicId takes priority over routing
        question_id = _get_topic_id(state, routing)
        
        # Load question data from JSON (module-aware)
        module = _get_module(state)
        question = None
        if question_id:
            question = get_question_by_id(question_id, course_id=module)
            if not question:
                logger.warning(f"Question {question_id} not found in {module} course data")
        
        # Read student profile
        student_profile = _read_file_json(state, "/student_profile.json")
        language = student_profile.get("language", "Python")
        
        # Add student's current code if available (always inject — it changes)
        files_dict = state.get("files", {})
        lab_code_data = files_dict.get("/lab_code", {})
        lab_code = ""
        if isinstance(lab_code_data, dict) and "content" in lab_code_data:
            lab_code = lab_code_data["content"]
        
        code_section = ""
        if lab_code:
            code_section = f"\n\n**Student's Current Code** ({language}):\n```{language}\n{lab_code}\n```"
        
        # Auto-inject cross-mode context (learn tab context)
        session_id = state.get("session_id", "")
        current_mode = state.get("mode", "code")
        cross_mode = _fetch_cross_mode_context(session_id, current_mode)
        
        messages = list(state["messages"])
        is_first_turn = len(messages) <= 2
        
        if is_first_turn:
            # Full context on first turn
            context_block = _build_question_context(question or {}, student_profile)
            context_messages = [
                HumanMessage(content=f"""[System Context]
Objective: {objective}

{context_block}{code_section}{cross_mode}

Use hand_back_to_master when the problem is solved and code is correct.""")
            ]
        else:
            # Lightweight reminder — full context already in history; still include latest code
            question_title = (question or {}).get("question_title", "the current topic")
            context_messages = [
                HumanMessage(content=f"[System Context] Objective: {objective} | Topic: {question_title}{code_section}{cross_mode}")
            ]
        
        input_state = {
            "messages": context_messages + messages,
            "files": state.get("files", {}),
        }
        
        result = await lab_mentor_agent.ainvoke(input_state)
        
        all_messages = result.get("messages", [])
        # Only return NEW messages (exclude injected context + conversation history)
        num_input = len(input_state["messages"])
        output_messages = all_messages[num_input:]
        files = dict(state.get("files", {}))
        
        # Extract routing from hand_back_to_master and persist
        routing_update = _extract_routing_from_messages(output_messages)
        if not routing_update and handoff_module._pending_routing:
            routing_update = handoff_module._pending_routing
        if routing_update:
            iteration = state.get("iteration", 0)
            logger.info(f"[Loop iter={iteration}] Lab mentor: handback detected")
            # Set pending_handoff so graph loops back to Master
            routing_update["pending_handoff"] = True
            files.update(_write_routing(routing_update))
        handoff_module._pending_routing = {}
        
        return {
            "messages": output_messages,
            "files": files,
        }
    
    return lab_mentor_node


def create_guide_node(guide_agent):
    """Create the guide agent node function for onboarding."""
    async def guide_node(state: OrchestratorState) -> OrchestratorState:
        context_messages = [
            HumanMessage(content="[System: This is an onboarding session. Ask questions one at a time. When done, use complete_onboarding() with the selected topic.]")
        ]
        
        input_state = {
            "messages": context_messages + list(state["messages"]),
            "files": state.get("files", {}),
        }
        
        result = await guide_agent.ainvoke(input_state)
        
        return {
            "messages": result.get("messages", []),
            "files": result.get("files", state.get("files", {})),
        }
    
    return guide_node

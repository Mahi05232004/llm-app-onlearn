"""Mode-specific code retrieval tools.

Two focused tools that read code directly from their own mode,
with no cross-mode ambiguity:

  get_lab_code   → reads `lab_code`      (Code editor / Lab mode)
  get_learn_code → reads `current_code`  (Learn mode scratchpad)

These are distinct from get_cross_mode_code (which reads the *other* mode).
Use these when the agent needs the student's code from its own mode context.
"""

import json
from langchain_core.tools import tool
from bson import ObjectId
from core.mongo_db import mongo_db_manager


def _get_db():
    return mongo_db_manager.get_database()


def _fetch_code_field(session_id: str, field: str, label: str) -> str:
    """Shared helper: fetch a single code field from the session document."""
    db = _get_db()
    
    query = {"_id": session_id}
    try:
        query = {"_id": ObjectId(session_id)}
    except Exception:
        # If it's not a valid 24-char hex, the frontend might have passed a custom string ID
        # like "session_1741246067". We just fall back to querying it as a raw string.
        pass

    try:
        session = db["chatsessions"].find_one(
            query,
            {field: 1},
        )
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Database connection error: {str(e)}",
        })

    if not session:
        return json.dumps({
            "status": "not_found",
            "message": f"No session found with id={session_id}",
        })

    code_map = session.get(field)
    if not code_map or not isinstance(code_map, dict) or not code_map:
        return json.dumps({
            "status": "empty",
            "message": f"The student has not written any code in {label} yet.",
        })

    language = next(iter(code_map))
    code_content = code_map[language]

    return json.dumps({
        "status": "success",
        "source": label,
        "language": language,
        "code": code_content,
    })


from langchain_core.runnables.config import RunnableConfig

@tool
def get_lab_code(config: RunnableConfig) -> str:
    """Fetch the student's current code from the Code editor (Lab mode).

    Use this in [CODE] mode to read what the student has written in the
    center editor panel. Combine with execute_code to run it and guide
    the student based on actual output.

    DO NOT use this in [LEARN] mode — use get_learn_code instead.

    Returns:
        JSON with status, language, and code content.
    """
    session_id = config.get("configurable", {}).get("tutor_context", {}).get("session_id")
    if not session_id:
        return json.dumps({"status": "error", "message": "System error: No active session_id found in context."})
    return _fetch_code_field(session_id, "lab_code", "Code Editor (Lab)")


@tool
def get_learn_code(config: RunnableConfig) -> str:
    """Fetch the student's current code from the Learn mode scratchpad.

    Use this in [LEARN] mode to see what the student wrote in the right-side
    code editor during concept practice. Helpful for reviewing their scratchpad
    attempts while teaching concepts.

    DO NOT use this in [CODE] mode — use get_lab_code instead.
    DO NOT execute this code — it's a scratchpad, not a lab submission.

    Returns:
        JSON with status, language, and code content.
    """
    session_id = config.get("configurable", {}).get("tutor_context", {}).get("session_id")
    if not session_id:
        return json.dumps({"status": "error", "message": "System error: No active session_id found in context."})
    return _fetch_code_field(session_id, "current_code", "Learn Mode Scratchpad")

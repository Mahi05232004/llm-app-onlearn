"""get_cross_mode_code tool — Retrieve code from the other interface mode.

Allows the tutor agent to peek at the student's code from learn mode
while in code mode (or vice versa).  This bridges the gap between the
two isolated editors.
"""

import json
from typing import Optional
from langchain_core.tools import tool
from bson import ObjectId
from core.mongo_db import mongo_db_manager


def _get_db():
    """Get the MongoDB database handle (reuses the singleton connection)."""
    return mongo_db_manager.get_database()


from langchain_core.runnables.config import RunnableConfig

@tool
def get_cross_mode_code(config: RunnableConfig) -> str:
    """Retrieve the student's code from the OTHER interface mode.

    Use this when you need to see what the student wrote in learn mode
    while they are in code mode, or vice versa.

    Returns:
        The student's code from the other mode, or a message if none exists.
    """
    tutor_context = config.get("configurable", {}).get("tutor_context", {})
    session_id = tutor_context.get("session_id")
    current_mode = tutor_context.get("mode")

    if not session_id or not current_mode:
        return json.dumps({"status": "error", "message": "System error: No active session_id or mode found in context."})

    db = _get_db()

    # Determine which field to read
    if current_mode == "code":
        target_field = "current_code"  # Learn mode scratchpad
        target_label = "Learn Mode (Scratchpad)"
    else:
        target_field = "lab_code"  # Code mode lab editor
        target_label = "Code Mode (Lab Editor)"

    query = {"_id": session_id}
    try:
        query = {"_id": ObjectId(session_id)}
    except Exception:
        pass

    try:
        session = db["chatsessions"].find_one(
            query,
            {target_field: 1}
        )
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Database connection error: {str(e)}"
        })

    if not session:
        return json.dumps({
            "status": "not_found",
            "message": "No session found with the given ID."
        })

    code_map = session.get(target_field)
    if not code_map or not isinstance(code_map, dict) or len(code_map) == 0:
        return json.dumps({
            "status": "empty",
            "message": f"The student has no code in {target_label} yet."
        })

    # code_map is { language: code_content }
    language = list(code_map.keys())[0]
    code_content = code_map[language]

    return json.dumps({
        "status": "success",
        "source": target_label,
        "language": language,
        "code": code_content,
    })

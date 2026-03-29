import sys
sys.path.insert(0, '/Users/mohan/Downloads/Onlearn-monorepo/llm-app')

from app.tutor.core.context_middleware import _format_session_context

mock_ctx = {
    "question_id": "q_2",
    "learning_plan": {
        "weeks": [
            {
                "week_number": 1,
                "focus_area": "Arrays",
                "topics": [
                    {"question_id": "q_1", "title": "Two Sum", "status": "completed"}
                ]
            },
            {
                "week_number": 2,
                "focus_area": "Pointers",
                "topics": [
                    {"question_id": "q_2", "title": "Three Sum", "status": "in_progress"}
                ]
            }
        ]
    }
}

print("OUTPUT:")
print(_format_session_context(mock_ctx))

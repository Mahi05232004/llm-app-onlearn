from langchain_core.tools import tool
from core.course_data import get_sidebar_data as get_course_sidebar_data
import logging

logger = logging.getLogger(__name__)


@tool
def get_steps(course_id: str = "dsa") -> dict:
    """
    Get a high-level overview of all course steps with progress statistics.
    
    Use this tool FIRST to understand the overall course structure.
    This returns only step-level data (no sub-steps or questions).
    
    Args:
        course_id: The course to get steps for ('dsa' or 'ds'). Default: 'dsa'.
    
    Returns:
        A dictionary with:
        - total_questions: Total questions in the course
        - steps: List of {step_no, step_title}
    """
    try:
        # Get sidebar data from JSON course loader
        data = get_course_sidebar_data(course_id=course_id)
        
        # Create compact step overview
        steps_overview = []
        total_questions = 0
        
        for step in data:
            step_questions = sum(len(ss.get("questions", [])) for ss in step.get("sub_steps", []))
            total_questions += step_questions
            steps_overview.append({
                "step_no": step["step_no"],
                "title": step["title"],
                "question_count": step_questions,
            })
        
        return {
            "total_questions": total_questions,
            "steps": steps_overview,
        }
    except Exception as e:
        logger.error(f"Error fetching steps: {e}")
        return {"error": str(e)}


@tool
def get_sub_steps(step_no: int, course_id: str = "dsa") -> dict:
    """
    Get the sub-steps within a specific step.
    
    Use this AFTER get_steps() to drill down into a particular step.
    
    Args:
        step_no: The step number to get sub-steps for (e.g., 1, 2, 3).
        course_id: The course to get sub-steps for ('dsa' or 'ds'). Default: 'dsa'.
    
    Returns:
        A dictionary with:
        - step_no: The requested step number
        - step_title: Title of the step
        - sub_steps: List of {sub_step_no, sub_step_title}
    """
    try:
        data = get_course_sidebar_data(course_id=course_id)
        
        # Find the requested step
        for step in data:
            if step["step_no"] == step_no:
                sub_steps_overview = [
                    {
                        "sub_step_no": ss["sub_step_no"],
                        "title": ss["title"],
                        "question_count": len(ss.get("questions", [])),
                    }
                    for ss in step.get("sub_steps", [])
                ]
                return {
                    "step_no": step_no,
                    "step_title": step["title"],
                    "sub_steps": sub_steps_overview,
                }
        
        return {"error": f"Step {step_no} not found"}
    except Exception as e:
        logger.error(f"Error fetching sub-steps: {e}")
        return {"error": str(e)}


@tool
def get_questions(step_no: int, sub_step_no: int, course_id: str = "dsa") -> dict:
    """
    Get all questions within a specific sub-step.
    
    Use this AFTER get_sub_steps() to see the actual topics/questions.
    The question 'question_id' is the topic_id you need for complete_onboarding.
    
    Args:
        step_no: The step number (e.g., 1, 2, 3).
        sub_step_no: The sub-step number within the step.
        course_id: The course to get questions for ('dsa' or 'ds'). Default: 'dsa'.
    
    Returns:
        A dictionary with:
        - step_no, sub_step_no: The requested location
        - sub_step_title: Title of the sub-step
        - questions: List of {question_id, sl_no, question_title, difficulty}
    """
    try:
        data = get_course_sidebar_data(course_id=course_id)
        
        # Find the requested sub-step
        for step in data:
            if step["step_no"] == step_no:
                for ss in step.get("sub_steps", []):
                    if ss["sub_step_no"] == sub_step_no:
                        return {
                            "step_no": step_no,
                            "sub_step_no": sub_step_no,
                            "sub_step_title": ss["title"],
                            "questions": ss.get("questions", []),
                        }
                return {"error": f"Sub-step {sub_step_no} not found in step {step_no}"}
        
        return {"error": f"Step {step_no} not found"}
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        return {"error": str(e)}

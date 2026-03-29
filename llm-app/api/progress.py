from fastapi import APIRouter, HTTPException, Query
from core.course_data import get_questions

# Create router instance
router = APIRouter()

@router.get("/{username}")
async def get_progress(username: str, course_id: str = Query("dsa", description="Course ID ('dsa' or 'ds')")):
    """
    Get progress data for a student.
    
    Note: Without Neo4j, progress tracking is handled by MongoDB.
    This endpoint returns basic course statistics from JSON data.
    User-specific progress should be fetched from MongoDB user profile.
    
    Args:
        username: The student's username
        course_id: The course to get progress for ('dsa' or 'ds')
    """
    try:
        questions = get_questions(course_id=course_id)
        total_questions = len(questions)
        
        # Return basic stats - actual user progress is stored in MongoDB
        return {
            "student_id": username,
            "total_questions": total_questions,
            "completed_questions": 0,  # Should come from MongoDB
            "completion_percentage": 0,
            "daily_progress": [],
            "course_progress": [],
            "current_streak": 0,
            "longest_streak": 0,
            "avg_daily_questions": 0,
            "active_days": 0,
            "this_week_solved": 0,
            "last_week_solved": 0,
            "note": "Progress tracking is handled by MongoDB. This endpoint provides static course info."
        }
    except Exception as e:
        print(f"Error fetching progress: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

from fastapi import APIRouter, HTTPException, Query
from core.course_data import get_sidebar_data, get_courses

# Create router instance
router = APIRouter()

@router.get("/test")
async def test_courses():
    """Test endpoint for courses."""
    return {"message": "Courses API is working!"}

# Add a simple get endpoint to test
@router.get("/health")
async def courses_health():
    """Health check for courses."""
    return {"status": "courses healthy"}

@router.get("/{username}")
async def get_courses_data(username: str, module: str = Query("dsa", description="Module/course ID (e.g. 'dsa', 'ds')")):
    """Get course structure/sidebar data for a specific module."""
    try:
        # Map module to course_id (they're the same for now)
        course_id = module
        
        # Get sidebar structure from JSON course data
        sidebar_data = get_sidebar_data(course_id=course_id)
        courses = get_courses()
        
        return {
            "total_questions": sum(
                len(sub["questions"]) 
                for step in sidebar_data 
                for sub in step.get("sub_steps", [])
            ),
            "steps": sidebar_data,
            "courses": courses
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


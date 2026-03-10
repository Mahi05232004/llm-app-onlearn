from fastapi import APIRouter, HTTPException
from core.course_data import get_sidebar_data, get_courses

# Create router instance
router = APIRouter()

@router.get("/test")
async def test_courses_ds():
    """Test endpoint for DS courses."""
    return {"message": "DS Courses API is working!"}

@router.get("/health")
async def courses_ds_health():
    """Health check for DS courses."""
    return {"status": "ds courses healthy"}

@router.get("/{username}")
async def get_ds_courses_data(username: str):
    """Get DS course structure/sidebar data."""
    try:
        # Get sidebar structure from DS JSON course data
        sidebar_data = get_sidebar_data(course_id="ds")
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

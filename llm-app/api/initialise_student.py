import logging
import sys
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from config.settings import app_config
from core.course_data import course_loader

# Setup logging
logging.basicConfig(
    level=app_config.log_level,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Create router instance
router = APIRouter()

@router.post("/initialise-student")
async def initialise_student(request: Request):
    """
    Initialise/validate student for the course.
    
    With JSON-based course data, we no longer create Neo4j nodes.
    This endpoint now just validates the request and confirms the course is loaded.
    Student data is managed through MongoDB.
    """
    try:
        request_data = await request.json()
        logger.debug(f"Received request data: {request_data}")
        
        username = request_data.get("username")
        email = request_data.get("email")
        name = request_data.get("name")
        
        if not username or not name:
            logger.warning("Missing required fields: 'username' and/or 'name'")
            raise HTTPException(status_code=400, detail="Missing required fields: 'username' and 'name'")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing request JSON: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

    # Verify course data is loaded
    try:
        courses = course_loader.get_courses()
        # Validate all active courses have questions loaded
        total_questions = 0
        for course in courses:
            if course.get("isActive"):
                cid = course.get("id", "dsa")
                qs = course_loader.get_questions(course_id=cid)
                total_questions += len(qs)
        
        if not courses:
            logger.error("No courses loaded")
            raise HTTPException(status_code=500, detail="Course data not loaded")
            
        logger.info(f"Student initialised: {username}, courses available: {len(courses)}, total questions: {total_questions}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify course data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to verify course data: {str(e)}")

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "success": True,
            "message": "Student initialized successfully",
            "student": {
                "username": username,
                "name": name,
                "email": email
            },
            "courses_available": len(courses),
            "total_questions": total_questions
        }
    )

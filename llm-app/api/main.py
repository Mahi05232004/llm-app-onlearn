import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Suppress noisy pymongo debug logs
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
logging.getLogger("pymongo.connection").setLevel(logging.WARNING)
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.courses import router as courses_router
from api.courses_ds import router as courses_ds_router
from api.initialise_student import router as initialise_student_router
from api.execution import router as execution_router
from api.validation import router as validation_router
from api.progress import router as progress_router
from core.rate_limiter import limiter
from core.course_data import course_loader

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown events."""
    # Startup - load course data
    try:
        course_loader.reload()  # Pre-load and cache course data
    except Exception as e:
        raise
    
    yield  # Application runs here
    
    # Shutdown - nothing to clean up for JSON

# Create FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)

# Set up rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware with specific origins
app.add_middleware(                     # TODO *: Add CORS middleware
    CORSMiddleware,
    allow_origins=[
        "*"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Include routers
app.include_router(courses_router, prefix="/courses", tags=["courses"])
app.include_router(courses_ds_router, prefix="/courses-ds", tags=["courses-ds"])
app.include_router(initialise_student_router, prefix="/kg", tags=["kg"])
app.include_router(execution_router, prefix="/execute", tags=["execution"])
app.include_router(validation_router, prefix="/validation", tags=["validation"])
app.include_router(progress_router, prefix="/progress", tags=["progress"])

# Chat - unified agent routing (Master + Concept Tutor + Lab Mentor)
from app.api.endpoints.orchestrator import router as chat_router
app.include_router(chat_router, prefix="/chat", tags=["chat"])

# Plan - adaptive weekly planning system
from app.api.endpoints.plan import router as plan_router
app.include_router(plan_router, prefix="/plan", tags=["plan"])

# Test/Debug endpoints (trace viewing, flagging, seed/reset)
# Only enabled when ENABLE_TEST_ENDPOINTS=1
import os
if os.environ.get("ENABLE_TEST_ENDPOINTS", "0") == "1":
    from tests.supervisor.tracing.endpoints import router as test_router
    app.include_router(test_router, prefix="/api/test", tags=["test"])
    logging.getLogger(__name__).info("Test endpoints enabled at /api/test/")

@app.get("/")
async def root():
    return {"response": "FastWise API is running!"}

@app.get("/health")
async def health_check():
    courses = course_loader.get_courses()
    return {
        "status": "healthy" if courses else "unhealthy",
        "courses_loaded": len(courses)
    }

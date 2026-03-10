
import logging
from models.state import GraphState

from fastapi import APIRouter, HTTPException

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/generate")
async def generate_text(request: GraphState):
    try:
        pass
    except Exception as e:
        logger.error(f"Error generating text: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
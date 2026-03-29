"""Onboarding API Endpoints."""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.plan_models import StudentProfile, LearningPlan, Progress
from app.planning.service import PlanningService
from app.planning.plan_store import plan_store
from app.tutor.core.store import get_tutor_store
from app.tutor.core.workspace import initialize_tutor_workspace
from core.mongo_db import mongo_db_manager
from bson import ObjectId

router = APIRouter()
logger = logging.getLogger(__name__)

class GeneratePlanRequest(BaseModel):
    profile: StudentProfile
    user_id: str
    module: str = "dsa"

class ApprovePlanRequest(BaseModel):
    user_id: str
    plan: dict[str, Any]      # The full LearningPlan dict
    profile: StudentProfile
    progress: dict[str, Any]  # The initial Progress dict
    module: str = "dsa"       # Which module this plan is for
    repersonalizing: bool = False  # True if user triggered re-personalization

@router.post("/generate")
async def generate_initial_plan(request: GeneratePlanRequest):
    """Generate a plan preview for the student to review."""
    try:
        service = PlanningService()
        # Generate but do NOT save yet
        plan, progress = await service.generate_initial_plan(
            request.profile, 
            user_id=request.user_id
        )
        
        return {
            "success": True,
            "plan": plan.model_dump(mode="json"),
            "progress": progress.model_dump(mode="json"),
        }
    except Exception as e:
        logger.error(f"Plan generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/approve")
async def approve_initial_plan(request: ApprovePlanRequest):
    """Save the approved plan and initialize the agent workspace."""
    try:
        module = request.module
        user_id = request.user_id
        new_plan = request.plan

        # 1. Carry over topic completion statuses from old plan (silent migration)
        old_data = plan_store.get_plan_data(user_id=user_id, module=module)
        old_plan = old_data.get("learningPlan")
        if old_plan:
            old_statuses: dict[str, str] = {
                t["question_id"]: t.get("status", "not_started")
                for w in old_plan.get("weeks", [])
                for t in w.get("topics", [])
                if t.get("question_id")
            }
            for week in new_plan.get("weeks", []):
                for topic in week.get("topics", []):
                    qid = topic.get("question_id")
                    if qid and qid in old_statuses:
                        topic["status"] = old_statuses[qid]
            logger.info(
                f"[Approve] Carried over statuses for {len(old_statuses)} topics "
                f"(user={user_id}, module={module})"
            )

        # Mark as a personalized (non-default) plan
        new_plan["is_default"] = False

        # 2. Initialize workspace (AGENTS.md)
        store = get_tutor_store()
        await initialize_tutor_workspace(store, user_id)

        # 3. Save plan & progress to MongoDB
        short_term = PlanningService().get_short_term_summary(LearningPlan(**new_plan))
        
        plan_store.save_plan_data(
            user_id=user_id,
            module=module,
            plan=new_plan,
            progress=request.progress,
            short_term=short_term,
        )

        # 4. If this was a re-personalization, clear the repersonalizing flag
        #    and ensure onboardingCompleted stays true
        if request.repersonalizing:
            db = mongo_db_manager.get_database()
            db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    f"modules.{module}.repersonalizing": False,
                    f"modules.{module}.onboardingCompleted": True,
                    f"modules.{module}.previousPlan": None,   # clear snapshot
                    "onboardingCompleted": True,
                }, "$unset": {
                    f"modules.{module}.previousPlan": "",
                }},
            )
            logger.info(f"[Approve] Cleared repersonalizing flag for user={user_id}, module={module}")

        # 5. Write short_term_plan.md to agent memory
        short_term_content = f"# Short Term Plan\n\n**Current Focus:** {short_term.get('current_focus')}\n"
        for topic in short_term.get("next_topics", []):
            short_term_content += f"- [ ] {topic['title']} (Week {topic['week']})\n"
        
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        
        await store.aput(
            (user_id,), 
            "short_term_plan.md", 
            {"content": short_term_content, "created_at": now, "modified_at": now}
        )
        
        # 6. Write student_profile.json
        await store.aput(
            (user_id,),
            "student_profile.json",
            {"content": request.profile.model_dump_json(), "created_at": now, "modified_at": now}
        )

        return {"success": True}

    except Exception as e:
        logger.error(f"Plan approval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


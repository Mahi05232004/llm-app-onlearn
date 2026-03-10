"""
MongoDB data access layer for the planning system.

Provides read/write access to the user document's planning fields:
- learningPlan: The full weekly learning plan
- progress: Progress metrics (pace, completion %, streak)
- studentProfile: Student's onboarding data
- shortTermPlan: Current week + next 3 topics (for agent context)
- planStartedAt: When the student started learning
"""

import json
import logging
from datetime import datetime, UTC
from typing import Any, Optional

from bson import ObjectId

from core.mongo_db import mongo_db_manager

logger = logging.getLogger(__name__)


class PlanStore:
    """Read/write plan data from/to MongoDB user documents."""

    def __init__(self):
        self.db = mongo_db_manager.get_database()
        self.users = self.db["users"]

    def get_plan_data(self, user_id: str) -> dict[str, Any]:
        """Read all planning-related fields from the user document.

        Returns:
            Dict with keys: learningPlan, progress, studentProfile,
            planStartedAt, shortTermPlan. Missing fields default to None.
        """
        try:
            user = self.users.find_one(
                {"_id": ObjectId(user_id)},
                {
                    "learningPlan": 1,
                    "progress": 1,
                    "studentProfile": 1,
                    "planStartedAt": 1,
                    "shortTermPlan": 1,
                },
            )
            if not user:
                logger.warning(f"User {user_id} not found in MongoDB")
                return {}

            return {
                "learningPlan": user.get("learningPlan"),
                "progress": user.get("progress"),
                "studentProfile": user.get("studentProfile"),
                "planStartedAt": user.get("planStartedAt"),
                "shortTermPlan": user.get("shortTermPlan"),
            }
        except Exception as e:
            logger.error(f"Failed to read plan data for user {user_id}: {e}")
            return {}

    def save_plan_data(
        self,
        user_id: str,
        plan: dict | None = None,
        progress: dict | None = None,
        short_term: dict | None = None,
    ) -> bool:
        """Write updated plan data back to the user document.

        Only updates fields that are provided (non-None).

        Returns:
            True if the update succeeded, False otherwise.
        """
        update_data: dict[str, Any] = {}
        if plan is not None:
            update_data["learningPlan"] = plan
        if progress is not None:
            update_data["progress"] = progress
        if short_term is not None:
            update_data["shortTermPlan"] = short_term

        if not update_data:
            return True  # nothing to update

        try:
            result = self.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data},
            )
            if result.modified_count > 0:
                logger.info(f"Plan data updated for user {user_id}: {list(update_data.keys())}")
            return True
        except Exception as e:
            logger.error(f"Failed to save plan data for user {user_id}: {e}")
            return False


# Singleton instance
plan_store = PlanStore()

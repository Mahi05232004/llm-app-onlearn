"""
MongoDB data access layer for the planning system.

Provides read/write access to the user document's planning fields,
stored under `user.modules.<module_id>.*`:
- learningPlan: The full weekly learning plan
- progress: Progress metrics (pace, completion %, streak)
- studentProfile: Student's onboarding data
- shortTermPlan: Current week + next 3 topics (for agent context)
- planStartedAt: When the student started learning

All access is module-aware: pass a `module` parameter to read/write
the correct module's data (e.g., 'dsa' or 'ds').
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

    def _get_prefix(self, module: str) -> str:
        """Return the field prefix for a module."""
        return f"modules.{module}"

    def get_plan_data(self, user_id: str, module: str = "dsa") -> dict[str, Any]:
        """Read all planning-related fields from the user document for a module.

        Returns:
            Dict with keys: learningPlan, progress, studentProfile,
            planStartedAt, shortTermPlan. Missing fields default to None.
        """
        prefix = self._get_prefix(module)
        try:
            user = self.users.find_one(
                {"_id": ObjectId(user_id)},
                {
                    f"{prefix}.learningPlan": 1,
                    f"{prefix}.progress": 1,
                    f"{prefix}.studentProfile": 1,
                    f"{prefix}.planStartedAt": 1,
                    f"{prefix}.shortTermPlan": 1,
                    f"{prefix}.planGenerationStatus": 1,
                    # Legacy fallback fields
                    "learningPlan": 1,
                    "progress": 1,
                    "studentProfile": 1,
                    "planStartedAt": 1,
                    "shortTermPlan": 1,
                    "planGenerationStatus": 1,
                },
            )
            if not user:
                logger.warning(f"User {user_id} not found in MongoDB")
                return {}

            # Prefer modules map, fall back to legacy flat fields
            mod_data = (user.get("modules") or {}).get(module, {})

            def _get(field: str) -> Any:
                """Get from modules map first, then legacy flat field."""
                val = mod_data.get(field)
                if val is not None:
                    return val
                # Only fall back for 'dsa' legacy fields
                if module == "dsa":
                    return user.get(field)
                return None

            return {
                "learningPlan": _get("learningPlan"),
                "progress": _get("progress"),
                "studentProfile": _get("studentProfile"),
                "planStartedAt": _get("planStartedAt"),
                "shortTermPlan": _get("shortTermPlan"),
                "planGenerationStatus": _get("planGenerationStatus"),
            }
        except Exception as e:
            logger.error(f"Failed to read plan data for user {user_id}: {e}")
            return {}

    def save_plan_data(
        self,
        user_id: str,
        module: str = "dsa",
        plan: dict | None = None,
        progress: dict | None = None,
        short_term: dict | None = None,
        status: str | None = None,
    ) -> bool:
        """Write updated plan data to the user document's modules map.

        Only updates fields that are provided (non-None).

        Returns:
            True if the update succeeded, False otherwise.
        """
        prefix = self._get_prefix(module)
        update_data: dict[str, Any] = {}
        if plan is not None:
            update_data[f"{prefix}.learningPlan"] = plan
        if progress is not None:
            update_data[f"{prefix}.progress"] = progress
        if short_term is not None:
            update_data[f"{prefix}.shortTermPlan"] = short_term
        if status is not None:
            update_data[f"{prefix}.planGenerationStatus"] = status

        if not update_data:
            return True  # nothing to update

        try:
            result = self.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data},
            )
            if result.modified_count > 0:
                logger.info(f"Plan data updated for user {user_id} (module={module}): {list(update_data.keys())}")
            return True
        except Exception as e:
            logger.error(f"Failed to save plan data for user {user_id}: {e}")
            return False


# Singleton instance
plan_store = PlanStore()

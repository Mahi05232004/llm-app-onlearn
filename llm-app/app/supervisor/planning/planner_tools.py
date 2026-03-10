"""
Tools for the internal Planner Agent.

These tools wrap PlanningService methods and are called by the Planner Agent
during plan updates. They operate on plan/profile data passed in via closure
from the planner runner — they do NOT access MongoDB directly.

The runner handles all MongoDB reads/writes; these tools are pure functions
over plan data.
"""

import json
import logging
import math
from datetime import datetime, UTC
from typing import Annotated, Any, Optional

from langchain_core.tools import tool

from app.models.plan_models import LearningPlan, StudentProfile, Progress
from app.supervisor.planning.service import PlanningService

logger = logging.getLogger(__name__)


def create_planner_tools(
    plan_data: dict[str, Any],
    planning_service: PlanningService,
) -> list:
    """Create planner tools with access to the current plan data.

    The plan_data dict is mutated in-place by the tools, so the runner
    can read the updated state after all tools have run.

    Args:
        plan_data: Mutable dict with keys: plan, profile, started_at, progress, short_term.
                   Updated in-place by tools.
        planning_service: The PlanningService instance.

    Returns:
        List of tools for the Planner Agent.
    """

    @tool
    def mark_topic_completed(
        question_id: Annotated[str, "The question_id of the completed topic, e.g. 'q_1_2_3'"],
        actual_minutes: Annotated[Optional[int], "How many minutes the student actually spent (optional)"] = None,
    ) -> str:
        """Mark a topic as completed and recalculate progress.

        Call this when the student has finished learning and coding a topic.
        This will:
        1. Mark the topic as 'completed' in the plan
        2. Run spillover for any past-due incomplete topics
        3. Recalculate progress metrics
        """
        plan = LearningPlan(**plan_data["plan"])
        profile = StudentProfile(**plan_data["profile"])
        started_at = plan_data["started_at"]

        updated_plan, progress = planning_service.complete_topic(
            plan, profile, question_id, started_at, actual_minutes
        )

        # Update shared state
        plan_data["plan"] = updated_plan.model_dump(mode="json")
        plan_data["progress"] = progress.model_dump(mode="json")

        return json.dumps({
            "status": "completed",
            "question_id": question_id,
            "completion_percentage": progress.completion_percentage,
            "pace_status": progress.pace_status.value,
            "pace_message": progress.pace_message,
            "completed_topics": progress.completed_topics,
            "total_topics": progress.total_topics,
        })

    @tool
    def absorb_off_plan_topic(
        question_id: Annotated[str, "The question_id of the off-plan topic the student is working on"],
    ) -> str:
        """Absorb a topic that's not in the current week's plan.

        Call this when the student starts working on a topic that isn't
        scheduled for their current week. The topic will be moved to
        or added to the current week.
        """
        plan = LearningPlan(**plan_data["plan"])
        profile = StudentProfile(**plan_data["profile"])
        started_at = plan_data["started_at"]

        updated_plan, progress = planning_service.handle_off_plan_topic(
            plan, profile, question_id, started_at
        )

        plan_data["plan"] = updated_plan.model_dump(mode="json")
        plan_data["progress"] = progress.model_dump(mode="json")

        return json.dumps({
            "status": "absorbed",
            "question_id": question_id,
            "message": f"Topic {question_id} has been added to the current week's plan.",
        })

    @tool
    def adjust_schedule(
        adjustment_type: Annotated[str, (
            "Type of schedule adjustment: "
            "'skip' (skip time period), "
            "'extend_deadline' (push target date forward), "
            "'compress' (try to fit more into current week)"
        )],
        amount: Annotated[int, (
            "Amount to adjust. For 'skip': number of days to skip (7 = one week, 14 = two weeks, 3 = three days). "
            "For 'extend_deadline': number of days to extend. "
            "For 'compress': ignored."
        )],
        reason: Annotated[str, "Brief reason for the adjustment, e.g. 'student is busy this week'"] = "",
    ) -> str:
        """Flexibly adjust the learning plan schedule.

        Handles various time-based adjustments:
        - Student says "I'm busy this week" → skip, 7 days
        - Student says "skip 3 days" → skip, 3 days
        - Student says "I need 2 more weeks" → extend_deadline, 14 days
        - Student says "I'm busy until Friday" → skip, calculated days

        The amount is always in DAYS for maximum flexibility.
        """
        plan = LearningPlan(**plan_data["plan"])
        profile = StudentProfile(**plan_data["profile"])
        started_at = plan_data["started_at"]

        if adjustment_type == "skip":
            # Convert days to weeks (round up) for the skip_week API
            weeks = max(1, math.ceil(amount / 7))
            updated_plan, progress = planning_service.skip_week(
                plan, profile, started_at, weeks_to_skip=weeks
            )
            message = f"Plan shifted forward by {weeks} week(s) ({amount} days). Reason: {reason}"

        elif adjustment_type == "extend_deadline":
            # For now, extending deadline means shifting the plan
            weeks = max(1, math.ceil(amount / 7))
            updated_plan, progress = planning_service.skip_week(
                plan, profile, started_at, weeks_to_skip=weeks
            )
            message = f"Deadline extended by {weeks} week(s) ({amount} days). Reason: {reason}"

        elif adjustment_type == "compress":
            # Compress: just recalculate progress (spillover handles the rest)
            updated_plan = plan
            progress = Progress.calculate(plan, profile, started_at)
            message = "Plan compressed — spillover topics moved to current week."

        else:
            return json.dumps({"status": "error", "message": f"Unknown adjustment type: {adjustment_type}"})

        plan_data["plan"] = updated_plan.model_dump(mode="json")
        plan_data["progress"] = progress.model_dump(mode="json")

        return json.dumps({
            "status": "adjusted",
            "adjustment_type": adjustment_type,
            "message": message,
            "estimated_completion": progress.estimated_completion.isoformat() if progress.estimated_completion else None,
        })

    @tool
    def get_short_term_summary() -> str:
        """Get the current week's focus and next upcoming topics.

        Returns the short-term plan: current focus area, weekly progress,
        and the next 5 incomplete topics across all weeks.

        Always call this at the end of any plan update to provide
        the Master Agent with the latest context.
        """
        plan = LearningPlan(**plan_data["plan"])
        summary = planning_service.get_short_term_summary(plan)

        # Store for persistence
        plan_data["short_term"] = summary

        return json.dumps(summary)

    @tool
    def get_current_progress() -> str:
        """Calculate and return the student's current progress metrics.

        Returns: completion percentage, pace status, topics completed,
        days remaining, estimated completion date.
        """
        plan = LearningPlan(**plan_data["plan"])
        profile = StudentProfile(**plan_data["profile"])
        started_at = plan_data["started_at"]

        progress = Progress.calculate(plan, profile, started_at)
        plan_data["progress"] = progress.model_dump(mode="json")

        return json.dumps({
            "completion_percentage": progress.completion_percentage,
            "completed_topics": progress.completed_topics,
            "total_topics": progress.total_topics,
            "pace_status": progress.pace_status.value,
            "pace_message": progress.pace_message,
            "days_remaining": progress.days_remaining,
            "estimated_completion": progress.estimated_completion.isoformat() if progress.estimated_completion else None,
        })

    return [
        mark_topic_completed,
        absorb_off_plan_topic,
        adjust_schedule,
        get_short_term_summary,
        get_current_progress,
    ]

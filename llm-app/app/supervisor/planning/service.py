"""
Planning Service — orchestrates the LLM planner + rule-based builder.

This is the main entry point for all planning operations:
- Initial plan generation (after onboarding)
- Progress updates (after topic completion)
- Off-plan topic handling
- Plan modifications (student says "I'm busy")
"""

import logging
import math
from datetime import datetime, UTC
from typing import Any, Optional

from app.models.plan_models import (
    StudentProfile,
    LearningPlan,
    Progress,
    TopicStatus,
)
from app.supervisor.planning.plan_builder import PlanBuilder
from app.supervisor.planning.planner_agent import generate_topic_ordering
from core.course_data import get_sidebar_data, get_question_by_id, get_questions

logger = logging.getLogger(__name__)


class PlanningService:
    """
    Main planning service that combines LLM intelligence with rule-based mechanics.

    Usage:
        service = PlanningService()
        plan, progress = await service.generate_initial_plan(profile)
        plan = service.complete_topic(plan, profile, "q_1_2_3")
    """

    def __init__(self):
        self.builder = PlanBuilder()

    async def generate_initial_plan(
        self,
        student_profile: StudentProfile,
        started_at: Optional[datetime] = None,
        feedback: Optional[str] = None,
        course_id: str = "dsa",
    ) -> tuple[LearningPlan, Progress]:
        """
        Generate the initial learning plan after onboarding.

        1. Calls the LLM planner to order topics intelligently
        2. Uses the rule-based builder to pack them into weeks
        3. Calculates initial progress

        Returns:
            Tuple of (LearningPlan, Progress)
        """
        if started_at is None:
            started_at = datetime.now(UTC)

        profile_dict = student_profile.model_dump()

        # Step 1: LLM orders topics
        logger.info("Generating topic ordering via planner agent...")

        # Calculate time budget for the planner
        now = datetime.now(UTC)
        target = student_profile.target_date
        if target.tzinfo is None:
            from datetime import timezone
            target = target.replace(tzinfo=timezone.utc)

        # If target_date is in the past, the LLM likely picked a stale date.
        # Recompute based on the intended duration from profile creation.
        days_until_target = (target - now).days
        if days_until_target <= 0:
            # Estimate original intent: if profile was created and target was set,
            # use the timeline field if available, otherwise default to 12 weeks
            # We can infer intent from the profile's goal timeline
            logger.warning(
                f"target_date {target.isoformat()} is in the past. "
                f"Recomputing from now."
            )
            # Check if there's a timeline hint in the profile
            profile_goal = student_profile.goal.lower() if student_profile.goal else ""
            # Default: 12 weeks (3 months) — most common student timeline
            estimated_weeks = 12

            # Try to extract duration from raw timeline field or goal
            import re
            # Check for timeline field on the profile (raw string like "4 weeks")
            timeline_raw = student_profile.timeline or profile_dict.get("timeline", "")

            fields_to_check = [timeline_raw, student_profile.goal, str(student_profile.target_date)]
            for field in fields_to_check:
                field_str = str(field)
                # Match "X weeks"
                weeks_match = re.search(r'(\d+)\s*weeks?', field_str, re.IGNORECASE)
                if weeks_match:
                    estimated_weeks = int(weeks_match.group(1))
                    break
                # Match "X months"
                months_match = re.search(r'(\d+)\s*months?', field_str, re.IGNORECASE)
                if months_match:
                    estimated_weeks = int(months_match.group(1)) * 4
                    break

            available_weeks = max(estimated_weeks, 4)
            logger.info(f"Using estimated timeline: {available_weeks} weeks")
        else:
            available_weeks = max(math.ceil(days_until_target / 7), 4)

        total_budget_minutes = available_weeks * student_profile.weekly_available_minutes

        logger.info(
            f"Time budget: {available_weeks} weeks, "
            f"{total_budget_minutes} total minutes "
            f"({student_profile.weekly_hours}h/week)"
        )

        planner_result = await generate_topic_ordering(
            profile_dict,
            feedback=feedback,
            available_weeks=available_weeks,
            total_budget_minutes=total_budget_minutes,
            course_id=course_id,
        )

        ordered_topic_ids = planner_result["ordered_topics"]
        focus_areas = planner_result["focus_areas"]

        logger.info(
            f"Planner returned {len(ordered_topic_ids)} topics, "
            f"{len(focus_areas)} focus areas. "
            f"Reasoning: {planner_result.get('reasoning', 'N/A')}"
        )

        # Step 2: Resolve topic IDs to full question data
        all_questions = get_questions(course_id=course_id)
        questions_by_id = {q["question_id"]: q for q in all_questions}

        ordered_questions = []
        for qid in ordered_topic_ids:
            if qid in questions_by_id:
                ordered_questions.append(questions_by_id[qid])
            else:
                logger.warning(f"Planner referenced unknown question: {qid}")

        # Step 3: Rule-based builder packs into weeks
        plan = self.builder.build_weekly_plan(
            ordered_topics=ordered_questions,
            focus_areas=focus_areas,
            weekly_available_minutes=student_profile.weekly_available_minutes,
            weekly_buffer_minutes=student_profile.weekly_buffer_minutes,
            start_date=started_at,
            max_weeks=available_weeks,
        )

        # Step 4: Calculate initial progress
        progress = Progress.calculate(plan, student_profile, started_at)

        logger.info(
            f"Initial plan: {plan.total_topics} topics, "
            f"{plan.total_weeks} weeks, "
            f"est. completion: {progress.estimated_completion}"
        )

        return plan, progress

    def complete_topic(
        self,
        plan: LearningPlan,
        profile: StudentProfile,
        question_id: str,
        started_at: datetime,
        actual_minutes: Optional[int] = None,
    ) -> tuple[LearningPlan, Progress]:
        """
        Mark a topic as completed and recalculate everything.

        Args:
            plan: Current learning plan
            profile: Student profile
            question_id: The completed question's ID
            started_at: When the student started learning
            actual_minutes: How long the student actually took

        Returns:
            Updated (LearningPlan, Progress)
        """
        # Mark topic done
        plan = self.builder.mark_topic_completed(plan, question_id, actual_minutes)

        # Spillover any past-due incomplete topics
        plan = self.builder.spillover_incomplete_topics(plan)

        # Recalculate progress
        progress = Progress.calculate(plan, profile, started_at)

        logger.info(
            f"Topic {question_id} completed. "
            f"Progress: {progress.completion_percentage}% "
            f"({progress.pace_status.value})"
        )

        return plan, progress

    def handle_off_plan_topic(
        self,
        plan: LearningPlan,
        profile: StudentProfile,
        question_id: str,
        started_at: datetime,
        course_id: str = "dsa",
    ) -> tuple[LearningPlan, Progress]:
        """
        Handle student starting a topic not in the current week.

        Only call this when the student has confirmed they're working
        on this topic (sent first message), not just browsing.

        Args:
            plan: Current learning plan
            profile: Student profile
            question_id: The off-plan question's ID
            started_at: When the student started learning

        Returns:
            Updated (LearningPlan, Progress)
        """
        # Get full question data
        question_data = get_question_by_id(question_id, course_id=course_id)
        if not question_data:
            logger.warning(f"Question {question_id} not found in curriculum")
            return plan, Progress.calculate(plan, profile, started_at)

        # Absorb into current week
        plan = self.builder.absorb_off_plan_topic(plan, question_id, question_data)

        # Recalculate progress
        progress = Progress.calculate(plan, profile, started_at)

        return plan, progress

    def skip_week(
        self,
        plan: LearningPlan,
        profile: StudentProfile,
        started_at: datetime,
        weeks_to_skip: int = 1,
    ) -> tuple[LearningPlan, Progress]:
        """
        Student is busy — shift the plan forward.

        Args:
            plan: Current learning plan
            profile: Student profile
            started_at: When the student started learning
            weeks_to_skip: Number of weeks to push forward

        Returns:
            Updated (LearningPlan, Progress)
        """
        plan = self.builder.shift_plan(plan, skip_weeks=weeks_to_skip)
        progress = Progress.calculate(plan, profile, started_at)

        logger.info(
            f"Plan shifted by {weeks_to_skip} weeks. "
            f"New estimated completion: {progress.estimated_completion}"
        )

        return plan, progress

    def get_short_term_summary(self, plan: LearningPlan) -> dict[str, Any]:
        """
        Get a short-term summary for the master agent to reference.

        Returns current week info and next 3 topics.
        """
        current_week = plan.get_current_week()
        if not current_week:
            return {"current_focus": "No active week", "next_topics": []}

        # Next incomplete topics across all weeks
        next_topics = []
        for week in plan.weeks:
            for topic in week.topics:
                if topic.status != TopicStatus.COMPLETED:
                    next_topics.append({
                        "question_id": topic.question_id,
                        "title": topic.title,
                        "difficulty": topic.difficulty,
                        "estimated_minutes": topic.estimated_minutes,
                        "week": week.week_number,
                    })
                    if len(next_topics) >= 5:
                        break
            if len(next_topics) >= 5:
                break

        return {
            "current_week": current_week.week_number,
            "current_focus": current_week.focus_area,
            "week_progress": f"{current_week.completed_topics}/{len(current_week.topics)} topics done",
            "next_topics": next_topics,
        }

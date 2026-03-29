"""
Rule-based plan builder.

Handles the deterministic parts of plan generation:
- Assigning topics to weeks based on time budgets
- Spillover logic for unfinished topics
- Off-plan topic absorption
- Plan rebalancing after updates
"""

from datetime import datetime, timedelta, UTC
from typing import Optional
import logging

from app.models.plan_models import (
    PlannedTopic,
    WeekPlan,
    WeekStatus,
    LearningPlan,
    TopicStatus,
    BUFFER_PERCENT,
)

logger = logging.getLogger(__name__)


class PlanBuilder:
    """Rule-based plan builder that assigns topics to weeks."""

    @staticmethod
    def build_weekly_plan(
        ordered_topics: list[dict],
        focus_areas: list[dict],
        weekly_available_minutes: int,
        weekly_buffer_minutes: int,
        start_date: datetime,
        max_weeks: int | None = None,
    ) -> LearningPlan:
        """
        Take an LLM-ordered list of topics and pack them into weeks.

        Args:
            ordered_topics: List of question dicts ordered by the planner agent.
                            Each must have: question_id, question_title/title, difficulty
            focus_areas: List of {topics: [question_ids], label: str} from planner
            weekly_available_minutes: Usable minutes per week (after buffer)
            weekly_buffer_minutes: Buffer minutes per week
            start_date: When the student starts learning

        Returns:
            A complete LearningPlan with topics assigned to weeks
        """
        # Build a lookup for focus area labels by question_id
        topic_focus_map: dict[str, str] = {}
        for area in focus_areas:
            for qid in area.get("topics", []):
                topic_focus_map[qid] = area.get("label", "General")

        # Convert raw question dicts to PlannedTopic objects
        planned_topics = [PlannedTopic.from_question(q) for q in ordered_topics]

        # Pack topics into weeks
        weeks: list[WeekPlan] = []
        current_week_topics: list[PlannedTopic] = []
        current_week_minutes = 0
        week_number = 1

        for topic in planned_topics:
            # Check if adding this topic exceeds the weekly budget
            if (current_week_minutes + topic.estimated_minutes > weekly_available_minutes
                    and current_week_topics):
                # Close current week
                week_start = start_date + timedelta(weeks=week_number - 1)
                week_end = week_start + timedelta(days=6, hours=23, minutes=59)

                # Determine focus area for this week (most common among topics)
                focus_counts: dict[str, int] = {}
                for t in current_week_topics:
                    area = topic_focus_map.get(t.question_id, "General")
                    focus_counts[area] = focus_counts.get(area, 0) + 1
                focus_area = max(focus_counts, key=focus_counts.get) if focus_counts else "General"

                weeks.append(WeekPlan(
                    week_number=week_number,
                    start_date=week_start,
                    end_date=week_end,
                    focus_area=focus_area,
                    planned_minutes=weekly_available_minutes,
                    buffer_minutes=weekly_buffer_minutes,
                    topics=current_week_topics,
                ))

                # Start next week
                week_number += 1
                current_week_topics = []
                current_week_minutes = 0

            current_week_topics.append(topic)
            current_week_minutes += topic.estimated_minutes

            # Safety: cap at max_weeks if specified
            if max_weeks and week_number > max_weeks:
                remaining = len(planned_topics) - (planned_topics.index(topic) + 1)
                if remaining > 0:
                    logger.warning(
                        f"Deadline cap reached at week {max_weeks}. "
                        f"Dropping {remaining} remaining topics."
                    )
                break

        # Don't forget the last partial week
        if current_week_topics:
            week_start = start_date + timedelta(weeks=week_number - 1)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59)

            focus_counts = {}
            for t in current_week_topics:
                area = topic_focus_map.get(t.question_id, "General")
                focus_counts[area] = focus_counts.get(area, 0) + 1
            focus_area = max(focus_counts, key=focus_counts.get) if focus_counts else "General"

            weeks.append(WeekPlan(
                week_number=week_number,
                start_date=week_start,
                end_date=week_end,
                focus_area=focus_area,
                planned_minutes=weekly_available_minutes,
                buffer_minutes=weekly_buffer_minutes,
                topics=current_week_topics,
            ))

        plan = LearningPlan(
            weeks=weeks,
            total_topics=len(planned_topics),
            plan_version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        logger.info(
            f"Built plan: {plan.total_topics} topics across {plan.total_weeks} weeks"
        )
        return plan

    @staticmethod
    def spillover_incomplete_topics(plan: LearningPlan) -> LearningPlan:
        """
        Move incomplete topics from past weeks to the current week.

        Called during progress updates. If a week has ended but has
        incomplete topics, those spill into the current/next active week.
        """
        now = datetime.now(UTC)
        current_week = plan.get_current_week()
        if not current_week:
            return plan

        for week in plan.weeks:
            if week.week_number >= current_week.week_number:
                break

            # Find incomplete topics in past weeks
            incomplete = [
                t for t in week.topics
                if t.status != TopicStatus.COMPLETED
            ]

            if incomplete:
                # Move them to current week
                for topic in incomplete:
                    week.topics.remove(topic)
                    current_week.topics.append(topic)

                # Mark past week as completed (all remaining work moved)
                if not week.topics or all(
                    t.status == TopicStatus.COMPLETED for t in week.topics
                ):
                    week.status = WeekStatus.COMPLETED

                logger.info(
                    f"Spilled {len(incomplete)} topics from week {week.week_number} "
                    f"to week {current_week.week_number}"
                )

        plan.updated_at = datetime.now(UTC)
        return plan

    @staticmethod
    def absorb_off_plan_topic(
        plan: LearningPlan,
        question_id: str,
        question_data: dict,
    ) -> LearningPlan:
        """
        Handle a student starting a topic that's not in the current week.

        If the topic exists in a future week, move it to current week.
        If it's not in the plan at all, add it to current week.
        """
        current_week = plan.get_current_week()
        if not current_week:
            logger.warning("No current week found, cannot absorb off-plan topic")
            return plan

        # Check if topic is already in current week
        for topic in current_week.topics:
            if topic.question_id == question_id:
                return plan  # Already here, nothing to do

        # Check if topic exists in a future week
        planned_week, planned_topic = plan.find_topic(question_id)

        if planned_topic and planned_week:
            # Remove from planned week
            planned_week.topics.remove(planned_topic)
            # Add to current week
            planned_topic.status = TopicStatus.IN_PROGRESS
            current_week.topics.append(planned_topic)
            logger.info(
                f"Moved topic {question_id} from week {planned_week.week_number} "
                f"to current week {current_week.week_number}"
            )
        else:
            # Topic not in plan at all — add it
            new_topic = PlannedTopic.from_question(question_data)
            new_topic.status = TopicStatus.IN_PROGRESS
            current_week.topics.append(new_topic)
            plan.total_topics += 1
            logger.info(f"Added new off-plan topic {question_id} to current week")

        plan.updated_at = datetime.now(UTC)
        plan.plan_version += 1
        return plan

    @staticmethod
    def shift_plan(
        plan: LearningPlan,
        skip_weeks: int = 1,
    ) -> LearningPlan:
        """
        Shift all future weeks forward by `skip_weeks` weeks.

        Used when student says "I'm busy this week" — pushes
        everything back while keeping completed topics in place.
        """
        now = datetime.now(UTC)

        for week in plan.weeks:
            # Only shift future/current incomplete weeks
            if week.end_date > now and week.status != WeekStatus.COMPLETED:
                week.start_date += timedelta(weeks=skip_weeks)
                week.end_date += timedelta(weeks=skip_weeks)
                week.week_number += skip_weeks

        plan.updated_at = datetime.now(UTC)
        plan.plan_version += 1

        logger.info(f"Shifted plan by {skip_weeks} weeks")
        return plan

    @staticmethod
    def mark_topic_completed(
        plan: LearningPlan,
        question_id: str,
        actual_minutes: Optional[int] = None,
    ) -> LearningPlan:
        """Mark a topic as completed and update week status."""
        week, topic = plan.find_topic(question_id)

        if not topic or not week:
            logger.warning(f"Topic {question_id} not found in plan")
            return plan

        topic.status = TopicStatus.COMPLETED
        topic.completed_at = datetime.now(UTC)
        if actual_minutes is not None:
            topic.actual_minutes = actual_minutes

        # Check if all topics in the week are done
        if all(t.status == TopicStatus.COMPLETED for t in week.topics):
            week.status = WeekStatus.COMPLETED

        plan.updated_at = datetime.now(UTC)
        return plan

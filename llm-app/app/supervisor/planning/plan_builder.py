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


import uuid
from itertools import groupby

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

        def close_week(
            week_num: int,
            week_topics: list[PlannedTopic],
            start: datetime,
            end: datetime,
            total_capacity: int,
            buffer: int
        ):
            """Helper to create one or more week parts from a list of topics."""
            if not week_topics:
                return

            # Group by focus area (preserving order) to create parts
            # e.g. [A, A, B, A] -> [Part 1: A, Part 2: B, Part 3: A]
            grouped_parts = []
            for focus, group in groupby(week_topics, key=lambda t: topic_focus_map.get(t.question_id, "General")):
                grouped_parts.append((focus, list(group)))

            part_num = 1
            for focus_area, topics_in_part in grouped_parts:
                # Calculate planned minutes just for this part
                part_minutes = sum(t.estimated_minutes for t in topics_in_part)
                
                weeks.append(WeekPlan(
                    id=str(uuid.uuid4()),
                    week_number=week_num,
                    week_part=part_num,
                    start_date=start,
                    end_date=end,
                    focus_area=focus_area,
                    planned_minutes=part_minutes,  # Set to actual usage, not total capacity
                    buffer_minutes=buffer if part_num == 1 else 0, # Assign buffer only to first part roughly
                    topics=topics_in_part,
                ))
                part_num += 1

        for topic in planned_topics:
            # Check if adding this topic exceeds the weekly budget
            if (current_week_minutes + topic.estimated_minutes > weekly_available_minutes
                    and current_week_topics):
                # Close current week
                week_start = start_date + timedelta(weeks=week_number - 1)
                week_end = week_start + timedelta(days=6, hours=23, minutes=59)

                close_week(
                    week_number, 
                    current_week_topics, 
                    week_start, 
                    week_end, 
                    weekly_available_minutes, 
                    weekly_buffer_minutes
                )

                # Start next week
                week_number += 1
                current_week_topics = []
                current_week_minutes = 0

            current_week_topics.append(topic)
            current_week_minutes += topic.estimated_minutes

            # Safety: cap at max_weeks if specified
            if max_weeks and week_number > max_weeks:
                # ... (snippet truncated logging)
                # For brevity ensuring we don't break logic, just standard break
                break

        # Don't forget the last partial week
        if current_week_topics:
            week_start = start_date + timedelta(weeks=week_number - 1)
            week_end = week_start + timedelta(days=6, hours=23, minutes=59)
            
            close_week(
                week_number,
                current_week_topics,
                week_start,
                week_end,
                weekly_available_minutes,
                weekly_buffer_minutes
            )

        plan = LearningPlan(
            weeks=weeks,
            total_topics=len(planned_topics),
            plan_version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        logger.info(
            f"Built plan: {plan.total_topics} topics across {plan.total_weeks} week-parts"
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

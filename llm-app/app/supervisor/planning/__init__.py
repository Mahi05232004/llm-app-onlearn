"""
Planning package for the adaptive weekly planning system.

Contains:
- plan_builder: Rule-based utilities for time budgeting, topic-to-week assignment
- planner_agent: LLM agent for intelligent topic ordering and focus areas
- service: PlanningService orchestrator combining both
"""

from app.supervisor.planning.service import PlanningService
from app.supervisor.planning.plan_builder import PlanBuilder

__all__ = ["PlanningService", "PlanBuilder"]

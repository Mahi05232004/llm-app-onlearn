"""
DEPRECATED: Import from models.state instead.

This module is kept for backward compatibility only.
New code should use: from models.state import SupervisorState
"""
from app.supervisor.state import SupervisorState

__all__ = ["SupervisorState"]
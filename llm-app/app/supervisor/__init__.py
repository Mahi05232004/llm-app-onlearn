"""
Supervisor module for AI teaching agents using deepagents architecture.

This package provides the handoff-based orchestrator for interactive learning.

Structure:
- orchestrator.py: Main entry point (compiled graph singleton)
- config/: Runtime configuration (model, checkpointer)
- prompts/: System prompts for each agent
- agents/: Agent creation and node implementations
- graph/: State definition, routing, and graph building
- tools/: Available tools (course, handoff, execute)

Usage:
    from app.supervisor.orchestrator import orchestrator
    
    result = await orchestrator.ainvoke(inputs, config=config)
"""

# Note: We don't eagerly import orchestrator here to avoid circular imports.
# Use direct imports: from app.supervisor.orchestrator import orchestrator

__all__ = ["orchestrator", "master_orchestrator"]


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name in ("orchestrator", "master_orchestrator"):
        from .orchestrator import orchestrator, master_orchestrator
        if name == "orchestrator":
            return orchestrator
        return master_orchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""
Module registry — maps module_id → ModuleConfig.

A ModuleConfig bundles everything that varies per learning module:
prompts, course data path, thread prefix, etc.  Adding a new module
only requires creating a new config file that calls register_module().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleConfig:
    """Immutable configuration for a learning module."""

    module_id: str
    """Unique identifier, e.g. 'dsa', 'ds'. Must match the course_id in data/courses/."""

    name: str
    """Human-readable name, e.g. 'Data Structures & Algorithms'."""

    course_id: str
    """Maps to data/courses/{course_id}/questions.json."""

    onboarding_prompt: str
    """Full system prompt for the onboarding agent when this module is active."""

    planner_prompt: str
    """Full system prompt for the planner agent when generating plans for this module."""

    thread_prefix: str
    """Prefix for LangGraph thread IDs: {thread_prefix}_{user_id}."""

    icon: str = ""
    """Emoji icon for UI display."""

    description: str = ""
    """Short description for the module selection UI."""

    # Future extensibility: add fields for module-specific tutor prompts,
    # tools, code execution runtimes, etc.
    extra: dict = field(default_factory=dict)
    """Arbitrary extra config for module-specific needs."""


# ── Global registry ──────────────────────────────────────────────────

_MODULES: dict[str, ModuleConfig] = {}


def register_module(config: ModuleConfig) -> None:
    """Register a module configuration.

    Args:
        config: The module configuration to register.

    Raises:
        ValueError: If a module with the same module_id is already registered.
    """
    if config.module_id in _MODULES:
        logger.warning(
            "Module '%s' already registered — skipping duplicate registration.",
            config.module_id,
        )
        return
    _MODULES[config.module_id] = config
    logger.info("Registered module: %s (%s)", config.module_id, config.name)


def get_module(module_id: str) -> ModuleConfig:
    """Retrieve a registered module configuration.

    Args:
        module_id: The unique module identifier.

    Returns:
        The ModuleConfig for the given module_id.

    Raises:
        ValueError: If the module_id is not registered.
    """
    if module_id not in _MODULES:
        available = ", ".join(_MODULES.keys()) or "(none)"
        raise ValueError(
            f"Unknown module '{module_id}'. Available modules: {available}"
        )
    return _MODULES[module_id]


def get_all_modules() -> list[ModuleConfig]:
    """Return all registered module configurations."""
    return list(_MODULES.values())

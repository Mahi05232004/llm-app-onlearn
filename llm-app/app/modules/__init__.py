"""
Module Registry — central configuration for all learning modules.

Each module (DSA, Data Science, etc.) registers a ModuleConfig that
provides module-specific prompts, course IDs, and thread prefixes.

Usage:
    from app.modules import get_module, get_all_modules

    config = get_module("dsa")
    print(config.onboarding_prompt)
"""

from app.modules.registry import (
    ModuleConfig,
    register_module,
    get_module,
    get_all_modules,
)

# Auto-register all built-in modules on import
import app.modules.dsa  # noqa: F401
import app.modules.ds   # noqa: F401

__all__ = ["ModuleConfig", "register_module", "get_module", "get_all_modules"]

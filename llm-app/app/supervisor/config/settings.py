"""Configuration settings for the supervisor orchestrator."""

from app.clients.llm_client import GeminiClient
from core.checkpointer import get_checkpointer as _get_checkpointer

# Cached singleton — avoid re-creating the client on every call
_client: GeminiClient | None = None


def _get_client() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


def get_model(model_type: str = "pro"):
    """Get the configured LLM model."""
    return _get_client().get_model(model_type=model_type)


def get_onboarding_model():
    """Get the flash model for the lightweight onboarding agent."""
    return _get_client().get_model(model_type="flash")


def get_checkpointer():
    """Get the configured checkpointer for state persistence."""
    return _get_checkpointer()

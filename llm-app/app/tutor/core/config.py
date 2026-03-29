"""Configuration settings for the Tutor agent."""

from app.clients.llm_client import AzureLLMClient
from core.checkpointer import get_checkpointer as _get_checkpointer

# Cached singleton to avoid re-initializing the client
_client: AzureLLMClient | None = None

def _get_client() -> AzureLLMClient:
    global _client
    if _client is None:
        _client = AzureLLMClient()
    return _client

def get_tutor_model(model_type: str = "flash", **kwargs):
    """Get the configured LLM for Main Chat & Onboarding (Kimi K2.5 via Azure AI)."""
    return _get_client().get_model(model_type=model_type, max_retries=1, **kwargs)

def get_planner_model(model_type: str = "pro", **kwargs):
    """Get the configured LLM for curriculum planning (Kimi K2.5 via Azure AI)."""
    return _get_client().get_model(model_type=model_type, max_retries=1, **kwargs)

def get_tutor_checkpointer():
    """Get the configured checkpointer for chat history persistence."""
    # We reuse the core checkpointer which handles MongoDB persistence
    return _get_checkpointer()

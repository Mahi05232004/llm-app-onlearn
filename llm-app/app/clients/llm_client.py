"""
Azure AI LLM Client — unified access to Azure AI Services models.

Uses ChatOpenAI for chat models via the Azure AI Inference endpoint
(/models/chat/completions), and AzureOpenAIEmbeddings for embeddings
via the standard Azure OpenAI deployment endpoint.

See config/settings.py for all configurable env vars.
"""

import logging
import os

from langchain_openai import ChatOpenAI, AzureOpenAIEmbeddings

from config.settings import llm_config

logger = logging.getLogger(__name__)


# ── Patch: forward reasoning_content into additional_kwargs ──────────────
# LangChain's ChatOpenAI (v1.1.7) ignores delta.reasoning_content, which
# models like Kimi K2.5, DeepSeek, and Grok use for chain-of-thought tokens.
# We wrap the internal _convert_delta_to_message_chunk so it preserves
# reasoning_content, making it available to our SSE streaming code.
try:
    import langchain_openai.chat_models.base as _oai_base

    _original_convert_delta = _oai_base._convert_delta_to_message_chunk

    def _patched_convert_delta(delta, default_class):
        chunk = _original_convert_delta(delta, default_class)
        # Inject reasoning_content if present in the raw delta
        reasoning = delta.get("reasoning_content")
        if reasoning and hasattr(chunk, "additional_kwargs"):
            chunk.additional_kwargs["reasoning_content"] = reasoning
        return chunk

    _oai_base._convert_delta_to_message_chunk = _patched_convert_delta
    logger.debug("Patched _convert_delta_to_message_chunk for reasoning_content support")
except Exception as _patch_err:
    logger.warning(f"Could not patch reasoning_content support: {_patch_err}")
# ────────────────────────────────────────────────────────────────────────


class AzureLLMClient:
    """Single entry point for all Azure AI LLM and embedding model access."""

    def __init__(self):
        self._api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        self._endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        self._api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

        # Embeddings may live on a separate Azure resource
        self._embedding_endpoint = os.environ.get("AZURE_OPENAI_EMBEDDING_ENDPOINT", self._endpoint)
        self._embedding_api_key = os.environ.get("AZURE_OPENAI_EMBEDDING_API_KEY", self._api_key)

        if not self._api_key or not self._endpoint:
            raise ValueError("Azure OpenAI environment variables are not fully set.")
        logger.info("Initializing AzureLLMClient with Azure AI Inference backend")

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def get_model(self, model_type: str = "default", **kwargs) -> ChatOpenAI:
        """Get a configured chat model instance (Azure AI Inference endpoint)."""
        deployment_name = self._resolve_model_name(model_type)

        # Azure AI Inference uses /models as the base path
        base_url = f"{self._endpoint.rstrip('/')}/models"

        model_args = {
            "model": deployment_name,
            "base_url": base_url,
            "api_key": self._api_key,
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens,
            "streaming": True,
            "default_headers": {
                "extra-parameters": "ignore",
            },
        }
        model_args.update(kwargs)
        logger.debug(f"Creating model: {deployment_name} (backend=azure_ai_inference, base_url={base_url})")
        return ChatOpenAI(**model_args)

    def get_model_with_fallback(self, model_type: str = "default", **kwargs) -> ChatOpenAI:
        """Get a chat model with automatic fallback."""
        primary = self.get_model(model_type=model_type, max_retries=1, **kwargs)
        fallback_name = llm_config.fallback_model

        if fallback_name and fallback_name != self._resolve_model_name(model_type):
            fallback = self.get_model(model_type=fallback_name, max_retries=2, **kwargs)
            logger.info(
                f"Fallback enabled: {self._resolve_model_name(model_type)} -> {fallback_name}"
            )
            return primary.with_fallbacks([fallback])

        return primary

    def get_embedding_model(self) -> AzureOpenAIEmbeddings:
        """Get a configured embedding model instance (stays on Azure OpenAI deployment endpoint)."""
        return AzureOpenAIEmbeddings(
            azure_deployment=llm_config.embedding_model,
            api_version=self._api_version,
            azure_endpoint=self._embedding_endpoint,
            api_key=self._embedding_api_key,
        )

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _resolve_model_name(self, model_type: str) -> str:
        """Map model_type shorthand to actual model name."""
        model_map = {
            "pro": llm_config.pro_model,
            "flash": llm_config.flash_model,
            "default": llm_config.model,
        }
        return model_map.get(model_type, model_type)

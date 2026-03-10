"""
Gemini LLM Client — unified access to Google Gemini models.

Auth is controlled by a single env var:
    LLM_BACKEND=api_key    → uses GOOGLE_API_KEY (Gemini Developer API)
    LLM_BACKEND=vertex_ai  → uses GOOGLE_APPLICATION_CREDENTIALS (GCP Service Account)

See config/settings.py for all configurable env vars.
"""

import logging
import os

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from google.oauth2.service_account import Credentials

from config.settings import llm_config

logger = logging.getLogger(__name__)


class GeminiClient:
    """Single entry point for all Gemini LLM and embedding model access."""

    def __init__(self):
        logger.info(f"Initializing GeminiClient with backend: {llm_config.backend}")

        if llm_config.backend == "vertex_ai":
            self._init_vertex_ai()
        else:
            self._init_api_key()

    # ------------------------------------------------------------------ #
    #  Auth initialization
    # ------------------------------------------------------------------ #

    def _init_vertex_ai(self):
        """Set up Vertex AI auth using GCP Service Account."""
        creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        self._credentials = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self._project = llm_config.gcp_project
        self._auth_kwargs = {
            "credentials": self._credentials,
            "project": self._project,
            "vertexai": True,
            "location": "global"
        }
        logger.info(f"Vertex AI backend ready (project={self._project})")

    def _init_api_key(self):
        """Set up Gemini Developer API auth using API key."""
        self._credentials = None
        self._project = None
        self._auth_kwargs = {
            "api_key": llm_config.api_key,
        }
        logger.info("Gemini Developer API backend ready")

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def get_model(self, model_type: str = "pro", **kwargs) -> ChatGoogleGenerativeAI:
        """Get a configured chat model instance.

        Args:
            model_type: "pro", "flash", or a specific model name.
            **kwargs: Override any model constructor args.
        """
        model_name = self._resolve_model_name(model_type)

        model_args = {
            "model": model_name,
            "temperature": llm_config.temperature,
            "streaming": True,
            **self._auth_kwargs,
        }

        # Enable thinking for reasoning models
        if "pro" in model_name or "thinking" in model_name:
            model_args["include_thoughts"] = True

        # Caller overrides take priority
        model_args.update(kwargs)

        logger.debug(f"Creating model: {model_name} (backend={llm_config.backend})")
        return ChatGoogleGenerativeAI(**model_args)

    def get_embedding_model(self) -> GoogleGenerativeAIEmbeddings:
        """Get a configured embedding model instance."""
        # Embeddings use the same auth backend as chat models
        if llm_config.backend == "vertex_ai":
            return GoogleGenerativeAIEmbeddings(
                model=llm_config.embedding_model,
                credentials=self._credentials,
                project=self._project,
            )
        else:
            return GoogleGenerativeAIEmbeddings(
                model=llm_config.embedding_model,
                google_api_key=llm_config.api_key,
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

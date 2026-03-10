# config/settings.py
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class CourseDataConfig:
    """Configuration for JSON-based course data."""
    base_path: str = os.getenv("COURSE_DATA_PATH", "/data/courses")
    
    @property
    def index_path(self) -> str:
        return os.path.join(self.base_path, "index.json")
    
    def get_course_path(self, course_id: str) -> str:
        return os.path.join(self.base_path, course_id, "questions.json")


@dataclass
class AppConfig:
    data_file_path: str = os.getenv("DATA_FILE", "data/dsa_data_with_embedding.json")
    log_level: str = os.getenv("LOG_LEVEL", "DEBUG")
    max_recommendations: int = int(os.getenv("MAX_RECOMMENDATIONS", "20"))


class LLMConfig:
    """LLM configuration with explicit backend selection.
    
    Set LLM_BACKEND env var to control auth:
      - "vertex_ai" → uses GCP Service Account (GOOGLE_APPLICATION_CREDENTIALS)
      - "api_key"   → uses Gemini Developer API (GOOGLE_API_KEY)
    """

    # --- Auth ---
    backend: str = os.getenv("LLM_BACKEND", "api_key")  # "vertex_ai" or "api_key"
    api_key: str | None = os.getenv("GOOGLE_API_KEY")
    gcp_project: str | None = os.getenv("GOOGLE_CLOUD_PROJECT")

    # --- Models ---
    model: str = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    pro_model: str = os.getenv("GEMINI_PRO_MODEL", "gemini-3-flash-preview")
    flash_model: str = os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")
    embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-exp-03-07")

    # --- Generation ---
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "1"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))

    def validate(self):
        """Fail fast if required env vars are missing for the chosen backend."""
        if self.backend not in ("vertex_ai", "api_key"):
            raise ValueError(
                f"LLM_BACKEND must be 'vertex_ai' or 'api_key', got '{self.backend}'"
            )
        if self.backend == "api_key" and not self.api_key:
            raise ValueError(
                "LLM_BACKEND=api_key but GOOGLE_API_KEY is not set"
            )
        if self.backend == "vertex_ai" and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            raise ValueError(
                "LLM_BACKEND=vertex_ai but GOOGLE_APPLICATION_CREDENTIALS is not set"
            )


# Global config instances
course_config = CourseDataConfig()
app_config = AppConfig()
llm_config = LLMConfig()
llm_config.validate()

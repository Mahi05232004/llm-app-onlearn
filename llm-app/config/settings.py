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
    """LLM configuration with Azure AI Services (OpenAI-compatible endpoint)."""

    # --- Models ---
    model: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "Kimi-K2.5")
    pro_model: str = os.getenv("AZURE_OPENAI_PRO_DEPLOYMENT", "Kimi-K2.5")
    flash_model: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "Kimi-K2.5")
    fallback_model: str = os.getenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "grok-4-fast-reasoning")
    embedding_model: str = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

    # --- Generation ---
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "1"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))

    def validate(self):
        """Fail fast if critical config is missing."""
        if not os.getenv("AZURE_OPENAI_API_KEY"):
            pass


# Global config instances
course_config = CourseDataConfig()
app_config = AppConfig()
llm_config = LLMConfig()
llm_config.validate()

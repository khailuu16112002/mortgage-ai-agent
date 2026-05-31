"""
Central configuration for Mortgage Verification System.
All settings come from environment variables with sensible defaults.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Optional


class DatabaseSettings(BaseSettings):
    url: str = Field(default="sqlite:///./mortgage.db", alias="DATABASE_URL")
    echo: bool = Field(default=False, alias="DATABASE_ECHO")
    pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")

    class Config:
        env_file = ".env"
        extra = "ignore"


class LLMSettings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    default_model: str = Field(default="gpt-4o", alias="LLM_MODEL")
    max_tokens: int = Field(default=1500, alias="LLM_MAX_TOKENS")
    temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class ChunkingSettings(BaseSettings):
    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=150, alias="CHUNK_OVERLAP")
    min_chunk_length: int = Field(default=50, alias="MIN_CHUNK_LENGTH")
    max_chunks_per_doc: int = Field(default=100, alias="MAX_CHUNKS_PER_DOC")
    use_semantic_chunking: bool = Field(default=False, alias="USE_SEMANTIC_CHUNKING")

    class Config:
        env_file = ".env"
        extra = "ignore"


class ONNXSettings(BaseSettings):
    enabled: bool = Field(default=False, alias="ONNX_ENABLED")
    model_dir: str = Field(default="./models/onnx", alias="ONNX_MODEL_DIR")
    use_cuda: bool = Field(default=False, alias="ONNX_USE_CUDA")
    ner_model: str = Field(default="dslim/bert-base-NER", alias="ONNX_NER_MODEL")
    classifier_model: str = Field(default="facebook/bart-large-mnli", alias="ONNX_CLASSIFIER_MODEL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class APISettings(BaseSettings):
    host: str = Field(default="0.0.0.0", alias="API_HOST")
    port: int = Field(default=8000, alias="API_PORT")
    debug: bool = Field(default=True, alias="API_DEBUG")
    secret_key: str = Field(default="dev-secret-key-change-in-prod", alias="SECRET_KEY")
    upload_dir: str = Field(default="./uploads", alias="UPLOAD_DIR")
    max_upload_size_mb: int = Field(default=100, alias="MAX_UPLOAD_SIZE_MB")
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:8501"], alias="CORS_ORIGINS")

    class Config:
        env_file = ".env"
        extra = "ignore"


class LoggingSettings(BaseSettings):
    level: str = Field(default="INFO", alias="LOG_LEVEL")
    format: str = Field(default="json", alias="LOG_FORMAT")  # json | text
    file: Optional[str] = Field(default=None, alias="LOG_FILE")

    class Config:
        env_file = ".env"
        extra = "ignore"


class Settings(BaseSettings):
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    onnx: ONNXSettings = Field(default_factory=ONNXSettings)
    api: APISettings = Field(default_factory=APISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"

    class Config:
        env_file = ".env"
        extra = "ignore"


# Singleton
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the AI microservice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Tech-Doc-Intelligence AI Service"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    collection_name: str = Field(default="tech_docs", alias="COLLECTION_NAME")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    embedding_model: str = Field(default="all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=384, alias="EMBEDDING_DIMENSION")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.2", alias="OLLAMA_MODEL")

    chunk_size: int = Field(default=500, ge=100, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=50, ge=0, alias="CHUNK_OVERLAP")
    default_top_k: int = Field(default=3, ge=1, le=20, alias="DEFAULT_TOP_K")

    hybrid_dense_top_k: int = Field(default=20, ge=5, le=100, alias="HYBRID_DENSE_TOP_K")
    hybrid_bm25_top_k: int = Field(default=20, ge=5, le=100, alias="HYBRID_BM25_TOP_K")
    hybrid_dense_weight: float = Field(default=0.6, ge=0.0, le=1.0, alias="HYBRID_DENSE_WEIGHT")
    hybrid_bm25_weight: float = Field(default=0.4, ge=0.0, le=1.0, alias="HYBRID_BM25_WEIGHT")

    rerank_candidates: int = Field(default=10, ge=3, le=50, alias="RERANK_CANDIDATES")
    rerank_top_n: int = Field(default=3, ge=1, le=10, alias="RERANK_TOP_N")
    cross_encoder_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        alias="CROSS_ENCODER_MODEL",
    )
    enable_rerank: bool = Field(default=True, alias="ENABLE_RERANK")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="techdoc", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="techdoc_dev_password", alias="POSTGRES_PASSWORD")

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")
    semantic_cache_enabled: bool = Field(default=True, alias="SEMANTIC_CACHE_ENABLED")
    semantic_cache_ttl_seconds: int = Field(default=3600, ge=60, alias="SEMANTIC_CACHE_TTL_SECONDS")
    semantic_cache_similarity_threshold: float = Field(
        default=0.92,
        ge=0.5,
        le=1.0,
        alias="SEMANTIC_CACHE_SIMILARITY_THRESHOLD",
    )
    session_memory_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        alias="SESSION_MEMORY_TTL_SECONDS",
    )
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=30, ge=1, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, ge=1, alias="RATE_LIMIT_WINDOW_SECONDS")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

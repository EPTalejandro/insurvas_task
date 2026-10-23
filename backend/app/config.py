from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    # Comma-separated list, e.g. "http://localhost:5173,http://127.0.0.1:5173"
    cors_origins: str = "http://localhost:5173"

    # API credentials. An empty value disables that platform's collector.
    youtube_api_key: str = ""
    meta_graph_version: str = ""
    ig_user_id: str = ""
    ig_access_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = ""
    # Comma-separated subreddits to search; empty = search all of Reddit.
    reddit_subreddits: str = ""

    # Gemini labeling. An empty key means the rules labeler is used.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    # Requests per minute we allow ourselves (free tier limit is lower for some models).
    gemini_rpm: int = 10
    # "auto" = Gemini if a key is set, otherwise rules. "rules" or "gemini" force one.
    labeler: str = "auto"

    # Pipeline limits.
    youtube_discovery_quota: int = 3000
    max_competitors: int = 100
    lookback_days: int = 90
    max_posts_per_account: int = 50

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

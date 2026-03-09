"""Application settings via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./trellis.db"
    dispatch_timeout: float = 30.0
    log_level: str = "info"

    # Azure Bot Service credentials
    teams_app_id: str = ""
    teams_app_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

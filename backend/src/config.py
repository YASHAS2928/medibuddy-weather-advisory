from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Weather Advisory Support Bot"
    environment: str = "development"
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    request_timeout_seconds: float = Field(default=10.0, gt=0)

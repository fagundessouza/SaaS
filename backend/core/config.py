"""Configuracao central da aplicacao, carregada de variaveis de ambiente/.env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    storage_endpoint_url: str
    storage_access_key: str
    storage_secret_key: str
    storage_bucket: str

    jwt_secret_key: str
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    cnpj_lookup_base_url: str = "https://brasilapi.com.br/api/cnpj/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

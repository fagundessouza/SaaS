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

    # Document Intelligence (Fase 4). `tesseract_cmd` so precisa ser setado quando o binario nao
    # esta no PATH (ex.: Windows sem instalar via um metodo que registre o PATH). `tessdata_dir`
    # aponta para o diretorio com os arquivos .traineddata (ver backend/README.md — nao
    # versionado, cada ambiente baixa o proprio).
    tesseract_cmd: str = "tesseract"
    tessdata_dir: str | None = None
    ocr_language: str = "por"

    # Knowledge / RAG (Fase 5). `paraphrase-multilingual-MiniLM-L12-v2` e a escolha default:
    # multilingue (cobre PT-BR), leve o suficiente para rodar em CPU em tempo de dev/teste
    # razoavel (384 dimensoes, ~220MB) — nao e o modelo "melhor" possivel (ex.:
    # multilingual-e5-large tem mais qualidade, mas e 10x maior e mais lento sem GPU). Trocavel
    # via este setting sem mudar codigo, ver ai_platform/embeddings/provider.py e ADR-0003.
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    qdrant_url: str = "http://localhost:6333"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

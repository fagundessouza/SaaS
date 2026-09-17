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

    # Opportunity Engine (Fase 7). Limiar de similaridade de cosseno acima do qual o objeto de um
    # edital e considerado semanticamente compativel com um produto/servico declarado pelo tenant.
    # NAO e um numero escolhido no abstrato: calibrado contra 100 objetos de edital reais do PNCP
    # com dois perfis de empresa plausiveis, julgando manualmente cada resultado (ver
    # FASE_7_REPORT, secao AMBIENTE, para a tabela completa). Em 0.55 a precisao medida foi 71%
    # (perfil TI) e 86% (perfil hospitalar); baixar para 0.50 derruba a precisao de TI para 54%,
    # subir para 0.65 leva a precisao a 100% mas o recall a ~29%. Fica como setting, nao
    # constante, porque o limiar ideal varia por ramo (ver RISCOS do relatorio) e precisa ser
    # revisado com dado de cliente piloto real.
    opportunity_semantic_match_threshold: float = 0.55
    # Janela de editais considerada a cada ciclo de matching. Sobreposicao generosa de proposito:
    # criar Opportunity e idempotente por (tenant_id, tender_id), entao reavaliar e barato, e
    # perder um edital por causa de um ciclo que falhou nao e.
    opportunity_matching_lookback_hours: int = 72

    # Limiares de similaridade de cosseno entre um Requirement de categoria TECNICA e o
    # `object_description` de um Attestation do tenant (Fase 8, ver
    # domains/procurement/analysis/service.py). NAO calibrados contra dado real ainda (ao
    # contrario de `opportunity_semantic_match_threshold` acima) — valores de engenharia,
    # ponto de partida razoavel, ver PENDENCIAS do docs/phase-reports/FASE_8_REPORT.md.
    analysis_attestation_met_threshold: float = 0.55
    analysis_attestation_review_threshold: float = 0.40

    # Notification Engine (Fase 10). SMTP nao configurado (padrao) = `ConsoleEmailChannel`
    # (loga a notificacao em vez de enviar — mesmo espirito de "sem gateway de pagamento" ja
    # usado em core/billing: a interface e real, o provider real entra quando houver um
    # ambiente com credenciais de verdade para configurar). Ver core/notifications/channels/.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "notificacoes@licitacoes.local"

    # Web Push (VAPID, RFC 8292) — par de chaves proprio do projeto, gerado uma vez com
    # `uv run python -c "from py_vapid import Vapid02; Vapid02().save_key('vapid_private.pem')"`
    # (nao versionado, ver .gitignore). Sem exigir nenhuma conta externa: ao contrario de e-mail,
    # Web Push nao depende de um provedor terceiro, so das proprias chaves. Nao configurado
    # (padrao) = `ConsolePushChannel`, mesmo raciocinio do e-mail.
    vapid_private_key: str | None = None
    vapid_public_key: str | None = None
    vapid_subject: str = "mailto:contato@licitacoes.local"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

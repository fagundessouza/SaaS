"""Extracao de Requirement a partir do texto ja processado/indexado de um edital (Fase 6).

Duas etapas, classificadas explicitamente conforme ADR-0007 ("IA assistindo regra" para extracao
de requisitos):

1. REGRA (deterministica): dos chunks ja indexados pela Fase 5, os candidatos a requisito de
   habilitacao sao os do tipo `clause` cujo cabecalho de secao bate com vocabulario conhecido de
   habilitacao em edital brasileiro — mesmo espirito da deteccao de cabecalho do chunker
   (ai_platform/chunking/chunker.py), aplicado aqui a um subconjunto de secoes (nem toda secao
   conhecida do chunker e sobre habilitacao: "da proposta", "dos precos", "das sancoes" nao sao).
2. IA (embeddings, zero-shot): cada candidato e classificado em uma `RequirementCategory` por
   similaridade de cosseno contra um texto-prototipo por categoria, usando o mesmo
   EmbeddingProvider self-hosted da Fase 5 (fastembed) — NAO um LLM generativo novo. Decisao
   deliberada (ver DECISOES do relatorio da Fase 6): ADR-0003 previa um segundo provider
   (LLMProvider de completion) apenas "quando houver necessidade real de comparar custo/
   qualidade", e classificacao zero-shot por embedding ja resolve este caso de uso sem exigir
   infraestrutura nova (API key, custo por chamada, latencia de rede) nem violar o YAGNI daquele
   ADR. `confidence` e o cosseno da categoria vencedora, nao uma probabilidade calibrada — uma
   pendencia explicita, nao escondida (ver relatorio).
"""

from __future__ import annotations

import math
import re
import uuid

from sqlalchemy import delete, select

from ai_platform.chunking.chunker import ChunkType
from ai_platform.embeddings.fastembed_provider import get_embedding_provider
from ai_platform.retrieval.search import ChunkRecord, get_document_chunks
from core.db.session import system_session
from core.observability.logging import get_logger
from core.observability.metrics import requirements_extracted_total
from domains.procurement.tenders.models import Requirement, RequirementCategory

logger = get_logger(__name__)

# Subconjunto do vocabulario do chunker (ai_platform/chunking/chunker.py) especificamente sobre
# habilitacao — deliberadamente mais estreito que `_KNOWN_SECTION_PATTERNS` de la, que tambem
# cobre secoes nao relacionadas a requisito (proposta, sancoes, recursos etc.).
_HABILITACAO_HEADING_PATTERN = re.compile(
    r"da habilita[cç][aã]o|documentos? de habilita[cç][aã]o|"
    r"qualifica[cç][aã]o t[eé]cnica|"
    r"qualifica[cç][aã]o econ[oô]mico.?financeira|"
    r"regularidade fiscal|requisitos fiscais",
    re.IGNORECASE,
)

_CATEGORY_PROTOTYPES: dict[RequirementCategory, str] = {
    RequirementCategory.FISCAL: (
        "Regularidade fiscal e trabalhista: certidao negativa de debitos federais, estaduais e "
        "municipais, FGTS, INSS, CNDT, prova de inscricao no CNPJ e regularidade tributaria."
    ),
    RequirementCategory.TECNICA: (
        "Qualificacao tecnica: atestado de capacidade tecnica, comprovacao de experiencia "
        "anterior em objeto compativel, registro ou inscricao em conselho de classe "
        "profissional."
    ),
    RequirementCategory.ECONOMICO_FINANCEIRA: (
        "Qualificacao economico-financeira: balanco patrimonial, demonstracoes contabeis, "
        "indices de liquidez, capital social minimo, patrimonio liquido."
    ),
    RequirementCategory.JURIDICA: (
        "Habilitacao juridica: ato constitutivo, contrato social ou estatuto, registro "
        "comercial, documento de identificacao do representante legal, procuracao."
    ),
}

_CATEGORY_ORDER = list(_CATEGORY_PROTOTYPES.keys())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _is_habilitacao_candidate(chunk: ChunkRecord) -> bool:
    if chunk.chunk_type != ChunkType.CLAUSE.value:
        return False
    if chunk.section is None:
        return False
    return bool(_HABILITACAO_HEADING_PATTERN.search(chunk.section))


async def _classify_category(
    candidates: list[ChunkRecord],
) -> list[tuple[RequirementCategory, float]]:
    provider = get_embedding_provider()
    prototype_texts = [_CATEGORY_PROTOTYPES[category] for category in _CATEGORY_ORDER]
    vectors = await provider.embed([chunk.content for chunk in candidates] + prototype_texts)

    candidate_vectors = vectors[: len(candidates)]
    prototype_vectors = vectors[len(candidates) :]

    classifications: list[tuple[RequirementCategory, float]] = []
    for vector in candidate_vectors:
        scores = [
            _cosine_similarity(vector, prototype_vector) for prototype_vector in prototype_vectors
        ]
        best_index = max(range(len(scores)), key=lambda i: scores[i])
        classifications.append((_CATEGORY_ORDER[best_index], scores[best_index]))
    return classifications


async def extract_requirements_for_document_version(
    tender_id: uuid.UUID, document_version_id: uuid.UUID, *, force: bool = False
) -> int:
    """Extrai e persiste Requirement a partir dos chunks ja indexados de uma DocumentVersion.
    Idempotente por `(document_version_id, chunk_index)` (constraint no banco) — checagem de
    cache-hit aqui evita reembedar candidatos ja processados, mesmo padrao de
    `ai_platform/retrieval/indexer.py::index_document_version`.
    """
    if not force:
        async with system_session() as session:
            existing = await session.execute(
                select(Requirement.id).where(Requirement.document_version_id == document_version_id)
            )
            if existing.first() is not None:
                logger.info(
                    "requirements.extraction_cache_hit",
                    document_version_id=str(document_version_id),
                )
                return 0

    chunks = await get_document_chunks(document_version_id, chunk_type=ChunkType.CLAUSE.value)
    candidates = [chunk for chunk in chunks if _is_habilitacao_candidate(chunk)]
    if not candidates:
        logger.info("requirements.no_candidates", document_version_id=str(document_version_id))
        return 0

    classifications = await _classify_category(candidates)

    created = 0
    async with system_session() as session:
        if force:
            # Reextracao completa: apaga o que existia para esta versao antes de reinserir, para
            # nao violar `uq_requirements_document_chunk` nem deixar Requirement obsoleto (ex.:
            # chunk que nao e mais candidato apos ajuste de heuristica) para tras.
            await session.execute(
                delete(Requirement).where(Requirement.document_version_id == document_version_id)
            )

        for chunk, (category, confidence) in zip(candidates, classifications, strict=True):
            if not force:
                existing = await session.execute(
                    select(Requirement.id).where(
                        Requirement.document_version_id == document_version_id,
                        Requirement.chunk_index == chunk.chunk_index,
                    )
                )
                if existing.first() is not None:
                    continue

            session.add(
                Requirement(
                    tender_id=tender_id,
                    category=category,
                    description=chunk.content,
                    confidence=confidence,
                    document_version_id=document_version_id,
                    chunk_index=chunk.chunk_index,
                    section=chunk.section,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                )
            )
            requirements_extracted_total.labels(category=category.value).inc()
            created += 1

    logger.info(
        "requirements.extracted",
        document_version_id=str(document_version_id),
        tender_id=str(tender_id),
        count=created,
    )
    return created

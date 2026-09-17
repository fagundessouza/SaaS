"""Opportunity Engine — decide se um Tender vira uma Opportunity para um tenant, e por que.

Funil em duas etapas, na ordem exigida pela mitigacao do risco 5 da analise critica da Fase 0
("filtro deterministico antes de qualquer chamada a IA", ver docs/00-CRITICAL_ANALYSIS.md secao
sobre explosao de custo em escala) e pelo ADR-0007:

1. REGRA (deterministica, custo ~zero): regiao. Se o perfil declara UFs e a UF do edital nao
   esta entre elas, descarta AQUI — sem embedding, sem chamada de modelo. E a barreira que
   derruba a maior parte do volume nacional antes de qualquer custo de IA.
2. REGRA (deterministica): palavra-chave sobre o objeto do edital, comparando com os
   produtos/servicos declarados pelo tenant (normalizado: minusculas, sem acento). Se bate, ja
   e match com confianca 1.0 — e o embedding NAO roda (nao ha o que refinar: o termo literal
   esta no texto).
3. IA (embeddings), so quando 1 passou e 2 nao bateu: similaridade semantica entre o objeto do
   edital e cada produto/servico declarado. E exatamente o caso que a regra nao cobre —
   sinonimo e reformulacao ("material de expediente" vs. "material de escritorio") — e a linha
   "Matching semantico de objeto do edital com produtos/servicos do tenant | Valor real" da
   tabela de vereditos da analise critica.

O resultado NUNCA e um score unico: `MatchEvaluation` carrega compatibilidade e confianca
decompostas por criterio (ver docstring de OpportunityMatch e item 5 da tabela de ambiguidades
da analise critica).
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ai_platform.embeddings.fastembed_provider import get_embedding_provider
from core.config import get_settings

# Termos curtos geram falso positivo por substring ("cal" dentro de "calcados", "papel" dentro
# de "papelaria" ainda e aceitavel, mas "gas" dentro de "gasolina" nao) — o filtro de palavra
# -chave exige um termo com pelo menos este tamanho para ser considerado. Termos menores do que
# isso ficam so para o matching semantico.
_MIN_KEYWORD_LENGTH = 4

# Preambulo formulaico de objeto de edital. Editais brasileiros quase nunca comecam pelo objeto
# real: comecam por "Registro de precos para eventual e futura aquisicao de...", "Contratacao de
# empresa especializada para prestacao de servicos de...". Esse texto e constante entre editais e
# domina o embedding da frase, diluindo o sinal do que realmente esta sendo comprado.
#
# Medido (ver FASE_7_REPORT, secao AMBIENTE): remover o preambulo antes de embedar levou
# "Registro de precos para eventual aquisicao de material de expediente" x "material de
# escritorio" de 0.434 para 0.679, e o equivalente de TI de 0.741 para 0.972. Aplica-se APENAS ao
# caminho semantico — o filtro de palavra-chave usa o texto completo, onde o preambulo nao
# atrapalha (busca de substring nao e diluida por contexto).
_OBJECT_PREAMBLE = re.compile(
    r"^\s*(registro\s+de\s+pre[cç]os?\s+(para\s+)?(eventual\s+)?(e\s+futura\s+)?"
    r"|futura\s+e\s+eventual\s+"
    r"|aquisi[cç][aã]o\s+(de\s+)?"
    r"|contrata[cç][aã]o\s+(de\s+)?(empresa\s+)?(especializada\s+)?"
    r"(para\s+)?(a\s+)?(presta[cç][aã]o\s+(de\s+)?(servi[cç]os?\s+)?(de\s+)?)?"
    r"|fornecimento\s+(de\s+)?"
    r"|presta[cç][aã]o\s+(de\s+)?(servi[cç]os?\s+)?(de\s+)?)+",
    re.IGNORECASE,
)


def _strip_object_preamble(objeto: str) -> str:
    stripped = _OBJECT_PREAMBLE.sub("", objeto).strip()
    # Se o preambulo era o objeto inteiro (edital com objeto degenerado tipo "Aquisicao de"),
    # melhor embedar o texto original do que uma string vazia.
    return stripped or objeto.strip()


def _normalize(text: str) -> str:
    """Minusculas e sem acento — o objeto de edital vem em caixa/acentuacao inconsistente, e
    comparar 'MATERIAL DE ESCRITÓRIO' com 'material de escritorio' precisa bater."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@dataclass(frozen=True)
class MatchProfile:
    """O recorte do CompanyProfile que o matching realmente usa — passado explicitamente em vez
    de o motor carregar o modelo do banco, para manter `evaluate_match` uma funcao pura
    (testavel sem Postgres, e sem risco de ler dado TENANT fora de um tenant_session)."""

    regions: list[str]
    products: list[str]
    services: list[str]

    @property
    def terms(self) -> list[str]:
        return [term for term in [*self.products, *self.services] if term.strip()]


@dataclass(frozen=True)
class MatchEvaluation:
    matched: bool
    compatibility: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)


def _evaluate_region(tender_uf: str | None, profile_regions: list[str]) -> dict[str, Any]:
    """Lista de regioes vazia = tenant nao declarou restricao, entao regiao nao filtra nada
    (matched=True, `reason` explicando que nao houve restricao a aplicar) — nunca o contrario.
    Tratar "nao declarou" como "nao aceita nenhuma UF" zeraria o radar de todo tenant novo, que
    e justamente quem mais precisa ver volume no primeiro uso.
    """
    if not profile_regions:
        return {"matched": True, "reason": "sem restricao de regiao declarada"}

    normalized_regions = [region.strip().upper() for region in profile_regions]
    if tender_uf is None:
        # UF desconhecida (edital antigo, antes da correcao retroativa da Fase 7, ou fonte que
        # omitiu) com perfil que declarou restricao: nao da para afirmar compatibilidade, mas
        # tambem nao da para afirmar incompatibilidade. Trata como NAO compativel de proposito —
        # um falso negativo aqui e recuperavel (o edital reaparece quando a UF for preenchida),
        # um falso positivo enche o radar de oportunidade de outro estado.
        return {
            "matched": False,
            "reason": "UF do edital desconhecida e perfil restringe regiao",
            "profile_regions": normalized_regions,
        }

    matched = tender_uf.strip().upper() in normalized_regions
    return {
        "matched": matched,
        "tender_uf": tender_uf.strip().upper(),
        "profile_regions": normalized_regions,
    }


def _evaluate_keyword(objeto: str, terms: list[str]) -> dict[str, Any]:
    normalized_objeto = _normalize(objeto)
    matched_terms = [
        term
        for term in terms
        if len(term.strip()) >= _MIN_KEYWORD_LENGTH
        and _normalize(term.strip()) in normalized_objeto
    ]
    return {"matched": bool(matched_terms), "matched_terms": matched_terms}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _evaluate_semantic(objeto: str, terms: list[str]) -> dict[str, Any]:
    threshold = get_settings().opportunity_semantic_match_threshold
    comparable_objeto = _strip_object_preamble(objeto)

    provider = get_embedding_provider()
    vectors = await provider.embed([comparable_objeto, *terms])
    objeto_vector, term_vectors = vectors[0], vectors[1:]

    scores = [_cosine_similarity(objeto_vector, term_vector) for term_vector in term_vectors]
    best_index = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_index]

    return {
        "matched": best_score >= threshold,
        "best_term": terms[best_index],
        "score": best_score,
        "threshold": threshold,
        # Guardado na evidencia porque o texto comparado nao e o objeto bruto — sem isto, um score
        # inesperado seria impossivel de auditar sem reimplementar a limpeza de preambulo.
        "compared_text": comparable_objeto,
    }


async def evaluate_match(
    *, objeto: str, tender_uf: str | None, profile: MatchProfile
) -> MatchEvaluation:
    """Avalia um Tender contra um perfil. Funcao pura exceto pela chamada de embedding (etapa 3),
    que so acontece quando a etapa 1 passou e a 2 nao bateu — ver docstring do modulo.
    """
    region = _evaluate_region(tender_uf, profile.regions)
    if not region["matched"]:
        return MatchEvaluation(
            matched=False, compatibility={"region": region}, confidence={"region": 1.0}
        )

    terms = profile.terms
    if not terms:
        # Perfil sem produto/servico declarado: nao ha como afirmar compatibilidade de objeto.
        # Nao vira Opportunity — o radar sem esse dado seria "todo edital do estado", que e ruido,
        # nao valor. A UX precisa cobrar esse cadastro no onboarding (ver PENDENCIAS da Fase 7).
        return MatchEvaluation(
            matched=False,
            compatibility={
                "region": region,
                "keyword": {"matched": False, "reason": "perfil sem produtos/servicos declarados"},
            },
            # Toda chave presente em `compatibility` tem sua contraparte aqui: confidence e a
            # confianca DA TECNICA (deterministica = 1.0), nao do resultado — um "nao bateu"
            # deterministico e tao confiavel quanto um "bateu".
            confidence={"region": 1.0, "keyword": 1.0},
        )

    keyword = _evaluate_keyword(objeto, terms)
    if keyword["matched"]:
        return MatchEvaluation(
            matched=True,
            compatibility={"region": region, "keyword": keyword},
            confidence={"region": 1.0, "keyword": 1.0},
        )

    semantic = await _evaluate_semantic(objeto, terms)
    return MatchEvaluation(
        matched=bool(semantic["matched"]),
        compatibility={"region": region, "keyword": keyword, "semantic": semantic},
        confidence={"region": 1.0, "keyword": 1.0, "semantic": float(semantic["score"])},
    )

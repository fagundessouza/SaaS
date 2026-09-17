"""Funil de matching do Opportunity Engine (ver domains/procurement/opportunities/matching.py).

O matching semantico usa o EmbeddingProvider real (mesmo padrao de tests/unit/test_embeddings.py
da Fase 5: similaridade semantica de verdade, nao mock) — exceto nos testes que provam
justamente que o embedding NAO e chamado, que injetam um provider explosivo.
"""

from __future__ import annotations

import pytest

import domains.procurement.opportunities.matching as matching_module
from domains.procurement.opportunities.matching import (
    MatchProfile,
    _evaluate_keyword,
    evaluate_match,
)

_PAPELARIA = MatchProfile(
    regions=["RN", "PB"],
    products=["material de escritorio", "papel A4"],
    services=[],
)


class _ExplodingProvider:
    """Prova que o caminho de IA nao foi tocado: se o funil chamar embedding, o teste falha."""

    model_name = "exploding"
    dimension = 1

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError(
            "embedding nao deveria ser chamado: a etapa deterministica ja decidiu o resultado"
        )


@pytest.fixture
def no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(matching_module, "get_embedding_provider", _ExplodingProvider)


async def test_region_mismatch_rejects_without_calling_embedding(no_embedding: None) -> None:
    """O filtro deterministico de regiao roda ANTES de qualquer IA — e a mitigacao do risco 5 da
    analise critica (custo de LLM/embedding em escala). Se algum dia alguem inverter a ordem do
    funil, este teste quebra."""
    evaluation = await evaluate_match(
        objeto="Aquisicao de material de escritorio", tender_uf="SP", profile=_PAPELARIA
    )

    assert evaluation.matched is False
    assert evaluation.compatibility["region"]["matched"] is False
    assert evaluation.compatibility["region"]["tender_uf"] == "SP"
    assert "keyword" not in evaluation.compatibility  # nem chegou a avaliar objeto
    assert "semantic" not in evaluation.compatibility


async def test_keyword_match_short_circuits_embedding(no_embedding: None) -> None:
    """Quando o termo literal esta no objeto, nao ha o que refinar semanticamente — o embedding
    seria custo puro sem informacao nova."""
    evaluation = await evaluate_match(
        objeto="AQUISIÇÃO DE MATERIAL DE ESCRITÓRIO PARA A SECRETARIA",
        tender_uf="RN",
        profile=_PAPELARIA,
    )

    assert evaluation.matched is True
    assert evaluation.compatibility["keyword"]["matched"] is True
    assert evaluation.compatibility["keyword"]["matched_terms"] == ["material de escritorio"]
    assert "semantic" not in evaluation.compatibility
    assert evaluation.confidence == {"region": 1.0, "keyword": 1.0}


async def test_keyword_match_ignores_case_and_accent(no_embedding: None) -> None:
    evaluation = await evaluate_match(
        objeto="Registro de preços para PAPEL A4 e outros insumos",
        tender_uf="PB",
        profile=_PAPELARIA,
    )

    assert evaluation.matched is True
    assert evaluation.compatibility["keyword"]["matched_terms"] == ["papel A4"]


async def test_empty_regions_means_no_region_restriction(no_embedding: None) -> None:
    """Tenant que nao declarou regiao ve edital de qualquer UF — nunca o contrario (um perfil
    novo, sem regiao declarada, nao pode ter o radar zerado)."""
    profile = MatchProfile(regions=[], products=["material de escritorio"], services=[])

    evaluation = await evaluate_match(
        objeto="Aquisicao de material de escritorio", tender_uf="AM", profile=profile
    )

    assert evaluation.matched is True
    assert evaluation.compatibility["region"]["matched"] is True


async def test_unknown_tender_uf_with_declared_regions_rejects(no_embedding: None) -> None:
    evaluation = await evaluate_match(
        objeto="Aquisicao de material de escritorio", tender_uf=None, profile=_PAPELARIA
    )

    assert evaluation.matched is False
    assert evaluation.compatibility["region"]["matched"] is False


async def test_profile_without_products_or_services_never_matches(no_embedding: None) -> None:
    profile = MatchProfile(regions=["RN"], products=[], services=[])

    evaluation = await evaluate_match(
        objeto="Aquisicao de material de escritorio", tender_uf="RN", profile=profile
    )

    assert evaluation.matched is False
    assert evaluation.compatibility["keyword"]["matched"] is False
    assert "sem produtos/servicos" in evaluation.compatibility["keyword"]["reason"]


def test_short_terms_do_not_count_as_keyword_match() -> None:
    """Termo curto (< 4 caracteres) casaria por substring dentro de palavras nao relacionadas
    ('gas' dentro de 'gasolina') — fica fora do filtro literal de proposito. Testa a regra
    isolada: no funil completo, um objeto que nao bate por palavra-chave segue para a etapa
    semantica, que e outro comportamento (testado separadamente)."""
    result = _evaluate_keyword("Aquisicao de gasolina comum para a frota municipal", ["gas"])

    assert result["matched"] is False
    assert result["matched_terms"] == []


async def test_semantic_match_catches_synonym_the_keyword_filter_misses() -> None:
    """O caso que justifica a etapa de IA: 'material de expediente' e o termo oficial para o que
    o tenant declarou como 'material de escritorio', mas nenhum termo literal bate."""
    evaluation = await evaluate_match(
        objeto="Registro de precos para eventual aquisicao de material de expediente",
        tender_uf="RN",
        profile=_PAPELARIA,
    )

    assert evaluation.compatibility["keyword"]["matched"] is False
    assert evaluation.matched is True
    assert evaluation.compatibility["semantic"]["matched"] is True
    assert evaluation.confidence["semantic"] == evaluation.compatibility["semantic"]["score"]


async def test_semantic_step_compares_object_without_boilerplate_preamble() -> None:
    """O preambulo formulaico ("Registro de precos para eventual aquisicao de") e removido antes
    de embedar, porque domina o vetor da frase e dilui o objeto real — medido na Fase 7: o mesmo
    par sai de 0.434 para 0.679. A evidencia guarda o texto efetivamente comparado, para o score
    ser auditavel."""
    evaluation = await evaluate_match(
        objeto="Registro de precos para eventual aquisicao de material de expediente",
        tender_uf="RN",
        profile=_PAPELARIA,
    )

    assert evaluation.compatibility["semantic"]["compared_text"] == "material de expediente"


async def test_semantically_unrelated_object_is_rejected() -> None:
    evaluation = await evaluate_match(
        objeto="Contratacao de servicos de dedetizacao e controle de pragas urbanas",
        tender_uf="RN",
        profile=_PAPELARIA,
    )

    assert evaluation.matched is False
    assert evaluation.compatibility["semantic"]["matched"] is False
    assert (
        evaluation.compatibility["semantic"]["score"]
        < (evaluation.compatibility["semantic"]["threshold"])
    )


async def test_evaluation_never_exposes_a_single_aggregate_score() -> None:
    """Invariante de produto, nao so de codigo: um numero unico de compatibilidade sem
    decomposicao e classificado como risco de "Fake AI" na analise critica da Fase 0. A avaliacao
    carrega confianca POR CRITERIO, e nenhuma chave agregada."""
    evaluation = await evaluate_match(
        objeto="Aquisicao de material de expediente", tender_uf="RN", profile=_PAPELARIA
    )

    assert set(evaluation.confidence) == set(evaluation.compatibility)
    for forbidden in ("score", "total", "overall", "final"):
        assert forbidden not in evaluation.confidence

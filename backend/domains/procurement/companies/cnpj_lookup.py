"""Adapter de consulta de CNPJ — fonte publica (BrasilAPI), isolado atras de uma interface
minima para que trocar de fonte no futuro (ex.: ReceitaWS, ou uma API oficial se/quando existir)
seja um novo adapter, nao um refactor de dominio (mesmo principio de core/llm, ADR-0003).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from core.config import get_settings


class CnpjLookupError(Exception):
    """Falha ao consultar o CNPJ — rede, formato invalido, ou CNPJ nao encontrado na fonte."""


@dataclass(frozen=True)
class CnpjLookupResult:
    legal_name: str
    trade_name: str | None
    cnaes: list[dict[str, Any]]
    city: str | None
    state: str | None
    raw: dict[str, Any]


def normalize_cnpj(cnpj: str) -> str:
    digits = re.sub(r"\D", "", cnpj)
    if len(digits) != 14:
        raise CnpjLookupError(f"CNPJ '{cnpj}' nao tem 14 digitos apos normalizacao")
    return digits


async def lookup_cnpj(cnpj: str) -> CnpjLookupResult:
    digits = normalize_cnpj(cnpj)
    url = f"{get_settings().cnpj_lookup_base_url}/{digits}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise CnpjLookupError(f"Erro de rede consultando CNPJ {digits}: {exc}") from exc

    if response.status_code == 404:
        raise CnpjLookupError(f"CNPJ {digits} nao encontrado na fonte")
    if response.status_code != 200:
        raise CnpjLookupError(
            f"Fonte de CNPJ retornou status inesperado {response.status_code} para {digits}"
        )

    data = response.json()

    cnaes = [
        {"codigo": data["cnae_fiscal"], "descricao": data.get("cnae_fiscal_descricao")},
    ]
    for secundario in data.get("cnaes_secundarios") or []:
        cnaes.append({"codigo": secundario.get("codigo"), "descricao": secundario.get("descricao")})

    return CnpjLookupResult(
        legal_name=data.get("razao_social") or "",
        trade_name=data.get("nome_fantasia") or None,
        cnaes=cnaes,
        city=data.get("municipio"),
        state=data.get("uf"),
        raw=data,
    )

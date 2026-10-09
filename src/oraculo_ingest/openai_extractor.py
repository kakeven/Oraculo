"""Adaptador opcional para extração via OpenAI Responses API."""

from __future__ import annotations

import os
from typing import Any

from .abilities import AbilityInput, SYSTEM_PROMPT, make_prompt


def extract_with_openai(source: AbilityInput, model_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não está definida no ambiente.")
    try:
        from openai import OpenAI
        from pydantic import BaseModel, ConfigDict
    except ImportError as exc:
        raise RuntimeError('Instale a integração com: pip install -e ".[openai]"') from exc

    class Ability(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str
        abbreviation: str
        description: str
        applications: list[str]
        evidence_quote: str
        page_pdf: int

    class AbilityResponse(BaseModel):
        model_config = ConfigDict(extra="forbid")
        abilities: list[Ability]

    prompt = make_prompt(source)
    client = OpenAI(timeout=60, max_retries=1)
    try:
        response = client.responses.parse(
            model=model_name,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt["user"]},
            ],
            text_format=AbilityResponse,
            store=False,
        )
    except Exception as exc:
        raise RuntimeError(f"Falha na API ({type(exc).__name__}); nenhum arquivo foi gravado.") from exc
    if response.output_parsed is None:
        raise RuntimeError("A API não retornou habilidades estruturadas; nenhum arquivo foi gravado.")
    usage = response.usage
    return response.output_parsed.model_dump(), {
        "provider": "openai",
        "model": model_name,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }

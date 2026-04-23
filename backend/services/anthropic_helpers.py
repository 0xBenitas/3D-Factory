"""Helpers communs pour les appels Claude API.

Factorise les patterns répétés dans `prompt_optimizer.py`, `seo_gen.py` et
`quality_scorer.py` : client, extraction de texte, parsing JSON tolérant,
traduction des erreurs SDK en exceptions typées du service.

Chaque service conserve sa propre hiérarchie d'exceptions (pour que le
caller puisse filtrer `retry_on` sur un type précis), mais les helpers ici
sont paramétrés par ces classes pour éviter la triplette de code.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Type

import anthropic

import config

logger = logging.getLogger(__name__)


def get_client_or_raise(auth_exc_cls: Type[Exception]) -> anthropic.AsyncAnthropic:
    """Construit un client Claude ou lève `auth_exc_cls` si la clé manque."""
    key = config.get_api_key("anthropic")
    if not key:
        raise auth_exc_cls("ANTHROPIC_API_KEY not configured (set it in Settings)")
    return anthropic.AsyncAnthropic(api_key=key)


def extract_text(message: anthropic.types.Message) -> str:
    """Concatène les blocs `text` d'une réponse Claude (ignore tool_use,
    image, etc.)."""
    parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def parse_json_tolerant(raw: str) -> dict | None:
    """Parse une réponse Claude en JSON, tolérant :
    - aux blocs fenced ```json … ```
    - au JSON embarqué dans un texte plus large (matche le premier `{…}`).

    Retourne None si irrécupérable — le caller décide du fallback.
    """
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    if not candidate.lstrip().startswith("{"):
        m = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not m:
            return None
        candidate = m.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("parse_json_tolerant: JSON parse error: %s", exc)
        return None


def wrap_api_error(
    exc: anthropic.APIError,
    context: str,
    *,
    auth_cls: Type[Exception],
    refused_cls: Type[Exception],
    generic_cls: Type[Exception],
) -> Exception:
    """Traduit une erreur SDK Anthropic en exception typée du service.

    - `AuthenticationError` (401) → `auth_cls`    : non-retryable (clé invalide)
    - `BadRequestError` (400)     → `refused_cls` : non-retryable (safety filter)
    - tout le reste (429, 5xx, réseau) → `generic_cls` : retryable
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return auth_cls(f"Claude auth failed ({context}): {exc}")
    if isinstance(exc, anthropic.BadRequestError):
        return refused_cls(f"Claude rejected request ({context}): {exc}")
    return generic_cls(f"Claude API error ({context}): {exc}")


def truncate_smart(text: str, max_chars: int) -> str:
    """Tronque à `max_chars` sans couper en plein mot (sauf si pas de
    séparateur disponible dans les 50 derniers chars)."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    space = cut.rfind(" ")
    return cut[:space] if space > max_chars - 50 else cut

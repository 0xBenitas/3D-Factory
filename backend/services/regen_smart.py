"""Régénération intelligente (Phase 1.6) — un seul appel Claude.

Prend le prompt original + le score détaillé + la catégorie, retourne un
prompt ajusté + une justification courte. Utilisé par
`POST /api/models/{id}/regen-smart-suggest` qui ne déclenche PAS la regen
elle-même : le frontend pré-remplit le panneau "Regénérer" avec la
suggestion, l'utilisateur valide.

Modèle Claude : `config.CLAUDE_MODEL` (Sonnet par défaut). On ne lève
jamais — en cas d'erreur on retourne `None`, l'UI affiche un toast.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

import config
from app_settings import get_effective_prompt
from services import anthropic_helpers

logger = logging.getLogger(__name__)

MAX_TOKENS_REPLY = 600


@dataclass(frozen=True)
class SmartSuggestion:
    prompt: str
    rationale: str


async def suggest_regen(
    original_prompt: str,
    category: str | None,
    qc_score: float | None,
    qc_details: dict[str, Any] | None,
) -> SmartSuggestion | None:
    """Appelle Claude pour proposer un prompt ajusté. Retourne `None` si
    Claude refuse, l'API plante, ou le JSON est ininterprétable.
    """
    key = config.get_api_key("anthropic")
    if not key:
        logger.warning("regen_smart: ANTHROPIC_API_KEY missing")
        return None
    if not original_prompt or not original_prompt.strip():
        logger.warning("regen_smart: empty original_prompt, skipping")
        return None

    criteria = (qc_details or {}).get("criteria") or {}
    summary = (qc_details or {}).get("summary") or ""

    user_msg = (
        f"Catégorie : {category or 'inconnue'}\n"
        f"Score global : {qc_score if qc_score is not None else 'N/A'} / 10\n"
        f"Score par critère :\n{json.dumps(criteria, indent=2, ensure_ascii=False)}\n"
        f"Summary scorer : {summary}\n\n"
        f"Prompt original :\n{original_prompt}"
    )

    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=get_effective_prompt("regen_smart"),
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        logger.warning("regen_smart: Claude API error: %s", exc)
        return None

    raw = anthropic_helpers.extract_text(message)
    data = anthropic_helpers.parse_json_tolerant(raw)
    if not isinstance(data, dict):
        logger.warning("regen_smart: unparseable response: %r", raw[:200] if raw else None)
        return None

    new_prompt = str(data.get("prompt") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    if not new_prompt:
        logger.warning("regen_smart: empty prompt in JSON response")
        return None

    return SmartSuggestion(prompt=new_prompt, rationale=rationale or "(pas de justification)")

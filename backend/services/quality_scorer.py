"""Étape 4 du pipeline : scoring qualité via Claude API.

Envoie les `mesh_metrics` brutes à Claude (texte, pas vision) et récupère
un score /10 + critères détaillés + summary.

System prompt : verbatim SPECS §1.3.

**Important** : le score est informatif. Si Claude échoue, on retourne
`None` et le pipeline continue — le modèle arrive en "pending" sans
score, les métriques brutes restent visibles (cf. SPECS §5).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

import config
from app_settings import get_effective_prompt
from services import anthropic_helpers

logger = logging.getLogger(__name__)

MAX_TOKENS_REPLY = 1500

# Défaut verbatim SPECS §1.3 : voir services/prompt_registry.py
# (brique `quality_scorer`). Chargé à chaque appel.


@dataclass
class QualityScoreResult:
    """Retour de `score_mesh` — cohérent avec `GenerationResult` des engines.

    `score = None` et `criteria = {}` si le scoring échoue — le pipeline
    continue, le modèle arrive en "pending" avec les métriques brutes.
    """

    score: float | None = None
    criteria: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None


async def score_mesh(
    mesh_metrics: dict,
    object_description: str,
) -> QualityScoreResult:
    """Appelle Claude pour scorer le mesh. Ne lève jamais — retourne un
    résultat vide en cas d'échec (le pipeline doit continuer).
    """
    key = config.get_api_key("anthropic")
    if not key:
        logger.warning("QualityScorer: ANTHROPIC_API_KEY missing, skipping")
        return QualityScoreResult()

    user_msg = (
        f"Type d'objet demandé : {object_description}\n"
        f"Métriques mesh :\n{json.dumps(mesh_metrics, indent=2)}"
    )
    client = anthropic.AsyncAnthropic(api_key=key)

    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=get_effective_prompt("quality_scorer"),
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        logger.warning("QualityScorer: Claude API error, skipping: %s", exc)
        return QualityScoreResult()

    raw = anthropic_helpers.extract_text(message)
    data = anthropic_helpers.parse_json_tolerant(raw)
    if not data:
        logger.warning("QualityScorer: unparseable response, skipping")
        return QualityScoreResult()

    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        logger.warning("QualityScorer: missing/invalid 'score' field")
        return QualityScoreResult()

    return QualityScoreResult(
        score=score,
        criteria=data.get("criteria") or {},
        summary=data.get("summary"),
    )

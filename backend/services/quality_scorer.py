"""Étape 4 du pipeline : scoring qualité via Claude API.

Envoie les `mesh_metrics` brutes à Claude (texte, pas vision) et récupère
un score per-criterion (0-10) + summary. Depuis Phase 1.4 (2026-04-25),
le score global est calculé côté Python via `scoring_profiles` à partir
de la `category` détectée par l'optimizer — Claude reste focalisé sur le
scoring par critère.

**Important** : le score est informatif. Si Claude échoue, on retourne
`None` et le pipeline continue — le modèle arrive en "pending" sans
score, les métriques brutes restent visibles.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

import config
from app_settings import get_effective_prompt
from services import anthropic_helpers, scoring_profiles

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
    category: str | None = None,
) -> QualityScoreResult:
    """Appelle Claude pour scorer le mesh. Ne lève jamais — retourne un
    résultat vide en cas d'échec (le pipeline doit continuer).

    `category` (Figurine/Fonctionnel/Déco) pilote les pondérations. None
    → poids historiques (cf. `scoring_profiles.DEFAULT_WEIGHTS`).
    """
    key = config.get_api_key("anthropic")
    if not key:
        logger.warning("QualityScorer: ANTHROPIC_API_KEY missing, skipping")
        return QualityScoreResult()

    user_msg = (
        f"Type d'objet demandé : {object_description}\n"
        f"Catégorie : {category or 'inconnue'}\n"
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

    criteria = data.get("criteria") or {}

    # Score global = moyenne pondérée par profil (Phase 1.4). Fallback
    # au champ `score` renvoyé par Claude si on n'a pas de critères
    # exploitables (override legacy qui ne suit plus le format JSON).
    score = scoring_profiles.compute_weighted_score(criteria, category)
    if score is None:
        try:
            score = float(data.get("score"))
        except (TypeError, ValueError):
            logger.warning("QualityScorer: no usable score (no criteria + no fallback)")
            return QualityScoreResult()

    return QualityScoreResult(
        score=score,
        criteria=criteria,
        summary=data.get("summary"),
    )

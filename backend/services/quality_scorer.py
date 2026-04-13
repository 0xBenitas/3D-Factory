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
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

import config

logger = logging.getLogger(__name__)

MAX_TOKENS_REPLY = 1500

# SPECS §1.3 — verbatim.
_SYSTEM = """Tu es un expert en impression 3D FDM/SLA. On te donne les métriques brutes d'un mesh 3D. Tu dois évaluer sa qualité pour l'impression et donner un score sur 10.

Évalue chaque critère sur 10 et donne un score global (moyenne pondérée) :

1. Manifold (poids 2) : is_manifold=true → 10/10, false → 2/10. Un mesh non-manifold a des arêtes partagées par plus de 2 faces.
2. Watertight (poids 2) : is_watertight=true → 10/10, false → 3/10. Nécessaire pour le slicing.
3. Épaisseur des parois (poids 2) : min_wall_thickness_mm >= 1.5mm = 10/10, entre 0.8 et 1.5 = 5/10, < 0.8 = 2/10.
4. Surplombs (poids 1) : max_overhang_angle_deg <= 45° = 10/10, 45-60° = 7/10, > 60° = 4/10 (supports nécessaires).
5. Parties flottantes (poids 2) : connected_components == 1 = 10/10, > 1 = 2/10.
6. Faces dégénérées (poids 1) : 0 = 10/10, < 1% du total = 7/10, > 1% = 3/10.
7. Nombre de faces (poids 0.5) : 5k-50k = 10/10, 50k-100k = 7/10, > 100k = 5/10 (lourd pour les slicers).
8. Proportions (poids 0.5) : bounding_box cohérent avec le type d'objet.

Réponds UNIQUEMENT en JSON, pas de texte autour :
{
  "score": 7.5,
  "criteria": {
    "manifold": { "score": 10, "note": "OK" },
    "watertight": { "score": 10, "note": "OK" },
    "wall_thickness": { "score": 6, "note": "Min 1.2mm, un peu juste" },
    "overhangs": { "score": 8, "note": "Max 52°, supports optionnels" },
    "floating_parts": { "score": 10, "note": "1 seul composant" },
    "degenerate_faces": { "score": 10, "note": "0 faces dégénérées" },
    "face_count": { "score": 10, "note": "12.4k faces, optimal" },
    "proportions": { "score": 9, "note": "Bounding box cohérent" }
  },
  "summary": "Bon modèle, attention à l'épaisseur minimale sur les bords fins. Imprimable sans supports."
}"""


@dataclass
class QualityScoreResult:
    """Retour de `score_mesh` — cohérent avec `GenerationResult` des engines.

    `score = None` et `criteria = {}` si le scoring échoue — le pipeline
    continue, le modèle arrive en "pending" avec les métriques brutes.
    """

    score: float | None = None
    criteria: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None


def _extract_text(message: anthropic.types.Message) -> str:
    parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _parse_json(raw: str) -> dict | None:
    """Parse une réponse Claude en JSON, tolérant aux entourages markdown."""
    if not raw:
        return None
    # Strip ```json … ``` si Claude ajoute du markdown.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    # Fallback : premier { ... } trouvé.
    if not candidate.lstrip().startswith("{"):
        m = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not m:
            return None
        candidate = m.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("QualityScorer: JSON parse error: %s", exc)
        return None


async def score_mesh(
    mesh_metrics: dict,
    object_description: str,
) -> QualityScoreResult:
    """Appelle Claude pour scorer le mesh. Ne lève jamais — retourne un
    résultat vide en cas d'échec (le pipeline doit continuer).
    """
    if not config.ANTHROPIC_API_KEY:
        logger.warning("QualityScorer: ANTHROPIC_API_KEY missing, skipping")
        return QualityScoreResult()

    user_msg = (
        f"Type d'objet demandé : {object_description}\n"
        f"Métriques mesh :\n{json.dumps(mesh_metrics, indent=2)}"
    )
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        logger.warning("QualityScorer: Claude API error, skipping: %s", exc)
        return QualityScoreResult()

    raw = _extract_text(message)
    data = _parse_json(raw)
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

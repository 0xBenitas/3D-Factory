"""Profils catégoriels du scorer (Phase 1.4, 2026-04-25).

Le scorer Claude renvoie un score 0-10 par critère. Le score global est
calculé ici en Python via une moyenne pondérée — pondérations différentes
selon la catégorie détectée par l'optimizer (Figurine/Fonctionnel/Déco).

Pourquoi pas dans le prompt Claude : changer les poids selon le profil
demanderait 3 prompts Claude différents (ou des conditionals dans le
prompt) — fragile, dur à versionner. Mieux vaut garder Claude focalisé
sur le scoring per-criterion (bonne tâche pour un LLM) et faire la
moyenne pondérée côté code (déterministe, cheap, ré-utilisable).

Catégories supportées :
- "Figurine"     : art/perso/jouets — printability + lisibilité visuelle
- "Fonctionnel"  : pièces mécaniques — robustesse + supports OK
- "Déco"         : pots/vases/bibelots — équilibré + proportions
- None / inconnu : pondérations DEFAULT (équivalentes à l'ancien prompt SPECS)
"""

from __future__ import annotations

CRITERIA: tuple[str, ...] = (
    "manifold",
    "watertight",
    "wall_thickness",
    "overhangs",
    "floating_parts",
    "degenerate_faces",
    "face_count",
    "proportions",
)

# Poids historiques (SPECS §1.3). Utilisés quand `category` est None ou
# hors de la liste connue.
DEFAULT_WEIGHTS: dict[str, float] = {
    "manifold": 2.0,
    "watertight": 2.0,
    "wall_thickness": 2.0,
    "overhangs": 1.0,
    "floating_parts": 2.0,
    "degenerate_faces": 1.0,
    "face_count": 0.5,
    "proportions": 0.5,
}

# Profils — les poids ne reflètent pas une "importance absolue", juste
# l'équilibre relatif entre critères pour ce type d'objet. Total libre,
# la pondération est normalisée par la somme des poids.
PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    # Figurine : art/perso. Watertight + manifold critiques (impression sans
    # défauts visibles), proportions importantes (lisibilité), parois et
    # surplombs moins critiques (détails fins acceptables, supports OK).
    "Figurine": {
        "manifold": 2.5,
        "watertight": 2.5,
        "wall_thickness": 1.0,
        "overhangs": 0.8,
        "floating_parts": 1.5,
        "degenerate_faces": 1.0,
        "face_count": 0.5,
        "proportions": 2.0,
    },
    # Fonctionnel : pièces mécaniques. Parois, surplombs, géométrie propre
    # priment sur l'esthétique. Pas de détails visuels à scorer.
    "Fonctionnel": {
        "manifold": 2.0,
        "watertight": 2.0,
        "wall_thickness": 2.5,
        "overhangs": 2.0,
        "floating_parts": 2.0,
        "degenerate_faces": 1.5,
        "face_count": 0.5,
        "proportions": 1.0,
    },
    # Déco : pots/vases/bibelots. Équilibré, proportions importantes,
    # parois moyennes (pas besoin de tenir une charge mais pas trop fines
    # non plus pour la durabilité).
    "Déco": {
        "manifold": 2.0,
        "watertight": 2.0,
        "wall_thickness": 1.5,
        "overhangs": 1.0,
        "floating_parts": 1.5,
        "degenerate_faces": 1.0,
        "face_count": 0.5,
        "proportions": 2.0,
    },
}


def get_weights(category: str | None) -> dict[str, float]:
    """Retourne les poids pour la catégorie. Fallback DEFAULT_WEIGHTS."""
    if category and category in PROFILE_WEIGHTS:
        return PROFILE_WEIGHTS[category]
    return DEFAULT_WEIGHTS


def compute_weighted_score(criteria: dict, category: str | None) -> float | None:
    """Moyenne pondérée des scores per-criterion selon le profil.

    `criteria` est le dict renvoyé par Claude :
        {"manifold": {"score": 10, "note": "..."}, ...}

    Retourne None si aucun critère exploitable n'est présent (peut arriver
    si Claude renvoie un format dégénéré).
    """
    weights = get_weights(category)

    weighted_sum = 0.0
    total_weight = 0.0
    for crit_id in CRITERIA:
        crit = criteria.get(crit_id)
        if not isinstance(crit, dict):
            continue
        raw = crit.get("score")
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        # Borne le score dans [0, 10] : Claude peut occasionnellement
        # déraper (ex: "0/10" stocké en string, "11" si surenchère).
        score = max(0.0, min(10.0, score))
        w = weights.get(crit_id, 0.0)
        weighted_sum += score * w
        total_weight += w

    if total_weight <= 0:
        return None
    return round(weighted_sum / total_weight, 1)

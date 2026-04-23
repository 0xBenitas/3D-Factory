"""Étape 7 du pipeline : SEO + paramètres impression + prompt lifestyle.

Trois appels Claude indépendants (SPECS §1.4 / §1.5 / §1.6) :
- `generate_lifestyle_prompt` : prompt image ≤ 200 chars pour Stability.
- `generate_listing`          : { title, description, tags, price_eur }.
- `generate_print_params`     : paramètres FDM (layer, infill, supports…).

Les erreurs typées non-retryable sont remontées (`SeoGenAuthError`,
`SeoGenRefused`). Les erreurs transitoires sont remontées en
`SeoGenError` brute, le caller (`tasks.py`) décide du retry.

En cas d'échec complet, `tasks.py` tombe sur un fallback (prompt lifestyle
minimal, listing vide, `DEFAULT_PRINT_PARAMS`) — le pipeline export ne
doit PAS bloquer sur une erreur Claude (SPECS §5 étape 7).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

import config
from services import anthropic_helpers

logger = logging.getLogger(__name__)

MAX_TOKENS_REPLY = 1500
LIFESTYLE_MAX_CHARS = 200


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class SeoGenError(Exception):
    """Erreur générique — retry possible (5xx, timeout, JSON invalide)."""


class SeoGenAuthError(SeoGenError):
    """401 : clé Claude invalide. Retry inutile."""


class SeoGenRefused(SeoGenError):
    """400 : safety filter ou bad request. Retry inutile."""


NON_RETRYABLE: tuple[type[SeoGenError], ...] = (SeoGenAuthError, SeoGenRefused)


# --------------------------------------------------------------------------- #
# System prompts (verbatim SPECS §1.4 / §1.5 / §1.6)
# --------------------------------------------------------------------------- #

# SPECS §1.4 — placeholders entre {{}} pour échapper la substitution str.format.
_SYSTEM_LISTING = """Tu es un expert en vente de fichiers STL sur les marketplaces d'impression 3D (Cults3D, Printables, Thangs). Tu génères des listings optimisés pour maximiser les ventes.

Règles :
- Le titre doit être accrocheur ET contenir des mots-clés recherchés (max {max_title_length} caractères).
- La description doit vendre le produit : bénéfices, originalité, cas d'usage. PAS de jargon technique excessif (max {max_description_length} caractères).
- Inclure les dimensions approximatives basées sur le bounding_box.
- {max_tags} tags pertinents, mélange de termes génériques ("3D print", "STL") et spécifiques (type d'objet).
- Prix suggéré en EUR basé sur la complexité (simple = 1-2€, moyen = 2-4€, complexe = 4-8€).
- Ton : {tone}

Réponds UNIQUEMENT en JSON :
{{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "price_eur": 2.99
}}"""

# SPECS §1.5 — pas de substitution, on peut laisser les { tels quels.
_SYSTEM_PRINT_PARAMS = """Tu es un expert en impression 3D FDM. À partir des métriques d'un mesh, tu recommandes les paramètres d'impression optimaux.

Réponds UNIQUEMENT en JSON :
{
  "layer_height_mm": 0.2,
  "infill_percent": 20,
  "supports_needed": false,
  "support_notes": "Aucun surplomb > 55°",
  "nozzle_diameter_mm": 0.4,
  "material_recommended": "PLA",
  "estimated_print_time_h": 4.5,
  "estimated_material_g": 35,
  "orientation_tip": "Imprimer debout, base plate vers le bas",
  "difficulty": "facile"
}

Règles :
- layer_height : 0.2 par défaut, 0.12 si détails fins (faces > 30k), 0.28 si objet simple gros
- infill : 15% pour déco, 20-30% pour fonctionnel, 50%+ pour pièces mécaniques
- supports : basé sur max_overhang_angle_deg (> 55° = supports nécessaires)
- matériau : PLA par défaut, PETG si pièce fonctionnelle, résine si très détaillé (faces > 50k)
- temps estimé : approximation basée sur volume et infill
- difficulty : "facile" (pas de supports, simple), "moyen" (supports ou calibration), "avancé" (multi-matériau ou fragile)"""

# SPECS §1.6
_SYSTEM_LIFESTYLE = """Tu génères un prompt pour une API de génération d'image. Le but : créer une photo lifestyle d'un objet imprimé en 3D, comme une photo produit professionnelle.

Règles :
- L'objet est imprimé en PLA blanc/gris (pas de couleur flashy).
- Le contexte doit correspondre au type d'objet.
- Photo réaliste, éclairage doux naturel, haute qualité.
- Limite : 200 caractères.
- Réponds UNIQUEMENT avec le prompt image, rien d'autre.

Exemples par type :
- Déco/pot : "3D printed white geometric plant pot on wooden shelf, Scandinavian interior, soft natural light, product photography"
- Figurine : "3D printed gray dragon figurine in glass display case, dramatic side lighting, dark background, product photography"
- Technique/support : "3D printed white phone stand on minimalist desk, laptop in background, clean studio lighting, product photography"
- Rangement : "3D printed desk organizer with pens and supplies, modern home office, warm natural light, lifestyle photography\""""


DEFAULT_PRINT_PARAMS: dict[str, Any] = {
    "layer_height_mm": 0.2,
    "infill_percent": 20,
    "supports_needed": False,
    "support_notes": "—",
    "nozzle_diameter_mm": 0.4,
    "material_recommended": "PLA",
    "estimated_print_time_h": None,
    "estimated_material_g": None,
    "orientation_tip": "—",
    "difficulty": "moyen",
}


# --------------------------------------------------------------------------- #
# Helpers communs (cf. services/anthropic_helpers.py pour la plomberie
# Claude partagée avec prompt_optimizer et quality_scorer).
# --------------------------------------------------------------------------- #

def _wrap(exc: anthropic.APIError, context: str) -> SeoGenError:
    return anthropic_helpers.wrap_api_error(  # type: ignore[return-value]
        exc, context,
        auth_cls=SeoGenAuthError,
        refused_cls=SeoGenRefused,
        generic_cls=SeoGenError,
    )


# --------------------------------------------------------------------------- #
# 1. Lifestyle prompt (SPECS §1.6)
# --------------------------------------------------------------------------- #

async def generate_lifestyle_prompt(object_description: str) -> str:
    """Génère un prompt image ≤ 200 chars adapté au type d'objet."""
    client = anthropic_helpers.get_client_or_raise(SeoGenAuthError)
    user_msg = f"Type d'objet : {object_description}"
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=400,
            system=_SYSTEM_LIFESTYLE,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "lifestyle_prompt") from exc

    text = anthropic_helpers.extract_text(message)
    if not text:
        raise SeoGenError("Claude returned empty lifestyle prompt")
    return anthropic_helpers.truncate_smart(text, LIFESTYLE_MAX_CHARS)


# --------------------------------------------------------------------------- #
# 2. Listing SEO (SPECS §1.4)
# --------------------------------------------------------------------------- #

async def generate_listing(
    object_description: str,
    mesh_metrics: dict,
    template_name: str,
    max_title_length: int,
    max_description_length: int,
    max_tags: int,
    tone: str,
) -> dict[str, Any]:
    """Génère le listing marketplace. Retourne title/description/tags/price_eur.

    Sanitize côté Python : tronque aux longueurs max si Claude déborde,
    force le type des tags en str, parse le prix en float.
    """
    client = anthropic_helpers.get_client_or_raise(SeoGenAuthError)
    system = _SYSTEM_LISTING.format(
        max_title_length=max_title_length,
        max_description_length=max_description_length,
        max_tags=max_tags,
        tone=tone,
    )
    user_msg = (
        f"Type d'objet : {object_description}\n"
        f"Métriques mesh : faces={mesh_metrics.get('face_count')}, "
        f"volume={mesh_metrics.get('volume_cm3')}cm³, "
        f"bounding_box={mesh_metrics.get('bounding_box_mm')}mm\n"
        f"Marketplace cible : {template_name}"
    )
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "listing") from exc

    data = anthropic_helpers.parse_json_tolerant(anthropic_helpers.extract_text(message))
    if not isinstance(data, dict):
        raise SeoGenError("Claude returned non-JSON listing")

    title = anthropic_helpers.truncate_smart(
        str(data.get("title", "")).strip(), max_title_length,
    )
    description = anthropic_helpers.truncate_smart(
        str(data.get("description", "")).strip(), max_description_length,
    )
    raw_tags = data.get("tags") or []
    tags = [str(t).strip() for t in raw_tags if str(t).strip()][:max_tags]
    try:
        price = float(data.get("price_eur") or 0.0)
    except (TypeError, ValueError):
        price = 0.0

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "price_eur": round(price, 2),
    }


# --------------------------------------------------------------------------- #
# 3. Paramètres d'impression (SPECS §1.5)
# --------------------------------------------------------------------------- #

async def generate_print_params(
    object_description: str,
    mesh_metrics: dict,
) -> dict[str, Any]:
    """Génère les `print_params`. Les clés manquantes sont remplies depuis
    `DEFAULT_PRINT_PARAMS` (pour garantir un schéma stable en BDD).
    """
    client = anthropic_helpers.get_client_or_raise(SeoGenAuthError)
    user_msg = (
        f"Type d'objet : {object_description}\n"
        f"Métriques : {json.dumps(mesh_metrics, indent=2)}"
    )
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=_SYSTEM_PRINT_PARAMS,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "print_params") from exc

    data = anthropic_helpers.parse_json_tolerant(anthropic_helpers.extract_text(message))
    if not isinstance(data, dict):
        raise SeoGenError("Claude returned non-JSON print_params")

    # Merge avec les defaults pour garantir que toutes les clés existent.
    return {**DEFAULT_PRINT_PARAMS, **data}

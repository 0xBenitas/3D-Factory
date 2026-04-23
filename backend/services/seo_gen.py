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
from app_settings import get_effective_prompt
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
# System prompts
# --------------------------------------------------------------------------- #
# Défauts verbatim SPECS §1.4 / §1.5 / §1.6 : voir services/prompt_registry.py
# (briques `seo_listing`, `seo_print_params`, `seo_lifestyle`). Chargés à
# chaque appel pour honorer l'override Settings sans restart.
#
# `seo_listing` contient des placeholders `{max_title_length}`,
# `{max_description_length}`, `{max_tags}`, `{tone}` — substitués via
# `format_map(_SafePlaceholders(...))` pour que les `{foo}` inconnus
# (ajoutés par l'utilisateur dans l'override) restent littéraux au lieu
# de faire crasher `.format()`.


class _SafePlaceholders(dict):
    """`format_map` tolérant : les clés inconnues restent littérales."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


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
            system=get_effective_prompt("seo_lifestyle"),
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
    system = get_effective_prompt("seo_listing").format_map(
        _SafePlaceholders(
            max_title_length=max_title_length,
            max_description_length=max_description_length,
            max_tags=max_tags,
            tone=tone,
        )
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
            system=get_effective_prompt("seo_print_params"),
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "print_params") from exc

    data = anthropic_helpers.parse_json_tolerant(anthropic_helpers.extract_text(message))
    if not isinstance(data, dict):
        raise SeoGenError("Claude returned non-JSON print_params")

    # Merge avec les defaults pour garantir que toutes les clés existent.
    return {**DEFAULT_PRINT_PARAMS, **data}

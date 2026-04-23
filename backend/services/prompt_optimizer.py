"""Étape 1 du pipeline : optimisation du prompt via Claude API.

- Texte → Claude Sonnet reformule en prompt 3D imprimable.
- Image → Claude Vision décrit la géométrie.

System prompts verbatim depuis SPECS §1.1 et §1.2. Modèle : voir
CLAUDE_MODEL. Limite stricte : 600 caractères (contrainte Meshy).
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

import anthropic

import config
from app_settings import get_effective_prompt
from services import anthropic_helpers

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 600   # Limite Meshy (SPECS §1.1).
MAX_TOKENS_REPLY = 400

# Défauts verbatim SPECS §1.1 / §1.2 : voir services/prompt_registry.py
# (briques `prompt_optimizer_text` et `prompt_optimizer_image`).
# Chargés à chaque appel pour que l'override Settings soit pris en compte
# sans restart.


class PromptOptimizerError(Exception):
    """Erreur générique — retry possible (5xx, timeout)."""


class PromptOptimizerAuthError(PromptOptimizerError):
    """401 : clé Claude invalide. Retry inutile."""


class PromptOptimizerRefused(PromptOptimizerError):
    """Claude a refusé le contenu (safety filter, 400). Retry inutile."""


# Exceptions permanentes — à exclure du retry dans tasks.py.
NON_RETRYABLE: tuple[type[PromptOptimizerError], ...] = (
    PromptOptimizerAuthError,
    PromptOptimizerRefused,
)


def _wrap(exc: anthropic.APIError, context: str) -> PromptOptimizerError:
    return anthropic_helpers.wrap_api_error(  # type: ignore[return-value]
        exc, context,
        auth_cls=PromptOptimizerAuthError,
        refused_cls=PromptOptimizerRefused,
        generic_cls=PromptOptimizerError,
    )


async def optimize_from_text(user_input: str, engine_name: str) -> str:
    """Optimise un prompt texte pour le moteur cible.

    Lève `PromptOptimizerError` si Claude refuse ou renvoie du vide.
    """
    user_msg = f"Moteur cible : {engine_name}\nDescription utilisateur : {user_input}"

    client = anthropic_helpers.get_client_or_raise(PromptOptimizerAuthError)
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=get_effective_prompt("prompt_optimizer_text"),
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "optimize_from_text") from exc

    result = anthropic_helpers.extract_text(message)
    if not result:
        raise PromptOptimizerError("Claude returned empty prompt (possibly filtered)")
    truncated = anthropic_helpers.truncate_smart(result, MAX_PROMPT_CHARS)
    logger.info(
        "Prompt optimized (text): %d→%d chars, engine=%s",
        len(user_input), len(truncated), engine_name,
    )
    return truncated


async def optimize_from_image(image_path: str, engine_name: str) -> str:
    """Optimise un prompt à partir d'une photo uploadée (Claude Vision)."""
    p = Path(image_path)
    if not p.is_file():
        # Non-retryable : le fichier n'apparaîtra pas par magie.
        raise PromptOptimizerRefused(f"Image not found: {image_path}")

    media_type, _ = mimetypes.guess_type(p.name)
    if not media_type or not media_type.startswith("image/"):
        media_type = "image/jpeg"

    image_b64 = base64.b64encode(p.read_bytes()).decode("ascii")

    client = anthropic_helpers.get_client_or_raise(PromptOptimizerAuthError)
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=get_effective_prompt("prompt_optimizer_image"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Moteur cible : {engine_name}",
                        },
                    ],
                }
            ],
        )
    except anthropic.APIError as exc:
        raise _wrap(exc, "optimize_from_image") from exc

    result = anthropic_helpers.extract_text(message)
    if not result:
        raise PromptOptimizerError("Claude returned empty prompt (possibly filtered)")
    truncated = anthropic_helpers.truncate_smart(result, MAX_PROMPT_CHARS)
    logger.info(
        "Prompt optimized (image): %s → %d chars, engine=%s",
        p.name, len(truncated), engine_name,
    )
    return truncated

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

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 600   # Limite Meshy (SPECS §1.1).
MAX_TOKENS_REPLY = 400

# SPECS §1.1 — verbatim.
_SYSTEM_TEXT = """Tu es un expert en modélisation 3D pour l'impression. Ton rôle est de transformer une description vague en un prompt optimisé pour un générateur 3D IA.

Règles :
- Le prompt doit décrire UNIQUEMENT la géométrie (forme, proportions, détails structurels). JAMAIS de couleurs, textures, matériaux visuels.
- L'objet doit être imprimable en 3D : formes solides, épaisseur minimale 1.5mm partout, pas de parties flottantes, pas de surplombs > 60° si possible.
- Sois précis sur les proportions relatives (ex: "le pied fait 1/4 de la hauteur totale").
- Mentionne la symétrie si applicable.
- Limite : 600 caractères max (limite du moteur).
- Réponds UNIQUEMENT avec le prompt optimisé, rien d'autre."""

# SPECS §1.2 — verbatim.
_SYSTEM_IMAGE = """Tu es un expert en modélisation 3D pour l'impression. On te montre une photo d'un objet. Tu dois générer un prompt pour un générateur 3D IA qui reproduira cet objet.

Règles :
- Décris UNIQUEMENT la géométrie : forme globale, proportions, détails structurels, symétrie.
- JAMAIS de couleurs, textures, matériaux visuels — on imprime en monochrome.
- L'objet doit être imprimable : formes solides, épaisseur min 1.5mm, pas de parties flottantes.
- Si l'objet a des détails trop fins pour l'impression, simplifie-les.
- Limite : 600 caractères max.
- Réponds UNIQUEMENT avec le prompt optimisé, rien d'autre."""


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


def _client() -> anthropic.AsyncAnthropic:
    if not config.ANTHROPIC_API_KEY:
        raise PromptOptimizerAuthError("ANTHROPIC_API_KEY not configured in .env")
    return anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


def _wrap_api_error(exc: anthropic.APIError, context: str) -> PromptOptimizerError:
    """Traduit une erreur du SDK Anthropic en exception typée du service.

    - AuthenticationError (401) → non-retryable (clé invalide)
    - BadRequestError (400)     → non-retryable (safety filter)
    - tout le reste (429, 5xx, réseau) → retryable
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return PromptOptimizerAuthError(f"Claude auth failed ({context}): {exc}")
    if isinstance(exc, anthropic.BadRequestError):
        return PromptOptimizerRefused(f"Claude rejected request ({context}): {exc}")
    return PromptOptimizerError(f"Claude API error ({context}): {exc}")


def _extract_text(message: anthropic.types.Message) -> str:
    """Concatène les blocs de texte d'une réponse Claude."""
    parts: list[str] = []
    for block in message.content:
        # On ignore les blocs non-texte éventuels (tool_use, etc.).
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _truncate(text: str) -> str:
    """Tronque proprement à MAX_PROMPT_CHARS sans couper en milieu de mot."""
    if len(text) <= MAX_PROMPT_CHARS:
        return text
    cut = text[:MAX_PROMPT_CHARS]
    space = cut.rfind(" ")
    return cut[:space] if space > MAX_PROMPT_CHARS - 50 else cut


async def optimize_from_text(user_input: str, engine_name: str) -> str:
    """Optimise un prompt texte pour le moteur cible.

    Lève `PromptOptimizerError` si Claude refuse ou renvoie du vide.
    """
    user_msg = f"Moteur cible : {engine_name}\nDescription utilisateur : {user_input}"

    client = _client()
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=_SYSTEM_TEXT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        raise _wrap_api_error(exc, "optimize_from_text") from exc

    result = _extract_text(message)
    if not result:
        raise PromptOptimizerError("Claude returned empty prompt (possibly filtered)")
    truncated = _truncate(result)
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

    client = _client()
    try:
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_REPLY,
            system=_SYSTEM_IMAGE,
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
        raise _wrap_api_error(exc, "optimize_from_image") from exc

    result = _extract_text(message)
    if not result:
        raise PromptOptimizerError("Claude returned empty prompt (possibly filtered)")
    truncated = _truncate(result)
    logger.info(
        "Prompt optimized (image): %s → %d chars, engine=%s",
        p.name, len(truncated), engine_name,
    )
    return truncated

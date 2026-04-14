"""Interface commune des moteurs image pluggables.

Parallèle à `engines/base.py` (moteurs 3D). Un moteur image prend un
prompt lifestyle (+ screenshot optionnel pour img2img) et retourne N
chemins de photos PNG générées.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


# --------------------------------------------------------------------------- #
# Exceptions typées (alignées sur engines.base)
# --------------------------------------------------------------------------- #

class ImageEngineError(Exception):
    """Base de toutes les erreurs remontées par un moteur image."""


class ImageEngineAuthError(ImageEngineError):
    """401 : clé API manquante/invalide. Non-retryable."""


class ImageEngineInsufficientCredits(ImageEngineError):
    """402 : budget/crédits épuisés. Non-retryable."""


class ImageEngineRateLimited(ImageEngineError):
    """429 : retry possible après backoff."""


class ImageEngineTransient(ImageEngineError):
    """5xx ou timeout réseau — retry possible."""


class ImageEngineRefused(ImageEngineError):
    """Safety filter, bad request, non-retryable."""


RETRYABLE: tuple[type[ImageEngineError], ...] = (
    ImageEngineRateLimited,
    ImageEngineTransient,
)
NON_RETRYABLE: tuple[type[ImageEngineError], ...] = (
    ImageEngineAuthError,
    ImageEngineInsufficientCredits,
    ImageEngineRefused,
)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #

class ImageEngine(ABC):
    """Interface abstraite d'un moteur image (text-to-image, éventuellement
    img2img). Les sous-classes sont enregistrées automatiquement à
    l'import via `image_engines/__init__.py`.
    """

    #: Nom court, utilisé dans l'UI et la BDD ("stability", ...).
    name: str = ""

    @abstractmethod
    async def generate(
        self,
        context_prompt: str,
        output_dir: str,
        n_images: int = 3,
        screenshot_path: str | None = None,
    ) -> list[str]:
        """Génère `n_images` photos et retourne leurs chemins absolus.

        `screenshot_path` est fourni pour les implémentations img2img ;
        les moteurs text-to-image l'ignorent (recommandé — un screenshot
        sans texture donne un résultat bizarre en img2img, cf. SPECS §2.2).
        """
        raise NotImplementedError

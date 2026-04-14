"""Registry auto-découvert des moteurs image (parallèle à engines/).

Chaque fichier `.py` du dossier (hors `base.py` et `__init__.py`) est
importé automatiquement. À l'import, le module doit instancier son
`ImageEngine` et appeler `register(instance)`.

Usage :
    from image_engines import get_image_engine, list_image_engines
    engine = get_image_engine("stability")
    paths = await engine.generate("prompt", "/data/photos/42", 3)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

from image_engines.base import (
    ImageEngine,
    ImageEngineAuthError,
    ImageEngineError,
    ImageEngineInsufficientCredits,
    ImageEngineRateLimited,
    ImageEngineRefused,
    ImageEngineTransient,
    NON_RETRYABLE,
    RETRYABLE,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ImageEngine",
    "ImageEngineAuthError",
    "ImageEngineError",
    "ImageEngineInsufficientCredits",
    "ImageEngineRateLimited",
    "ImageEngineRefused",
    "ImageEngineTransient",
    "NON_RETRYABLE",
    "RETRYABLE",
    "register",
    "get_image_engine",
    "list_image_engines",
]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_registry: dict[str, ImageEngine] = {}


def register(engine: ImageEngine) -> None:
    """Enregistre un moteur image. Appelé par chaque module à l'import."""
    if not engine.name:
        raise ValueError(f"ImageEngine {type(engine).__name__} has no `name`")
    if engine.name in _registry:
        logger.warning("ImageEngine '%s' already registered, overwriting", engine.name)
    _registry[engine.name] = engine
    logger.info("Registered image engine: %s", engine.name)


def get_image_engine(name: str) -> ImageEngine:
    """Retourne le moteur image par son nom. Lève `KeyError` si inconnu."""
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(
            f"Unknown image engine '{name}'. Available: {sorted(_registry)}"
        ) from None


def list_image_engines() -> list[ImageEngine]:
    """Retourne la liste des moteurs enregistrés (triés par nom)."""
    return [_registry[k] for k in sorted(_registry)]


# --------------------------------------------------------------------------- #
# Auto-discovery
# --------------------------------------------------------------------------- #

_SKIP = {"__init__", "base"}
_pkg_dir = Path(__file__).resolve().parent

for _mod_info in pkgutil.iter_modules([str(_pkg_dir)]):
    if _mod_info.name in _SKIP:
        continue
    try:
        importlib.import_module(f"image_engines.{_mod_info.name}")
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to load image engine '%s': %s", _mod_info.name, exc)

"""Registry auto-découvert des moteurs 3D.

Chaque fichier `.py` du dossier `engines/` (hors `base.py` et
`__init__.py`) est importé automatiquement. À l'import, le module doit
instancier son `Engine3D` et appeler `register(instance)`.

Usage :
    from engines import get_engine, list_engines
    engine = get_engine("meshy")
    result = await engine.generate(prompt="...")
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

from engines.base import (
    Engine3D,
    EngineError,
    EngineTaskFailed,
    GenerationResult,
    InsufficientCredits,
    InvalidApiKey,
    NotSupported,
    RateLimited,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Engine3D",
    "EngineError",
    "EngineTaskFailed",
    "GenerationResult",
    "InsufficientCredits",
    "InvalidApiKey",
    "NotSupported",
    "RateLimited",
    "register",
    "get_engine",
    "list_engines",
]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_registry: dict[str, Engine3D] = {}


def register(engine: Engine3D) -> None:
    """Enregistre un moteur. Appelé par chaque module engine à l'import."""
    if not engine.name:
        raise ValueError(f"Engine {type(engine).__name__} has no `name`")
    if engine.name in _registry:
        logger.warning("Engine '%s' already registered, overwriting", engine.name)
    _registry[engine.name] = engine
    logger.info("Registered 3D engine: %s (image_input=%s)",
                engine.name, engine.supports_image_input)


def get_engine(name: str) -> Engine3D:
    """Retourne le moteur par son nom. Lève `KeyError` si inconnu."""
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(
            f"Unknown engine '{name}'. Available: {sorted(_registry)}"
        ) from None


def list_engines() -> list[Engine3D]:
    """Retourne la liste des moteurs enregistrés (triés par nom)."""
    return [_registry[k] for k in sorted(_registry)]


# --------------------------------------------------------------------------- #
# Auto-discovery : importe tous les fichiers du dossier, ce qui déclenche
# leur `register(...)` top-level.
# --------------------------------------------------------------------------- #

_SKIP = {"__init__", "base"}
_pkg_dir = Path(__file__).resolve().parent

for _mod_info in pkgutil.iter_modules([str(_pkg_dir)]):
    if _mod_info.name in _SKIP:
        continue
    try:
        importlib.import_module(f"engines.{_mod_info.name}")
    except Exception as exc:  # pragma: no cover — ne doit pas bloquer le boot
        logger.error("Failed to load engine '%s': %s", _mod_info.name, exc)

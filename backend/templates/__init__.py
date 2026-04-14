"""Registry auto-découvert des templates marketplace.

Chaque fichier `.py` du dossier (hors `base.py` et `__init__.py`) est
importé automatiquement. À l'import, le module doit instancier son
`MarketplaceTemplate` et appeler `register(instance)`.

Usage :
    from templates import get_template, list_templates
    tpl = get_template("cults3d")
    text = tpl.format_listing(seo, print_params)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

from templates.base import MarketplaceTemplate

logger = logging.getLogger(__name__)

__all__ = [
    "MarketplaceTemplate",
    "register",
    "get_template",
    "list_templates",
]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_registry: dict[str, MarketplaceTemplate] = {}


def register(template: MarketplaceTemplate) -> None:
    """Enregistre un template. Appelé par chaque module à l'import."""
    if not template.name:
        raise ValueError(f"MarketplaceTemplate {type(template).__name__} has no `name`")
    if template.name in _registry:
        logger.warning("Template '%s' already registered, overwriting", template.name)
    _registry[template.name] = template
    logger.info(
        "Registered marketplace template: %s (max_title=%d, max_tags=%d)",
        template.name, template.max_title_length, template.max_tags,
    )


def get_template(name: str) -> MarketplaceTemplate:
    """Retourne le template par son nom. Lève `KeyError` si inconnu."""
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(
            f"Unknown template '{name}'. Available: {sorted(_registry)}"
        ) from None


def list_templates() -> list[MarketplaceTemplate]:
    """Retourne la liste des templates enregistrés (triés par nom)."""
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
        importlib.import_module(f"templates.{_mod_info.name}")
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to load template '%s': %s", _mod_info.name, exc)

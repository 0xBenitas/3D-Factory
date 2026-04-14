"""Router : GET / PUT /api/settings.

Source de vérité runtime = table `settings` (seedée depuis `.env` au boot).
La UI peut modifier les clés connues (cf. `app_settings.KNOWN_KEYS`) ; les
pipelines lisent à chaque appel via `app_settings.get_*_setting()`.

Clés exposées :
- `default_engine`       : string
- `default_image_engine` : string
- `default_template`     : string
- `max_daily_budget_eur` : float (stocké en string côté BDD)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_settings import KNOWN_KEYS, get_setting, set_setting
from database import get_db
from engines import list_engines
from image_engines import list_image_engines
from templates import list_templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class SettingsPayload(BaseModel):
    """Seules les clés connues sont acceptées (les autres sont rejetées 400)."""

    default_engine: str | None = Field(default=None, max_length=50)
    default_image_engine: str | None = Field(default=None, max_length=50)
    default_template: str | None = Field(default=None, max_length=50)
    max_daily_budget_eur: float | None = Field(default=None, ge=0.0, le=1000.0)


class SettingsView(BaseModel):
    default_engine: str
    default_image_engine: str
    default_template: str
    max_daily_budget_eur: float


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _valid_engine_names(db: Session) -> set[str]:
    return {e.name for e in list_engines()}


def _valid_image_engine_names(db: Session) -> set[str]:
    return {e.name for e in list_image_engines()}


def _valid_template_names(db: Session) -> set[str]:
    return {t.name for t in list_templates()}


def _read_all(db: Session) -> SettingsView:
    return SettingsView(
        default_engine=get_setting(db, "default_engine", "meshy"),
        default_image_engine=get_setting(db, "default_image_engine", "stability"),
        default_template=get_setting(db, "default_template", "cults3d"),
        max_daily_budget_eur=_safe_float(
            get_setting(db, "max_daily_budget_eur", "2.00"), 2.00,
        ),
    )


def _safe_float(raw: str, fallback: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@router.get("", response_model=SettingsView)
def read_settings(db: Session = Depends(get_db)) -> SettingsView:
    return _read_all(db)


@router.put("", response_model=SettingsView)
def update_settings(
    payload: SettingsPayload,
    db: Session = Depends(get_db),
) -> SettingsView:
    """Applique une mise à jour partielle (PATCH-like) sur les settings.

    Valide les valeurs contre les registries (moteurs, templates) pour
    éviter qu'on puisse stocker `default_engine="banana"` qui ferait
    crasher le pipeline plus tard.
    """
    data: dict[str, Any] = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No settings to update")

    for key in data:
        if key not in KNOWN_KEYS:
            raise HTTPException(400, f"Unknown settings key: '{key}'")

    if "default_engine" in data:
        names = _valid_engine_names(db)
        if data["default_engine"] not in names:
            raise HTTPException(
                400,
                f"Unknown engine '{data['default_engine']}'. Available: {sorted(names)}",
            )
    if "default_image_engine" in data:
        names = _valid_image_engine_names(db)
        if data["default_image_engine"] not in names:
            raise HTTPException(
                400,
                f"Unknown image engine '{data['default_image_engine']}'. Available: {sorted(names)}",
            )
    if "default_template" in data:
        names = _valid_template_names(db)
        if data["default_template"] not in names:
            raise HTTPException(
                400,
                f"Unknown template '{data['default_template']}'. Available: {sorted(names)}",
            )

    for key, value in data.items():
        set_setting(db, key, str(value))
    db.commit()
    logger.info("Settings updated: %s", sorted(data.keys()))

    return _read_all(db)

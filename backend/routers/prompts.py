"""Router : GET / PUT / DELETE /api/prompts.

Édition par-brique des system prompts Claude. Le registry vit dans
`services/prompt_registry.py` (6 briques, défauts verbatim SPECS).
Les overrides sont stockés en BDD dans la table `settings` avec clé
`prompt_override_<brick_id>`.

- `GET    /api/prompts`            → liste complète (défaut + override courant)
- `PUT    /api/prompts/{brick_id}` → set override (string vide = reset)
- `DELETE /api/prompts/{brick_id}` → reset explicite (efface l'override)

Les services lisent le prompt effectif via `app_settings.get_effective_prompt`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_settings import (
    PROMPT_OVERRIDE_MAX,
    _prompt_override_key,
    get_setting,
    set_setting,
)
from database import get_db
from services.prompt_registry import PromptBrick, get_brick, list_bricks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class BrickView(BaseModel):
    id: str
    label: str
    description: str
    default: str
    override: str
    is_custom: bool
    placeholders: list[str]


class BrickListView(BaseModel):
    bricks: list[BrickView]
    max_length: int = PROMPT_OVERRIDE_MAX


class UpdateBrickPayload(BaseModel):
    override: str = Field(max_length=PROMPT_OVERRIDE_MAX)


def _view(db: Session, brick: PromptBrick) -> BrickView:
    override = get_setting(db, _prompt_override_key(brick.id), "")
    return BrickView(
        id=brick.id,
        label=brick.label,
        description=brick.description,
        default=brick.default,
        override=override,
        is_custom=bool(override.strip()),
        placeholders=list(brick.placeholders),
    )


@router.get("", response_model=BrickListView)
def list_all(db: Session = Depends(get_db)) -> BrickListView:
    return BrickListView(bricks=[_view(db, b) for b in list_bricks()])


@router.put("/{brick_id}", response_model=BrickView)
def update_brick(
    brick_id: str,
    payload: UpdateBrickPayload,
    db: Session = Depends(get_db),
) -> BrickView:
    try:
        brick = get_brick(brick_id)
    except KeyError:
        raise HTTPException(404, f"Unknown prompt brick '{brick_id}'")

    override = payload.override.strip()
    # Si brick a des placeholders requis et override non vide, ils doivent y figurer.
    if override and brick.placeholders:
        missing = [p for p in brick.placeholders if f"{{{p}}}" not in override]
        if missing:
            hint = ", ".join("{" + p + "}" for p in brick.placeholders)
            raise HTTPException(
                400,
                f"Override manque les placeholders requis : {missing}. "
                f"Utilise {hint} dans le prompt "
                "(ou laisse vide pour restaurer le défaut).",
            )

    set_setting(db, _prompt_override_key(brick.id), override)
    db.commit()
    logger.info(
        "Prompt brick '%s' %s",
        brick.id,
        "customized" if override else "cleared",
    )
    return _view(db, brick)


@router.delete("/{brick_id}", response_model=BrickView)
def reset_brick(
    brick_id: str,
    db: Session = Depends(get_db),
) -> BrickView:
    try:
        brick = get_brick(brick_id)
    except KeyError:
        raise HTTPException(404, f"Unknown prompt brick '{brick_id}'")
    set_setting(db, _prompt_override_key(brick.id), "")
    db.commit()
    logger.info("Prompt brick '%s' reset to default", brick.id)
    return _view(db, brick)

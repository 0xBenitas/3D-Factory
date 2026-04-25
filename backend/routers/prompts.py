"""Router : `/api/prompts` (vue par brique) + `/api/prompts/library` (CRUD).

Phase 1.5 (2026-04-25) — la table `prompts` est la source de vérité.
Les overrides legacy (table `settings`) ont été migrés en presets
"User custom" via `database._seed_prompt_library_and_migrate_overrides`.

`/api/prompts` (legacy, conservé pour le frontend Settings) :
- `GET    /api/prompts`              → liste briques avec preset actif
- `PUT    /api/prompts/{brick_id}`   → upsert d'un preset "User custom" + activation
- `DELETE /api/prompts/{brick_id}`   → réactive le preset "Default" (User custom conservé en biblio)

`/api/prompts/library` (Phase 1.5) :
- `GET    /api/prompts/library?brick_id=X&category=Y`
- `POST   /api/prompts/library`
- `PUT    /api/prompts/library/{id}`
- `DELETE /api/prompts/library/{id}`     (interdit si `is_default=True`)
- `POST   /api/prompts/library/{id}/activate`
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_settings import PROMPT_OVERRIDE_MAX
from database import get_db
from models import Prompt
from services.prompt_registry import PromptBrick, get_brick, list_bricks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _active_for_brick(db: Session, brick_id: str) -> Prompt | None:
    return (
        db.query(Prompt)
        .filter(Prompt.brick_id == brick_id, Prompt.is_active.is_(True))
        .first()
    )


def _default_for_brick(db: Session, brick_id: str) -> Prompt | None:
    return (
        db.query(Prompt)
        .filter(Prompt.brick_id == brick_id, Prompt.is_default.is_(True))
        .first()
    )


def _activate(db: Session, target: Prompt) -> None:
    """Active `target` en désactivant proprement l'ancien actif.

    Le flush intermédiaire est obligatoire : l'index partiel unique sur
    `is_active=1` rejette deux lignes actives simultanément.
    """
    current = _active_for_brick(db, target.brick_id)
    if current is not None and current.id != target.id:
        current.is_active = False
        db.flush()
    target.is_active = True
    db.flush()


def _validate_placeholders(brick: PromptBrick, content: str) -> None:
    if not brick.placeholders:
        return
    missing = [p for p in brick.placeholders if f"{{{p}}}" not in content]
    if missing:
        hint = ", ".join("{" + p + "}" for p in brick.placeholders)
        raise HTTPException(
            400,
            f"Le preset manque les placeholders requis : {missing}. "
            f"Utilise {hint} dans le contenu.",
        )


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class BrickView(BaseModel):
    """Vue par brique pour le frontend Settings (preserve l'ancien shape)."""

    id: str
    label: str
    description: str
    default: str
    override: str             # contenu du preset actif (vide si actif = default)
    is_custom: bool           # actif != default
    placeholders: list[str]
    active_prompt_id: int | None


class BrickListView(BaseModel):
    bricks: list[BrickView]
    max_length: int = PROMPT_OVERRIDE_MAX


class UpdateBrickPayload(BaseModel):
    override: str = Field(max_length=PROMPT_OVERRIDE_MAX)


class PromptView(BaseModel):
    id: int
    brick_id: str
    name: str
    content: str
    category: str | None
    tags: list[str] | None
    notes: str | None
    is_default: bool
    is_active: bool
    usage_count: int
    avg_score: float | None
    created_at: str
    updated_at: str


class PromptCreatePayload(BaseModel):
    brick_id: str
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=PROMPT_OVERRIDE_MAX)
    category: str | None = None
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    activate: bool = False


class PromptUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=PROMPT_OVERRIDE_MAX)
    category: str | None = None
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)


def _to_prompt_view(p: Prompt) -> PromptView:
    return PromptView(
        id=p.id,
        brick_id=p.brick_id,
        name=p.name,
        content=p.content,
        category=p.category,
        tags=p.tags or None,
        notes=p.notes,
        is_default=bool(p.is_default),
        is_active=bool(p.is_active),
        usage_count=p.usage_count or 0,
        avg_score=p.avg_score,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


def _to_brick_view(db: Session, brick: PromptBrick) -> BrickView:
    active = _active_for_brick(db, brick.id)
    active_content = active.content if active else brick.default
    is_custom = bool(active and not active.is_default)
    return BrickView(
        id=brick.id,
        label=brick.label,
        description=brick.description,
        default=brick.default,
        override=active_content if is_custom else "",
        is_custom=is_custom,
        placeholders=list(brick.placeholders),
        active_prompt_id=active.id if active else None,
    )


# --------------------------------------------------------------------------- #
# /api/prompts (vue par brique — frontend Settings actuel)
# --------------------------------------------------------------------------- #

@router.get("", response_model=BrickListView)
def list_all(db: Session = Depends(get_db)) -> BrickListView:
    return BrickListView(bricks=[_to_brick_view(db, b) for b in list_bricks()])


@router.put("/{brick_id}", response_model=BrickView)
def update_brick_active(
    brick_id: str,
    payload: UpdateBrickPayload,
    db: Session = Depends(get_db),
) -> BrickView:
    """Upsert d'un preset "User custom" pour la brique + activation.

    Si `override` vide → équivalent du DELETE (réactive le Default).
    Si l'actif courant est déjà un User custom → on met à jour son contenu.
    Sinon → nouveau preset actif (l'ancien actif passe en is_active=False).
    """
    try:
        brick = get_brick(brick_id)
    except KeyError:
        raise HTTPException(404, f"Unknown prompt brick '{brick_id}'")

    content = payload.override.strip()

    if not content:
        return _reset_to_default(db, brick)

    _validate_placeholders(brick, content)

    active = _active_for_brick(db, brick_id)
    if active is not None and not active.is_default:
        active.content = content
        db.commit()
        return _to_brick_view(db, brick)

    new_prompt = Prompt(
        brick_id=brick_id,
        name="User custom",
        content=content,
        is_default=False,
        is_active=False,
    )
    db.add(new_prompt)
    db.flush()
    _activate(db, new_prompt)
    db.commit()
    logger.info("Prompt brick '%s' customized via /api/prompts", brick_id)
    return _to_brick_view(db, brick)


@router.delete("/{brick_id}", response_model=BrickView)
def reset_brick_to_default(
    brick_id: str,
    db: Session = Depends(get_db),
) -> BrickView:
    """Réactive le preset Default. Le User custom reste dans la biblio
    (consultable / réactivable via /api/prompts/library/{id}/activate).
    """
    try:
        brick = get_brick(brick_id)
    except KeyError:
        raise HTTPException(404, f"Unknown prompt brick '{brick_id}'")
    return _reset_to_default(db, brick)


def _reset_to_default(db: Session, brick: PromptBrick) -> BrickView:
    default = _default_for_brick(db, brick.id)
    if default is None:
        # Tout premier boot — devrait avoir été créé par init_db. Garde-fou.
        default = Prompt(
            brick_id=brick.id,
            name="Default",
            content=brick.default,
            is_default=True,
            is_active=False,
        )
        db.add(default)
        db.flush()
    _activate(db, default)
    db.commit()
    logger.info("Prompt brick '%s' reset to default", brick.id)
    return _to_brick_view(db, brick)


# --------------------------------------------------------------------------- #
# /api/prompts/library (CRUD biblio versionnée — Phase 1.5)
# --------------------------------------------------------------------------- #

@router.get("/library", response_model=list[PromptView])
def library_list(
    brick_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PromptView]:
    q = db.query(Prompt)
    if brick_id:
        q = q.filter(Prompt.brick_id == brick_id)
    if category:
        q = q.filter(Prompt.category == category)
    rows = q.order_by(
        Prompt.brick_id.asc(),
        Prompt.is_active.desc(),
        Prompt.is_default.desc(),
        Prompt.created_at.desc(),
    ).all()
    return [_to_prompt_view(p) for p in rows]


@router.post("/library", response_model=PromptView, status_code=201)
def library_create(
    payload: PromptCreatePayload,
    db: Session = Depends(get_db),
) -> PromptView:
    try:
        brick = get_brick(payload.brick_id)
    except KeyError:
        raise HTTPException(404, f"Unknown prompt brick '{payload.brick_id}'")

    _validate_placeholders(brick, payload.content)

    new = Prompt(
        brick_id=brick.id,
        name=payload.name.strip(),
        content=payload.content,
        category=payload.category,
        tags=payload.tags or None,
        notes=payload.notes,
        is_default=False,
        is_active=False,
    )
    db.add(new)
    db.flush()
    if payload.activate:
        _activate(db, new)
    db.commit()
    logger.info("Prompt #%d created (brick=%s, activated=%s)",
                new.id, brick.id, payload.activate)
    return _to_prompt_view(new)


@router.put("/library/{prompt_id}", response_model=PromptView)
def library_update(
    prompt_id: int,
    payload: PromptUpdatePayload,
    db: Session = Depends(get_db),
) -> PromptView:
    p = db.get(Prompt, prompt_id)
    if p is None:
        raise HTTPException(404, f"Prompt {prompt_id} not found")
    if p.is_default:
        raise HTTPException(
            400,
            "Cannot edit a Default preset (sync via prompt_registry.py). "
            "Duplicate it as a new preset instead.",
        )

    if payload.content is not None:
        try:
            brick = get_brick(p.brick_id)
        except KeyError:
            raise HTTPException(500, f"Brick '{p.brick_id}' missing from registry")
        _validate_placeholders(brick, payload.content)
        p.content = payload.content
    if payload.name is not None:
        p.name = payload.name.strip()
    if payload.category is not None:
        p.category = payload.category or None
    if payload.tags is not None:
        p.tags = payload.tags or None
    if payload.notes is not None:
        p.notes = payload.notes or None

    db.commit()
    return _to_prompt_view(p)


@router.delete("/library/{prompt_id}", status_code=204)
def library_delete(
    prompt_id: int,
    db: Session = Depends(get_db),
) -> None:
    p = db.get(Prompt, prompt_id)
    if p is None:
        raise HTTPException(404, f"Prompt {prompt_id} not found")
    if p.is_default:
        raise HTTPException(400, "Cannot delete a Default preset.")
    if p.is_active:
        # Réactiver le Default avant de supprimer le User custom actif.
        default = _default_for_brick(db, p.brick_id)
        if default is None:
            raise HTTPException(
                500,
                f"No Default preset for brick '{p.brick_id}' — cannot deactivate this one.",
            )
        _activate(db, default)
    db.delete(p)
    db.commit()
    logger.info("Prompt #%d deleted", prompt_id)


@router.post("/library/{prompt_id}/activate", response_model=PromptView)
def library_activate(
    prompt_id: int,
    db: Session = Depends(get_db),
) -> PromptView:
    p = db.get(Prompt, prompt_id)
    if p is None:
        raise HTTPException(404, f"Prompt {prompt_id} not found")
    _activate(db, p)
    db.commit()
    logger.info("Prompt #%d activated for brick '%s'", prompt_id, p.brick_id)
    return _to_prompt_view(p)

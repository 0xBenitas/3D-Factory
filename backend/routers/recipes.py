"""Router : CRUD `/api/recipes` (Phase 1.8).

Une recette pré-remplit InputForm (engine + image_engine + category hint).
v1 minimaliste — Phase 2.13 enrichira (prompt FK par brique, viewer
preset, slicer preset, listing template).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from engines import get_engine
from image_engines import get_image_engine
from models import Recipe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


class RecipeView(BaseModel):
    id: int
    name: str
    engine: str
    image_engine: str | None
    category: str | None
    notes: str | None
    usage_count: int
    created_at: str
    updated_at: str


class RecipeCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    engine: str = Field(min_length=1, max_length=50)
    image_engine: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class RecipeUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    engine: str | None = Field(default=None, min_length=1, max_length=50)
    image_engine: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


def _to_view(r: Recipe) -> RecipeView:
    return RecipeView(
        id=r.id,
        name=r.name,
        engine=r.engine,
        image_engine=r.image_engine,
        category=r.category,
        notes=r.notes,
        usage_count=r.usage_count or 0,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


def _validate_engines(engine: str, image_engine: str | None) -> None:
    try:
        get_engine(engine)
    except KeyError as exc:
        raise HTTPException(400, f"Unknown engine '{engine}': {exc}")
    if image_engine:
        try:
            get_image_engine(image_engine)
        except KeyError as exc:
            raise HTTPException(400, f"Unknown image_engine '{image_engine}': {exc}")


@router.get("", response_model=list[RecipeView])
def list_recipes(db: Session = Depends(get_db)) -> list[RecipeView]:
    rows = db.query(Recipe).order_by(desc(Recipe.usage_count), desc(Recipe.updated_at)).all()
    return [_to_view(r) for r in rows]


@router.post("", response_model=RecipeView, status_code=201)
def create_recipe(
    payload: RecipeCreatePayload,
    db: Session = Depends(get_db),
) -> RecipeView:
    _validate_engines(payload.engine, payload.image_engine)
    r = Recipe(
        name=payload.name.strip(),
        engine=payload.engine,
        image_engine=payload.image_engine,
        category=payload.category,
        notes=payload.notes,
    )
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"A recipe named '{payload.name}' already exists")
    db.refresh(r)
    logger.info("Recipe #%d created (name=%r, engine=%s)", r.id, r.name, r.engine)
    return _to_view(r)


@router.put("/{recipe_id}", response_model=RecipeView)
def update_recipe(
    recipe_id: int,
    payload: RecipeUpdatePayload,
    db: Session = Depends(get_db),
) -> RecipeView:
    r = db.get(Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, f"Recipe {recipe_id} not found")

    if payload.engine or payload.image_engine is not None:
        _validate_engines(payload.engine or r.engine, payload.image_engine if payload.image_engine is not None else r.image_engine)

    if payload.name is not None:
        r.name = payload.name.strip()
    if payload.engine is not None:
        r.engine = payload.engine
    if payload.image_engine is not None:
        r.image_engine = payload.image_engine or None
    if payload.category is not None:
        r.category = payload.category or None
    if payload.notes is not None:
        r.notes = payload.notes or None

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Another recipe with this name already exists")
    return _to_view(r)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)) -> None:
    r = db.get(Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, f"Recipe {recipe_id} not found")
    db.delete(r)
    db.commit()
    logger.info("Recipe #%d deleted", recipe_id)


@router.post("/{recipe_id}/use", response_model=RecipeView)
def increment_usage(recipe_id: int, db: Session = Depends(get_db)) -> RecipeView:
    """Incrémente `usage_count`. Appelé par le frontend (ou plus tard par
    le pipeline si le payload pipeline carrie un `recipe_id`)."""
    r = db.get(Recipe, recipe_id)
    if r is None:
        raise HTTPException(404, f"Recipe {recipe_id} not found")
    r.usage_count = (r.usage_count or 0) + 1
    db.commit()
    return _to_view(r)

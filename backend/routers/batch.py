"""Router : `/api/batch` (Phase 1.9).

Crée un batch (recette + liste de prompts + budget cap optionnel),
schedule le worker en BackgroundTask. Le worker traite les items en
série (cf. tasks.run_batch).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import get_db
from models import BatchItem, BatchJob, Recipe
from tasks import run_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch", tags=["batch"])

MAX_ITEMS_PER_BATCH = 200
MAX_PROMPT_LEN = 5000


class BatchCreatePayload(BaseModel):
    recipe_id: int
    prompts: list[str] = Field(min_length=1, max_length=MAX_ITEMS_PER_BATCH)
    max_budget_eur: float | None = Field(default=None, ge=0.0, le=10000.0)


class BatchItemView(BaseModel):
    id: int
    position: int
    prompt: str
    status: str
    model_id: int | None
    error: str | None
    started_at: str | None
    finished_at: str | None


class BatchJobView(BaseModel):
    id: int
    recipe_id: int | None
    recipe_name: str | None
    status: str
    total: int
    done: int
    failed: int
    max_budget_eur: float | None
    spent_eur: float
    cancel_requested: bool
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class BatchJobDetail(BatchJobView):
    items: list[BatchItemView]


def _to_item_view(it: BatchItem) -> BatchItemView:
    return BatchItemView(
        id=it.id,
        position=it.position,
        prompt=it.prompt,
        status=it.status,
        model_id=it.model_id,
        error=it.error,
        started_at=it.started_at.isoformat() if it.started_at else None,
        finished_at=it.finished_at.isoformat() if it.finished_at else None,
    )


def _to_job_view(job: BatchJob, recipe: Recipe | None) -> BatchJobView:
    return BatchJobView(
        id=job.id,
        recipe_id=job.recipe_id,
        recipe_name=recipe.name if recipe else None,
        status=job.status,
        total=job.total or 0,
        done=job.done or 0,
        failed=job.failed or 0,
        max_budget_eur=job.max_budget_eur,
        spent_eur=float(job.spent_eur or 0.0),
        cancel_requested=bool(job.cancel_requested),
        error=job.error,
        created_at=job.created_at.isoformat() if job.created_at else "",
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


@router.post("", response_model=BatchJobView, status_code=201)
def create_batch(
    payload: BatchCreatePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> BatchJobView:
    """Crée un BatchJob + ses items, schedule le worker.

    Validation :
    - La recette doit exister
    - Au moins 1 prompt non vide
    - Chaque prompt <= MAX_PROMPT_LEN
    """
    recipe = db.get(Recipe, payload.recipe_id)
    if recipe is None:
        raise HTTPException(404, f"Recipe {payload.recipe_id} not found")

    cleaned = [p.strip() for p in payload.prompts]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        raise HTTPException(400, "No non-empty prompts provided")
    too_long = [i for i, p in enumerate(cleaned) if len(p) > MAX_PROMPT_LEN]
    if too_long:
        raise HTTPException(
            400,
            f"Prompts trop longs (>{MAX_PROMPT_LEN} chars) aux positions : {too_long[:5]}",
        )

    job = BatchJob(
        recipe_id=recipe.id,
        status="pending",
        total=len(cleaned),
        max_budget_eur=payload.max_budget_eur,
    )
    db.add(job)
    db.flush()

    for idx, prompt in enumerate(cleaned):
        db.add(BatchItem(
            batch_id=job.id,
            position=idx,
            prompt=prompt,
            status="pending",
        ))
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_batch, job.id)
    logger.info("Batch #%d scheduled (recipe=%s, items=%d, budget=%s)",
                job.id, recipe.name, len(cleaned), payload.max_budget_eur)
    return _to_job_view(job, recipe)


@router.get("", response_model=list[BatchJobView])
def list_batches(db: Session = Depends(get_db)) -> list[BatchJobView]:
    rows = (
        db.query(BatchJob, Recipe)
        .outerjoin(Recipe, Recipe.id == BatchJob.recipe_id)
        .order_by(desc(BatchJob.created_at))
        .limit(50)
        .all()
    )
    return [_to_job_view(j, r) for (j, r) in rows]


@router.get("/{batch_id}", response_model=BatchJobDetail)
def get_batch(batch_id: int, db: Session = Depends(get_db)) -> BatchJobDetail:
    job = db.get(BatchJob, batch_id)
    if job is None:
        raise HTTPException(404, f"Batch {batch_id} not found")
    recipe = db.get(Recipe, job.recipe_id) if job.recipe_id else None
    items = (
        db.query(BatchItem)
        .filter(BatchItem.batch_id == batch_id)
        .order_by(BatchItem.position.asc())
        .all()
    )
    return BatchJobDetail(
        **_to_job_view(job, recipe).model_dump(),
        items=[_to_item_view(it) for it in items],
    )


@router.post("/{batch_id}/cancel", response_model=BatchJobView)
def cancel_batch(batch_id: int, db: Session = Depends(get_db)) -> BatchJobView:
    job = db.get(BatchJob, batch_id)
    if job is None:
        raise HTTPException(404, f"Batch {batch_id} not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(409, f"Batch already in terminal state ({job.status})")
    job.cancel_requested = 1
    db.commit()
    recipe = db.get(Recipe, job.recipe_id) if job.recipe_id else None
    logger.info("Batch #%d: cancel requested", batch_id)
    return _to_job_view(job, recipe)

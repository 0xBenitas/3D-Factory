"""Router : CRUD partiel sur les modèles 3D + actions de validation.

Cf. ARCHITECTURE §"Models" :
- GET    /api/models?sort=score_desc&validation=pending
- GET    /api/models/{id}
- GET    /api/models/{id}/glb      (streaming du fichier pour Three.js)
- PUT    /api/models/{id}/validate
- POST   /api/models/{id}/regenerate
- POST   /api/models/{id}/remesh
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, asc
from sqlalchemy.orm import Session

from app_settings import check_budget_or_raise
from database import get_db
from models import Model
from tasks import run_pipeline_guarded, run_remesh_guarded

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

# Valeurs autorisées pour le filtre `validation`.
ValidationFilter = Literal["pending", "approved", "rejected", "all"]
SortKey = Literal["score_desc", "score_asc", "date_desc", "date_asc"]


class ModelSummary(BaseModel):
    """Résumé pour la grille de ModelsPage."""

    id: int
    input_type: str
    input_text: str | None
    engine: str
    validation: str
    pipeline_status: str
    qc_score: float | None
    cost_credits: int
    created_at: str


class ModelDetail(ModelSummary):
    """Détail complet pour le pane de sélection."""

    optimized_prompt: str | None
    input_image_path: str | None
    glb_path: str | None
    stl_path: str | None
    mesh_metrics: dict[str, Any] | None
    qc_details: dict[str, Any] | None
    repair_log: str | None
    pipeline_error: str | None
    rejection_reason: str | None
    engine_task_id: str | None
    image_engine: str | None


class ValidateRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=2000)


class RegenerateRequest(BaseModel):
    prompt_override: str | None = Field(default=None, max_length=5000)


class RemeshRequest(BaseModel):
    target_polycount: int = Field(default=30000, ge=500, le=200000)


class ActionResponse(BaseModel):
    ok: bool = True
    model_id: int


# --------------------------------------------------------------------------- #
# Helpers de sérialisation
# --------------------------------------------------------------------------- #

def _to_summary(m: Model) -> ModelSummary:
    return ModelSummary(
        id=m.id,
        input_type=m.input_type,
        input_text=m.input_text,
        engine=m.engine,
        validation=m.validation,
        pipeline_status=m.pipeline_status,
        qc_score=m.qc_score,
        cost_credits=m.cost_credits or 0,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


def _to_detail(m: Model) -> ModelDetail:
    return ModelDetail(
        **_to_summary(m).model_dump(),
        optimized_prompt=m.optimized_prompt,
        input_image_path=m.input_image_path,
        glb_path=m.glb_path,
        stl_path=m.stl_path,
        mesh_metrics=m.mesh_metrics,
        qc_details=m.qc_details,
        repair_log=m.repair_log,
        pipeline_error=m.pipeline_error,
        rejection_reason=m.rejection_reason,
        engine_task_id=m.engine_task_id,
        image_engine=m.image_engine,
    )


# --------------------------------------------------------------------------- #
# GET /api/models
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[ModelSummary])
def list_models(
    validation: ValidationFilter = "all",
    sort: SortKey = "date_desc",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ModelSummary]:
    q = db.query(Model)
    if validation != "all":
        q = q.filter(Model.validation == validation)

    # Tri : pour les scores, on pousse les NULL à la fin quel que soit le sens.
    if sort == "score_desc":
        q = q.order_by(Model.qc_score.is_(None).asc(), desc(Model.qc_score))
    elif sort == "score_asc":
        q = q.order_by(Model.qc_score.is_(None).asc(), asc(Model.qc_score))
    elif sort == "date_asc":
        q = q.order_by(asc(Model.created_at))
    else:  # date_desc (défaut)
        q = q.order_by(desc(Model.created_at))

    rows = q.limit(limit).all()
    return [_to_summary(m) for m in rows]


# --------------------------------------------------------------------------- #
# GET /api/models/{id}
# --------------------------------------------------------------------------- #

@router.get("/{model_id}", response_model=ModelDetail)
def get_model(model_id: int, db: Session = Depends(get_db)) -> ModelDetail:
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    return _to_detail(m)


# --------------------------------------------------------------------------- #
# GET /api/models/{id}/glb — stream fichier pour Three.js viewer
# --------------------------------------------------------------------------- #

@router.get("/{model_id}/glb")
def get_glb(model_id: int, db: Session = Depends(get_db)) -> FileResponse:
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    if not m.glb_path:
        raise HTTPException(404, "GLB not generated yet")
    path = Path(m.glb_path)
    if not path.is_file():
        raise HTTPException(404, f"GLB file missing on disk: {path}")
    return FileResponse(
        path,
        media_type="model/gltf-binary",
        filename=f"model_{model_id}.glb",
    )


# --------------------------------------------------------------------------- #
# GET /api/models/{id}/input-image — photo source (si input_type="image")
# --------------------------------------------------------------------------- #

@router.get("/{model_id}/input-image")
def get_input_image(model_id: int, db: Session = Depends(get_db)) -> FileResponse:
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    if not m.input_image_path:
        raise HTTPException(404, "No input image for this model")
    path = Path(m.input_image_path)
    if not path.is_file():
        raise HTTPException(404, f"Input image file missing on disk: {path}")
    mime, _ = mimetypes.guess_type(path.name)
    return FileResponse(path, media_type=mime or "image/jpeg")


# --------------------------------------------------------------------------- #
# PUT /api/models/{id}/validate
# --------------------------------------------------------------------------- #

@router.put("/{model_id}/validate", response_model=ActionResponse)
def validate_model(
    model_id: int,
    payload: ValidateRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Approve ou reject un modèle.

    - `approve` : uniquement possible depuis `pending` ou `done`
      (il faut un STL valide pour passer à l'étape export).
    - `reject` : autorisé depuis n'importe quel état terminal
      (`pending`, `done`, `failed`) — permet de nettoyer les modèles
      cassés sans régénérer.
    """
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")

    running = {"prompt", "generating", "repairing", "scoring", "photos", "packing"}
    if m.pipeline_status in running:
        raise HTTPException(
            409, f"Pipeline in progress (status='{m.pipeline_status}'), wait for completion",
        )

    if payload.action == "approve":
        if m.pipeline_status not in ("pending", "done"):
            raise HTTPException(
                400,
                f"Cannot approve: pipeline_status='{m.pipeline_status}' "
                "(no valid STL to export)",
            )
        m.validation = "approved"
        m.rejection_reason = None
        logger.info("Model #%d approved", model_id)
    else:  # reject
        m.validation = "rejected"
        m.rejection_reason = payload.reason
        logger.info("Model #%d rejected (reason=%r)", model_id, payload.reason)
    db.commit()
    return ActionResponse(model_id=model_id)


# --------------------------------------------------------------------------- #
# POST /api/models/{id}/regenerate
# --------------------------------------------------------------------------- #

@router.post("/{model_id}/regenerate", response_model=ActionResponse)
def regenerate_model(
    model_id: int,
    payload: RegenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ActionResponse:
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    if m.pipeline_status in ("prompt", "generating", "repairing", "scoring", "photos", "packing"):
        raise HTTPException(409, f"Pipeline already running (status='{m.pipeline_status}')")

    check_budget_or_raise(db)

    # Reset les champs du pipeline — garde l'input + engine + optimized_prompt
    # précédent (utile si prompt_override est null, on pourra ré-optimiser).
    m.pipeline_status = "prompt"
    m.pipeline_error = None
    m.validation = "pending"
    m.rejection_reason = None
    m.qc_score = None
    m.qc_details = None
    m.mesh_metrics = None
    m.repair_log = None
    db.commit()

    background_tasks.add_task(
        run_pipeline_guarded, model_id, payload.prompt_override
    )
    logger.info("Model #%d regenerate scheduled (prompt_override=%s)",
                model_id, bool(payload.prompt_override))
    return ActionResponse(model_id=model_id)


# --------------------------------------------------------------------------- #
# POST /api/models/{id}/remesh
# --------------------------------------------------------------------------- #

@router.post("/{model_id}/remesh", response_model=ActionResponse)
def remesh_model(
    model_id: int,
    payload: RemeshRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ActionResponse:
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    if not m.engine_task_id:
        raise HTTPException(
            400,
            "Cannot remesh: no engine_task_id (original generation missing)",
        )
    if m.pipeline_status in ("prompt", "generating", "repairing", "scoring", "photos", "packing"):
        raise HTTPException(409, f"Pipeline already running (status='{m.pipeline_status}')")

    check_budget_or_raise(db)

    m.pipeline_status = "generating"
    m.pipeline_error = None
    m.validation = "pending"
    m.rejection_reason = None
    m.qc_score = None
    m.qc_details = None
    m.mesh_metrics = None
    m.repair_log = None
    db.commit()

    background_tasks.add_task(
        run_remesh_guarded, model_id, payload.target_polycount
    )
    logger.info("Model #%d remesh scheduled (target_polycount=%d)",
                model_id, payload.target_polycount)
    return ActionResponse(model_id=model_id)

"""Router : exports marketplace (étapes 6-7 du pipeline).

Cf. ARCHITECTURE §"API Endpoints / Exports" :
- POST /api/exports/generate        : schedule le pipeline export
- GET  /api/exports?model_id=N      : liste des exports d'un modèle
- GET  /api/exports/{id}            : détail d'un export
- GET  /api/exports/{id}/zip        : stream du ZIP
- GET  /api/exports/{id}/listing    : texte brut (pour copier-coller)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_settings import check_budget_or_raise
from database import get_db
from models import Export, Model
from tasks import run_export_guarded
from templates import get_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exports", tags=["exports"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class ExportGenerateRequest(BaseModel):
    model_id: int = Field(ge=1)
    template: str = Field(max_length=50)


class ExportGenerateResponse(BaseModel):
    model_id: int
    template: str


class ExportDetail(BaseModel):
    id: int
    model_id: int
    template: str
    title: str
    description: str
    tags: list[str]
    price_suggested: float
    print_params: dict[str, Any]
    zip_path: str | None
    created_at: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_RUNNING_STATUSES = {
    "prompt", "generating", "repairing", "scoring", "photos", "packing",
}


def _to_detail(ex: Export) -> ExportDetail:
    return ExportDetail(
        id=ex.id,
        model_id=ex.model_id,
        template=ex.template,
        title=ex.title,
        description=ex.description,
        tags=list(ex.tags or []),
        price_suggested=float(ex.price_suggested or 0.0),
        print_params=dict(ex.print_params or {}),
        zip_path=ex.zip_path,
        created_at=ex.created_at.isoformat() if ex.created_at else "",
    )


# --------------------------------------------------------------------------- #
# POST /api/exports/generate
# --------------------------------------------------------------------------- #

@router.post("/generate", response_model=ExportGenerateResponse)
def generate_export(
    payload: ExportGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ExportGenerateResponse:
    """Schedule le pipeline export (photos + SEO + ZIP) en BackgroundTask.

    Pré-requis :
    - Le modèle doit exister et être approuvé.
    - Il doit avoir un `stl_path` + `glb_path` + `mesh_metrics` (sortie du
      pipeline de génération).
    - Aucun pipeline ne doit tourner pour ce modèle.
    """
    m = db.get(Model, payload.model_id)
    if m is None:
        raise HTTPException(404, f"Model {payload.model_id} not found")
    if m.validation != "approved":
        raise HTTPException(
            400,
            f"Model must be approved before export (current validation: {m.validation})",
        )
    if m.pipeline_status in _RUNNING_STATUSES:
        raise HTTPException(
            409,
            f"Pipeline in progress (status='{m.pipeline_status}')",
        )
    if not m.stl_path or not m.glb_path or not m.mesh_metrics:
        raise HTTPException(
            400,
            "Model missing stl/glb/mesh_metrics — run the generation pipeline first",
        )

    # Valider le template avant de schedule.
    try:
        get_template(payload.template)
    except KeyError as exc:
        raise HTTPException(400, str(exc))

    check_budget_or_raise(db)

    background_tasks.add_task(run_export_guarded, payload.model_id, payload.template)
    logger.info("Export scheduled: model_id=%d, template=%s",
                payload.model_id, payload.template)
    return ExportGenerateResponse(model_id=payload.model_id, template=payload.template)


# --------------------------------------------------------------------------- #
# GET /api/exports?model_id=N
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[ExportDetail])
def list_exports(
    model_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> list[ExportDetail]:
    """Liste les exports d'un modèle, le plus récent d'abord."""
    rows = (
        db.query(Export)
        .filter(Export.model_id == model_id)
        .order_by(Export.created_at.desc(), Export.id.desc())
        .all()
    )
    return [_to_detail(ex) for ex in rows]


# --------------------------------------------------------------------------- #
# GET /api/exports/{id}
# --------------------------------------------------------------------------- #

@router.get("/{export_id}", response_model=ExportDetail)
def get_export(export_id: int, db: Session = Depends(get_db)) -> ExportDetail:
    ex = db.get(Export, export_id)
    if ex is None:
        raise HTTPException(404, f"Export {export_id} not found")
    return _to_detail(ex)


# --------------------------------------------------------------------------- #
# GET /api/exports/{id}/zip
# --------------------------------------------------------------------------- #

@router.get("/{export_id}/zip")
def get_export_zip(export_id: int, db: Session = Depends(get_db)) -> FileResponse:
    ex = db.get(Export, export_id)
    if ex is None:
        raise HTTPException(404, f"Export {export_id} not found")
    if not ex.zip_path:
        raise HTTPException(404, "ZIP not generated yet")
    path = Path(ex.zip_path)
    if not path.is_file():
        raise HTTPException(404, f"ZIP file missing on disk: {path}")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


# --------------------------------------------------------------------------- #
# GET /api/exports/{id}/listing — texte brut prêt à copier-coller
# --------------------------------------------------------------------------- #

@router.get("/{export_id}/listing")
def get_export_listing(
    export_id: int,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    ex = db.get(Export, export_id)
    if ex is None:
        raise HTTPException(404, f"Export {export_id} not found")

    # On reformate depuis la BDD plutôt que d'extraire du ZIP — plus simple
    # et permet de régénérer le listing si on change le template (utile si
    # l'utilisateur a juste besoin du texte).
    try:
        template = get_template(ex.template)
    except KeyError:
        raise HTTPException(
            500,
            f"Template '{ex.template}' no longer available in registry",
        )

    seo = {
        "title": ex.title,
        "description": ex.description,
        "tags": list(ex.tags or []),
        "price_eur": float(ex.price_suggested or 0.0),
    }
    text = template.format_listing(seo, dict(ex.print_params or {}))
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

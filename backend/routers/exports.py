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
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from app_settings import check_budget_or_raise
from config import resolve_under_data_dir
from database import get_db
from models import Export, Model
from services import packager
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


class ExportPatchRequest(BaseModel):
    """Édition manuelle du listing (sans réappel Claude). Tous les champs
    sont optionnels — on n'update que ceux fournis. Le ZIP est reconstruit
    avec le template courant si au moins un champ change."""

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=50)
    price_suggested: float | None = Field(default=None, ge=0.0, le=10000.0)


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


@router.patch("/{export_id}", response_model=ExportDetail)
def patch_export(
    export_id: int,
    payload: ExportPatchRequest,
    db: Session = Depends(get_db),
) -> ExportDetail:
    """Édition manuelle du listing (title/desc/tags/price) sans réappel
    Claude. Reconstruit le ZIP avec le template courant si le modèle a
    toujours son STL. Sinon on update uniquement les champs texte.

    Intentionnellement PAS de `check_budget_or_raise` : cette édition est
    gratuite (pas d'appel API externe), c'est justement tout l'intérêt
    — tweaker un mot sans cramer 0.10€ de régénération.
    """
    ex = db.get(Export, export_id)
    if ex is None:
        raise HTTPException(404, f"Export {export_id} not found")

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")

    if "title" in updates:
        ex.title = updates["title"].strip() or ex.title
    if "description" in updates:
        ex.description = updates["description"]
    if "tags" in updates:
        ex.tags = [str(t).strip() for t in updates["tags"] if str(t).strip()]
    if "price_suggested" in updates:
        ex.price_suggested = round(float(updates["price_suggested"]), 2)

    # Regénération du ZIP si le STL est encore là. Best-effort : si on ne
    # peut pas reconstruire (STL supprimé, disque plein), on commit quand
    # même les changements texte — l'utilisateur peut toujours copier le
    # listing via /listing qui lit les nouveaux champs BDD.
    try:
        template = get_template(ex.template)
    except KeyError:
        raise HTTPException(
            500,
            f"Template '{ex.template}' no longer available in registry",
        )

    zip_rebuilt = False
    model = db.get(Model, ex.model_id)
    if model and model.stl_path:
        try:
            stl_safe = resolve_under_data_dir(model.stl_path)
            if stl_safe.is_file():
                seo = {
                    "title": ex.title,
                    "description": ex.description,
                    "tags": list(ex.tags or []),
                    "price_eur": float(ex.price_suggested or 0.0),
                }
                listing_text = template.format_listing(
                    seo, dict(ex.print_params or {}),
                )
                photo_paths = list(model.photo_paths or [])
                exports_dir = config.DATA_DIR / "exports"
                new_zip = packager.build_zip(
                    ex.model_id,
                    str(stl_safe),
                    photo_paths,
                    listing_text,
                    ex.title,
                    str(exports_dir),
                )
                ex.zip_path = new_zip
                zip_rebuilt = True
        except (ValueError, packager.PackagerError, OSError) as exc:
            logger.warning(
                "Export #%d: fields updated but ZIP rebuild skipped: %s",
                export_id, exc,
            )

    db.commit()
    logger.info(
        "Export #%d patched (fields=%s, zip_rebuilt=%s)",
        export_id, sorted(updates.keys()), zip_rebuilt,
    )
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
    try:
        path = resolve_under_data_dir(ex.zip_path)
    except ValueError:
        logger.error(
            "Rejected path traversal: export_id=%d zip_path=%r",
            export_id, ex.zip_path,
        )
        raise HTTPException(404, "ZIP not accessible")
    if not path.is_file():
        raise HTTPException(404, "ZIP file missing on disk")
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

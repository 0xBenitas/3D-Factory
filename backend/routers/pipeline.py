"""Router : POST /api/pipeline/run + GET /api/pipeline/status/{model_id}.

Cf. ARCHITECTURE §"API Endpoints". Le POST crée un Model en BDD et
schedule le pipeline en BackgroundTask, puis renvoie immédiatement
l'`id`. Le frontend poll ensuite `/status/{id}` toutes les 3s
(cf. SPECS §4.2 PipelineTracker).
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from database import get_db
from engines import get_engine
from models import Model
from tasks import run_pipeline_guarded

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB (SPECS §5 étape 1 + §4.1)
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png"}


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #

class PipelineRunRequest(BaseModel):
    # 5000 chars largement suffisant (prompt utilisateur) et empêche
    # l'abus (spam 10 MB de texte à traiter par Claude).
    input_text: str | None = Field(
        default=None,
        max_length=5000,
        description="Description texte libre (ignoré si image fournie)",
    )
    input_image: str | None = Field(
        default=None,
        description="Image encodée en data URI (data:image/jpeg;base64,...) "
                    "ou base64 brut.",
    )
    engine: str | None = Field(default=None, max_length=50, description="Nom du moteur 3D")
    image_engine: str | None = Field(default=None, max_length=50, description="Nom du moteur image")


class PipelineRunResponse(BaseModel):
    model_id: int


class PipelineStatusResponse(BaseModel):
    model_id: int
    pipeline_status: str
    pipeline_error: str | None
    optimized_prompt: str | None
    engine: str
    validation: str
    qc_score: float | None
    mesh_metrics: dict[str, Any] | None
    qc_details: dict[str, Any] | None
    cost_credits: int


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _decode_image(raw: str) -> tuple[bytes, str]:
    """Décode un data URI ou base64 brut. Retourne (bytes, mime).

    Lève HTTPException 400 si invalide, trop gros, ou format non supporté.
    """
    mime = "image/jpeg"
    b64_data = raw

    if raw.startswith("data:"):
        # "data:image/jpeg;base64,AAAA..."
        try:
            header, b64_data = raw.split(",", 1)
            prefix = header[len("data:"):]
            mime = prefix.split(";", 1)[0].strip().lower() or mime
        except ValueError:
            raise HTTPException(400, "Invalid data URI")

    try:
        data = base64.b64decode(b64_data, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, f"Invalid base64 image: {exc}")

    if mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"Image mime '{mime}' not supported (jpeg/png only)")
    if len(data) == 0:
        raise HTTPException(400, "Empty image")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"Image too large: {len(data)} > {MAX_IMAGE_BYTES} bytes")
    return data, mime


def _save_image(model_id: int, data: bytes, mime: str) -> str:
    """Persiste l'image uploadée et retourne son chemin absolu."""
    ext = ".jpg" if mime == "image/jpeg" else ".png"
    d = config.DATA_DIR / "models" / str(model_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"input{ext}"
    path.write_bytes(data)
    return str(path)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@router.post("/run", response_model=PipelineRunResponse)
async def run(
    payload: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PipelineRunResponse:
    """Crée un Model en BDD et schedule le pipeline en BackgroundTask.

    Règles d'input (SPECS §4.1) :
    - Si `input_image` fourni → input_type = "image", texte ignoré.
    - Sinon `input_text` requis → input_type = "text".
    - Le bouton frontend est disabled sans aucun input, mais on protège
      quand même côté serveur.
    """
    # Résoudre le moteur (défaut depuis settings si absent)
    engine_name = payload.engine or config.DEFAULT_ENGINE
    try:
        engine_obj = get_engine(engine_name)
    except KeyError as exc:
        raise HTTPException(400, str(exc))

    image_engine = payload.image_engine or config.DEFAULT_IMAGE_ENGINE

    # Déterminer le type d'input
    image_data: bytes | None = None
    image_mime = "image/jpeg"
    if payload.input_image:
        if not engine_obj.supports_image_input:
            raise HTTPException(
                400,
                f"Engine '{engine_name}' does not support image input",
            )
        image_data, image_mime = _decode_image(payload.input_image)
        input_type = "image"
    elif payload.input_text and payload.input_text.strip():
        input_type = "text"
    else:
        raise HTTPException(400, "Either input_text or input_image is required")

    # Créer le Model en BDD (on a besoin de l'id pour créer le dossier)
    model = Model(
        input_type=input_type,
        input_text=payload.input_text if input_type == "text" else None,
        engine=engine_name,
        image_engine=image_engine,
        pipeline_status="prompt",
        validation="pending",
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    # Persister l'image sur disque maintenant qu'on a l'id
    if image_data is not None:
        img_path = _save_image(model.id, image_data, image_mime)
        model.input_image_path = img_path
        db.commit()

    logger.info("Pipeline scheduled: model_id=%d, engine=%s, input=%s",
                model.id, engine_name, input_type)

    # Schedule la BackgroundTask — FastAPI await la coroutine après response
    background_tasks.add_task(run_pipeline_guarded, model.id)

    return PipelineRunResponse(model_id=model.id)


@router.get("/status/{model_id}", response_model=PipelineStatusResponse)
def status(model_id: int, db: Session = Depends(get_db)) -> PipelineStatusResponse:
    """Retourne l'état courant du pipeline pour un Model donné.

    Polled par le frontend toutes les 3s (SPECS §4.2). Le polling s'arrête
    côté frontend quand pipeline_status ∈ {pending, done, failed}.
    """
    m = db.get(Model, model_id)
    if m is None:
        raise HTTPException(404, f"Model {model_id} not found")
    return PipelineStatusResponse(
        model_id=m.id,
        pipeline_status=m.pipeline_status,
        pipeline_error=m.pipeline_error,
        optimized_prompt=m.optimized_prompt,
        engine=m.engine,
        validation=m.validation,
        qc_score=m.qc_score,
        mesh_metrics=m.mesh_metrics,
        qc_details=m.qc_details,
        cost_credits=m.cost_credits or 0,
    )

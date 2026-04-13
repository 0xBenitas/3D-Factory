"""Orchestrateur du pipeline — exécuté via FastAPI BackgroundTasks.

Phase 2 du pipeline : étapes 1 → 4 (PROMPT, FORGE, REPAIR, SCORE).
Les étapes 5-7 (VALIDATION, STUDIO, PACK) arrivent en Phase 3/4 : le
pipeline s'arrête à `pipeline_status="pending"` pour validation humaine.

Règles (cf. SPECS §5) :
- Sémaphore global : max 2 pipelines simultanés (évite de spammer les APIs).
- Retry async avec backoff exponentiel pour les erreurs transitoires.
- Chaque erreur met `pipeline_status="failed"` + `pipeline_error=...`.
- Le scoring est best-effort : si Claude échoue, score=None et le
  pipeline continue vers "pending".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

import config
from database import SessionLocal
from engines import get_engine
from engines.base import (
    EngineError,
    EngineTransient,
    InsufficientCredits,
    InvalidApiKey,
    NON_RETRYABLE as ENGINE_NON_RETRYABLE,
    RETRYABLE as ENGINE_RETRYABLE,
    RateLimited,
)
from models import Model
from services import mesh_repair, prompt_optimizer, quality_scorer

logger = logging.getLogger(__name__)

# Concurrency : max 2 pipelines simultanés (SPECS §5 "Pipeline concurrency").
PIPELINE_SEMAPHORE = asyncio.Semaphore(2)

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Retry helper (SPECS §5)
# --------------------------------------------------------------------------- #

async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 2,
    backoff_base: float = 5.0,
    retry_on: tuple[type[BaseException], ...] = ENGINE_RETRYABLE,
    non_retryable: tuple[type[BaseException], ...] = ENGINE_NON_RETRYABLE,
    **kwargs: Any,
) -> T:
    """Appelle `func(*args, **kwargs)` avec retry + backoff exponentiel.

    Par défaut (pour engines) :
    - max_retries = 2 (donc 3 tentatives)
    - backoff : 5s → 10s → 20s
    - Retry sur ENGINE_RETRYABLE = (RateLimited, EngineTransient)
    - Pas de retry sur ENGINE_NON_RETRYABLE = (InvalidApiKey,
      InsufficientCredits, EngineTaskFailed, NotSupported)

    L'ordre des except matters : les non_retryable sont checkés AVANT
    retry_on pour qu'une exception listée dans les deux (cas de
    sous-classes) soit traitée comme permanente.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except non_retryable:
            raise
        except retry_on as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            wait = backoff_base * (2 ** attempt)
            logger.warning(
                "%s attempt %d/%d failed (%s), retrying in %.0fs",
                getattr(func, "__name__", "call"),
                attempt + 1, max_retries + 1, exc, wait,
            )
            await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc


# --------------------------------------------------------------------------- #
# Helpers DB
# --------------------------------------------------------------------------- #

def _update_model(
    model_id: int,
    **fields: Any,
) -> None:
    """Applique un update sur le Model ciblé dans une session courte.

    Les BackgroundTasks partagent des sessions différentes du thread web.
    On ouvre/ferme à chaque update pour éviter les sessions longues.
    """
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            logger.error("Model %d not found for update", model_id)
            return
        for k, v in fields.items():
            setattr(m, k, v)
        db.commit()


def _fail(model_id: int, error_msg: str) -> None:
    logger.error("Pipeline #%d FAILED: %s", model_id, error_msg)
    _update_model(
        model_id,
        pipeline_status="failed",
        pipeline_error=error_msg[:2000],
    )


# --------------------------------------------------------------------------- #
# Pipeline principal
# --------------------------------------------------------------------------- #

async def run_pipeline(model_id: int) -> None:
    """Orchestre les étapes 1-4 du pipeline pour un Model donné.

    Lit l'état initial depuis la BDD (input_text/image, engine choisi),
    écrit le statut + résultats au fil de l'eau.

    Cette coroutine est conçue pour être lancée dans un `BackgroundTask`.
    """
    async with PIPELINE_SEMAPHORE:
        try:
            await _run_pipeline_inner(model_id)
        except Exception as exc:
            # Garde-fou absolu : si quoi que ce soit remonte, on marque failed.
            _fail(model_id, f"Unhandled pipeline error: {exc}")
            logger.exception("Pipeline #%d crashed", model_id)


async def _run_pipeline_inner(model_id: int) -> None:
    # Charger l'état initial
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            logger.error("Model %d not found at pipeline start", model_id)
            return
        input_text = m.input_text
        input_image_path = m.input_image_path
        input_type = m.input_type
        engine_name = m.engine

    logger.info("Pipeline #%d start (engine=%s, input=%s)",
                model_id, engine_name, input_type)

    # ----- Étape 1 : PROMPT -------------------------------------------------
    _update_model(model_id, pipeline_status="prompt")
    try:
        if input_type == "image" and input_image_path:
            optimized = await retry_async(
                prompt_optimizer.optimize_from_image,
                input_image_path, engine_name,
                retry_on=(prompt_optimizer.PromptOptimizerError,),
                non_retryable=prompt_optimizer.NON_RETRYABLE,
            )
        else:
            optimized = await retry_async(
                prompt_optimizer.optimize_from_text,
                input_text or "", engine_name,
                retry_on=(prompt_optimizer.PromptOptimizerError,),
                non_retryable=prompt_optimizer.NON_RETRYABLE,
            )
    except Exception as exc:
        _fail(model_id, f"Prompt optimization failed: {exc}")
        return
    _update_model(model_id, optimized_prompt=optimized)

    # ----- Étape 2 : FORGE --------------------------------------------------
    _update_model(model_id, pipeline_status="generating")
    try:
        engine = get_engine(engine_name)
    except KeyError as exc:
        _fail(model_id, str(exc))
        return

    model_dir = config.DATA_DIR / "models" / str(model_id)
    try:
        gen_result = await retry_async(
            engine.generate,
            optimized,
            input_image_path if input_type == "image" else None,
            str(model_dir),
        )
    except (InvalidApiKey, InsufficientCredits) as exc:
        _fail(model_id, f"Engine refused: {exc}")
        return
    except Exception as exc:
        _fail(model_id, f"Engine generation failed: {exc}")
        return

    _update_model(
        model_id,
        glb_path=gen_result.glb_path,
        engine_task_id=gen_result.engine_task_id,
        cost_credits=gen_result.cost_credits,
    )
    logger.info("Pipeline #%d: .glb generated in %.1fs",
                model_id, gen_result.generation_time_s)

    # ----- Étape 3 : REPAIR -------------------------------------------------
    _update_model(model_id, pipeline_status="repairing")
    stl_path = str(model_dir / "model.stl")
    try:
        # mesh_repair est synchrone (CPU-bound). On l'exécute dans un thread
        # pour ne pas bloquer la loop FastAPI ni le semaphore.
        repair_result = await asyncio.to_thread(
            mesh_repair.analyze_and_repair, gen_result.glb_path, stl_path
        )
    except mesh_repair.MeshRepairError as exc:
        _fail(model_id, f"Mesh repair failed: {exc}")
        return

    _update_model(
        model_id,
        stl_path=repair_result["stl_path"],
        mesh_metrics=repair_result["mesh_metrics"],
        repair_log=repair_result["repair_log"],
    )

    # ----- Étape 4 : SCORE (best-effort) ------------------------------------
    _update_model(model_id, pipeline_status="scoring")
    object_desc = input_text or "(photo input)"
    try:
        score_result = await quality_scorer.score_mesh(
            repair_result["mesh_metrics"], object_desc
        )
    except Exception as exc:
        # Double sécurité — quality_scorer est censé ne jamais lever.
        logger.warning("Pipeline #%d: scoring crashed: %s", model_id, exc)
        score_result = quality_scorer.QualityScoreResult()

    _update_model(
        model_id,
        qc_score=score_result.score,
        qc_details={
            "criteria": score_result.criteria,
            "summary": score_result.summary,
        } if score_result.criteria or score_result.summary else None,
    )

    # ----- Pipeline en attente de validation humaine ------------------------
    _update_model(model_id, pipeline_status="pending")
    logger.info("Pipeline #%d DONE (status=pending, score=%s)",
                model_id, score_result.score)


# --------------------------------------------------------------------------- #
# Garde anti-doublon : évite deux pipelines parallèles sur le même model_id.
# --------------------------------------------------------------------------- #

_running_ids: set[int] = set()
_running_lock = asyncio.Lock()


async def run_pipeline_guarded(model_id: int) -> None:
    """Point d'entrée appelé depuis `BackgroundTasks`.

    Refuse de lancer un pipeline déjà en cours sur ce modèle (sécurité
    supplémentaire si l'utilisateur spam le POST /regenerate).

    FastAPI BackgroundTasks gère nativement les coroutines : elles sont
    awaitées sur la loop principale après l'envoi de la réponse.
    """
    async with _running_lock:
        if model_id in _running_ids:
            logger.warning("Pipeline #%d already running, skipping", model_id)
            return
        _running_ids.add(model_id)
    try:
        await run_pipeline(model_id)
    finally:
        async with _running_lock:
            _running_ids.discard(model_id)

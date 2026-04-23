"""Orchestrateur du pipeline — exécuté via FastAPI BackgroundTasks.

- Pipeline génération (étapes 1-4) : `run_pipeline_guarded`.
- Pipeline remesh (sous-cas de FORGE + REPAIR + SCORE) : `run_remesh_guarded`.
- Pipeline export (étapes 6-7 : STUDIO + PACK) : `run_export_guarded`,
  déclenché par POST /api/exports/generate après validation humaine.

Règles (cf. SPECS §5) :
- Sémaphore global : max 2 pipelines simultanés (évite de spammer les APIs).
- Retry async avec backoff exponentiel pour les erreurs transitoires.
- Chaque erreur fatale met `pipeline_status="failed"` + `pipeline_error=...`.
- Le scoring est best-effort : si Claude échoue, score=None et le
  pipeline continue vers "pending".
- L'export est best-effort par sous-étape : screenshots ou photos qui
  échouent ne bloquent pas le PACK (SPECS §5 étape 6). Seul le packaging
  STL est fatal.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

import config
import costs
from database import SessionLocal
from engines import get_engine
from engines.base import (
    CancelledByUser,
    EngineError,
    EngineTransient,
    InsufficientCredits,
    InvalidApiKey,
    NON_RETRYABLE as ENGINE_NON_RETRYABLE,
    RETRYABLE as ENGINE_RETRYABLE,
    RateLimited,
)
from image_engines import get_image_engine
from image_engines.base import (
    NON_RETRYABLE as IMAGE_NON_RETRYABLE,
    RETRYABLE as IMAGE_RETRYABLE,
)
from models import Export, Model
from services import mesh_repair, packager, prompt_optimizer, quality_scorer, screenshot, seo_gen
from templates import get_template

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


def _cancelled(model_id: int) -> None:
    """Marque le pipeline comme annulé (statut terminal, pas d'erreur)."""
    logger.info("Pipeline #%d CANCELLED by user", model_id)
    _update_model(
        model_id,
        pipeline_status="cancelled",
        pipeline_error=None,
        pipeline_progress=None,
    )


def _is_cancel_requested(model_id: int) -> bool:
    """Lit le flag `cancel_requested` dans une session courte."""
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        return bool(m and m.cancel_requested)


def _set_progress(model_id: int, pct: int) -> None:
    _update_model(model_id, pipeline_progress=max(0, min(100, int(pct))))


def _add_eur_cost(model_id: int, amount: float) -> None:
    """Incrémente `cost_eur_estimate` (cumulé sur la vie du modèle).

    Utilisé par chaque étape facturante pour que `GET /api/stats` et le
    CostTracker frontend puissent afficher un total réaliste.
    """
    if amount <= 0:
        return
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            return
        m.cost_eur_estimate = round((m.cost_eur_estimate or 0.0) + amount, 4)
        db.commit()


# --------------------------------------------------------------------------- #
# Pipeline principal
# --------------------------------------------------------------------------- #

async def run_pipeline(model_id: int, prompt_override: str | None = None) -> None:
    """Orchestre les étapes 1-4 du pipeline pour un Model donné.

    Si `prompt_override` est fourni, saute l'étape 1 (PROMPT) et utilise
    ce prompt directement (cas du regenerate avec prompt édité par
    l'utilisateur).
    """
    async with PIPELINE_SEMAPHORE:
        try:
            await _run_pipeline_inner(model_id, prompt_override=prompt_override)
        except CancelledByUser:
            _cancelled(model_id)
        except Exception as exc:
            # Garde-fou absolu : si quoi que ce soit remonte, on marque failed.
            _fail(model_id, f"Unhandled pipeline error: {exc}")
            logger.exception("Pipeline #%d crashed", model_id)


async def run_remesh_pipeline(model_id: int, target_polycount: int) -> None:
    """Remesh un modèle existant : saute PROMPT + FORGE, utilise
    `engine_task_id` existant pour appeler `engine.remesh()`, puis
    ré-exécute REPAIR + SCORE sur le nouveau .glb.
    """
    async with PIPELINE_SEMAPHORE:
        try:
            await _run_remesh_inner(model_id, target_polycount)
        except CancelledByUser:
            _cancelled(model_id)
        except Exception as exc:
            _fail(model_id, f"Unhandled remesh error: {exc}")
            logger.exception("Remesh #%d crashed", model_id)


async def _run_pipeline_inner(
    model_id: int,
    prompt_override: str | None = None,
) -> None:
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

    logger.info("Pipeline #%d start (engine=%s, input=%s, prompt_override=%s)",
                model_id, engine_name, input_type, bool(prompt_override))

    # ----- Étape 1 : PROMPT -------------------------------------------------
    if prompt_override:
        # Regenerate avec prompt édité : on saute l'optimisation et
        # on utilise directement la version fournie par l'utilisateur.
        optimized = prompt_override[:600]
    else:
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
        _add_eur_cost(model_id, costs.PROMPT_OPTIMIZE_EUR)
    _update_model(model_id, optimized_prompt=optimized)

    # Vérif annulation avant de démarrer une étape coûteuse.
    if _is_cancel_requested(model_id):
        raise CancelledByUser("cancelled before generation")

    # ----- Étape 2 : FORGE --------------------------------------------------
    _update_model(model_id, pipeline_status="generating", pipeline_progress=0)
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
            progress_callback=lambda p, mid=model_id: _set_progress(mid, p),
            cancel_check=lambda mid=model_id: _is_cancel_requested(mid),
        )
    except CancelledByUser:
        raise
    except (InvalidApiKey, InsufficientCredits) as exc:
        _fail(model_id, f"Engine refused: {exc}")
        return
    except Exception as exc:
        _fail(model_id, f"Engine generation failed: {exc}")
        return
    finally:
        _update_model(model_id, pipeline_progress=None)

    # Cumul des crédits (utile pour les regenerate / remesh multiples).
    _add_cost_and_set_paths(
        model_id,
        glb_path=gen_result.glb_path,
        engine_task_id=gen_result.engine_task_id,
        extra_credits=gen_result.cost_credits,
    )
    _add_eur_cost(model_id, costs.engine_generate_eur(engine_name))
    logger.info("Pipeline #%d: .glb generated in %.1fs",
                model_id, gen_result.generation_time_s)

    # ----- Étapes 3 + 4 : REPAIR + SCORE -----------------------------------
    await _run_repair_and_score(model_id, gen_result.glb_path, model_dir,
                                object_desc=input_text or "(photo input)")


async def _run_remesh_inner(model_id: int, target_polycount: int) -> None:
    # Charger l'état
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            logger.error("Model %d not found for remesh", model_id)
            return
        engine_name = m.engine
        engine_task_id = m.engine_task_id
        input_text = m.input_text

    if not engine_task_id:
        _fail(model_id, "Cannot remesh: no engine_task_id (original generation missing)")
        return

    logger.info("Remesh #%d start (engine=%s, target=%d)",
                model_id, engine_name, target_polycount)

    if _is_cancel_requested(model_id):
        raise CancelledByUser("cancelled before remesh")

    # ----- FORGE (remesh) ---------------------------------------------------
    _update_model(
        model_id,
        pipeline_status="generating",
        pipeline_error=None,
        pipeline_progress=0,
    )
    try:
        engine = get_engine(engine_name)
    except KeyError as exc:
        _fail(model_id, str(exc))
        return

    model_dir = config.DATA_DIR / "models" / str(model_id)
    try:
        gen_result = await retry_async(
            engine.remesh,
            engine_task_id,
            target_polycount,
            str(model_dir),
            progress_callback=lambda p, mid=model_id: _set_progress(mid, p),
            cancel_check=lambda mid=model_id: _is_cancel_requested(mid),
        )
    except CancelledByUser:
        raise
    except (InvalidApiKey, InsufficientCredits) as exc:
        _fail(model_id, f"Engine refused: {exc}")
        return
    except Exception as exc:
        _fail(model_id, f"Engine remesh failed: {exc}")
        return
    finally:
        _update_model(model_id, pipeline_progress=None)

    _add_cost_and_set_paths(
        model_id,
        glb_path=gen_result.glb_path,
        engine_task_id=gen_result.engine_task_id,
        extra_credits=gen_result.cost_credits,
    )
    _add_eur_cost(model_id, costs.engine_remesh_eur(engine_name))

    await _run_repair_and_score(model_id, gen_result.glb_path, model_dir,
                                object_desc=input_text or "(remeshed)")


async def _run_repair_and_score(
    model_id: int,
    glb_path: str,
    model_dir: "Path",
    object_desc: str,
) -> None:
    """Étapes 3 + 4 (REPAIR + SCORE) + transition "pending".

    Extrait pour être partagé entre run_pipeline et run_remesh_pipeline.
    """
    if _is_cancel_requested(model_id):
        raise CancelledByUser("cancelled before repair")
    _update_model(model_id, pipeline_status="repairing")
    stl_path = str(model_dir / "model.stl")
    try:
        # CPU-bound → thread pour ne pas bloquer la loop ni le semaphore.
        repair_result = await asyncio.to_thread(
            mesh_repair.analyze_and_repair, glb_path, stl_path
        )
    except mesh_repair.MeshRepairError as exc:
        _fail(model_id, f"Mesh repair failed: {exc}")
        return

    # Même borne que `pipeline_error` : les logs de repair peuvent gonfler
    # si pymeshfix/trimesh enchaînent des warnings — on cappe pour garder
    # la table légère.
    repair_log_raw = repair_result["repair_log"] or ""
    _update_model(
        model_id,
        stl_path=repair_result["stl_path"],
        mesh_metrics=repair_result["mesh_metrics"],
        repair_log=repair_log_raw[:2000],
    )

    # Thumbnail (~500ms CPU) — non-bloquant : si pyrender plante on
    # continue, la grille affiche juste le placeholder. Chemin
    # déterministe pour ne pas alourdir le schéma DB.
    try:
        thumb_path = str(model_dir / "thumb.png")
        await asyncio.to_thread(
            screenshot.generate_thumbnail, glb_path, thumb_path, 256,
        )
    except Exception as exc:
        logger.warning("Pipeline #%d: thumbnail skipped: %s", model_id, exc)

    _update_model(model_id, pipeline_status="scoring")
    try:
        score_result = await quality_scorer.score_mesh(
            repair_result["mesh_metrics"], object_desc
        )
    except Exception as exc:
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
    if score_result.score is not None:
        _add_eur_cost(model_id, costs.SCORING_EUR)

    _update_model(model_id, pipeline_status="pending")
    logger.info("Pipeline #%d DONE (status=pending, score=%s)",
                model_id, score_result.score)


def _add_cost_and_set_paths(
    model_id: int,
    *,
    glb_path: str,
    engine_task_id: str,
    extra_credits: int,
) -> None:
    """Met à jour glb_path + engine_task_id et incrémente cost_credits."""
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            return
        m.glb_path = glb_path
        m.engine_task_id = engine_task_id
        m.cost_credits = (m.cost_credits or 0) + extra_credits
        db.commit()


# --------------------------------------------------------------------------- #
# Pipeline export (étapes 6-7 : STUDIO + PACK)
# --------------------------------------------------------------------------- #

# Fallback lifestyle prompt si Claude échoue : assez générique pour que
# Stability sorte quelque chose d'utilisable.
_LIFESTYLE_FALLBACK = (
    "3D printed white {desc}, soft natural light, minimal background, "
    "product photography"
)


async def run_export_pipeline(model_id: int, template_name: str) -> None:
    """Orchestre les étapes 6-7 pour un modèle approuvé.

    Pré-requis : model.validation == "approved" + stl_path + glb_path +
    mesh_metrics. C'est le router qui vérifie ces invariants.
    """
    async with PIPELINE_SEMAPHORE:
        try:
            await _run_export_inner(model_id, template_name)
        except Exception as exc:
            _fail(model_id, f"Unhandled export error: {exc}")
            logger.exception("Export pipeline #%d crashed", model_id)


async def _run_export_inner(model_id: int, template_name: str) -> None:
    # Snapshot de l'état (les BackgroundTasks sont hors session web).
    with SessionLocal() as db:
        m = db.get(Model, model_id)
        if m is None:
            logger.error("Model %d not found for export", model_id)
            return
        input_text = m.input_text or "(photo input)"
        stl_path = m.stl_path
        glb_path = m.glb_path
        mesh_metrics = m.mesh_metrics or {}
        image_engine_name = m.image_engine or config.DEFAULT_IMAGE_ENGINE

    if not stl_path or not glb_path or not mesh_metrics:
        _fail(model_id, "Cannot export: model missing stl_path/glb_path/mesh_metrics")
        return

    try:
        template = get_template(template_name)
    except KeyError as exc:
        _fail(model_id, str(exc))
        return

    screenshots_dir = config.DATA_DIR / "screenshots" / str(model_id)
    photos_dir = config.DATA_DIR / "photos" / str(model_id)
    exports_dir = config.DATA_DIR / "exports"

    logger.info("Export pipeline #%d start (template=%s, image_engine=%s)",
                model_id, template_name, image_engine_name)

    # ----- Étape 6 : STUDIO ------------------------------------------------- #
    _update_model(model_id, pipeline_status="photos", pipeline_error=None)

    # 6a) Screenshots — non bloquant (SPECS §5 étape 6 "pyrender fail").
    screenshot_paths: list[str] = []
    try:
        screenshot_paths = await asyncio.to_thread(
            screenshot.generate_screenshots,
            glb_path, str(screenshots_dir),
        )
    except screenshot.ScreenshotError as exc:
        logger.warning("Export #%d: screenshots skipped: %s", model_id, exc)

    # 6b) Prompt lifestyle — fallback si Claude échoue.
    lifestyle_ok = False
    try:
        lifestyle_prompt = await retry_async(
            seo_gen.generate_lifestyle_prompt,
            input_text,
            retry_on=(seo_gen.SeoGenError,),
            non_retryable=seo_gen.NON_RETRYABLE,
        )
        lifestyle_ok = True
    except Exception as exc:
        logger.warning("Export #%d: lifestyle prompt failed, fallback: %s", model_id, exc)
        lifestyle_prompt = _LIFESTYLE_FALLBACK.format(desc=input_text[:120])
    if lifestyle_ok:
        _add_eur_cost(model_id, costs.LIFESTYLE_PROMPT_EUR)

    # 6c) Photos — non bloquant (SPECS §5 étape 6).
    photo_paths: list[str] = []
    try:
        image_engine = get_image_engine(image_engine_name)
    except KeyError as exc:
        logger.warning("Export #%d: image engine unknown, skipping photos: %s",
                       model_id, exc)
        image_engine = None

    if image_engine is not None:
        try:
            photo_paths = await retry_async(
                image_engine.generate,
                lifestyle_prompt, str(photos_dir), 3, None,
                retry_on=IMAGE_RETRYABLE,
                non_retryable=IMAGE_NON_RETRYABLE,
            )
        except Exception as exc:
            logger.warning("Export #%d: photos failed (non-blocking): %s",
                           model_id, exc)
        # Facturer uniquement les photos réellement livrées.
        if photo_paths:
            _add_eur_cost(model_id, costs.STABILITY_PER_IMAGE_EUR * len(photo_paths))

    _update_model(
        model_id,
        screenshot_paths=screenshot_paths or None,
        photo_paths=photo_paths or None,
    )

    # ----- Étape 7 : PACK --------------------------------------------------- #
    _update_model(model_id, pipeline_status="packing")

    # 7a) Listing SEO — fallback minimal si Claude échoue (SPECS §5 étape 7).
    listing_ok = False
    try:
        listing = await retry_async(
            seo_gen.generate_listing,
            input_text, mesh_metrics, template.name,
            template.max_title_length, template.max_description_length,
            template.max_tags, template.tone,
            retry_on=(seo_gen.SeoGenError,),
            non_retryable=seo_gen.NON_RETRYABLE,
        )
        listing_ok = True
    except Exception as exc:
        logger.warning("Export #%d: listing failed, using fallback: %s", model_id, exc)
        listing = {
            "title": f"Model #{model_id}",
            "description": input_text,
            "tags": [],
            "price_eur": 0.0,
        }
    if listing_ok:
        _add_eur_cost(model_id, costs.LISTING_EUR)

    # 7b) Print params — fallback aux defaults si Claude échoue.
    print_params_ok = False
    try:
        print_params = await retry_async(
            seo_gen.generate_print_params,
            input_text, mesh_metrics,
            retry_on=(seo_gen.SeoGenError,),
            non_retryable=seo_gen.NON_RETRYABLE,
        )
        print_params_ok = True
    except Exception as exc:
        logger.warning("Export #%d: print_params failed, using defaults: %s",
                       model_id, exc)
        print_params = dict(seo_gen.DEFAULT_PRINT_PARAMS)
    if print_params_ok:
        _add_eur_cost(model_id, costs.PRINT_PARAMS_EUR)

    # 7c) Packaging ZIP — fatal si échec (on ne peut pas livrer sans).
    listing_text = template.format_listing(listing, print_params)
    try:
        zip_path = await asyncio.to_thread(
            packager.build_zip,
            model_id, stl_path, photo_paths, listing_text,
            listing["title"], str(exports_dir),
        )
    except packager.PackagerError as exc:
        _fail(model_id, f"Packaging failed: {exc}")
        return

    # 7d) Persister l'Export en BDD.
    with SessionLocal() as db:
        ex = Export(
            model_id=model_id,
            template=template.name,
            title=listing["title"],
            description=listing["description"],
            tags=listing["tags"],
            price_suggested=listing["price_eur"],
            print_params=print_params,
            zip_path=zip_path,
        )
        db.add(ex)
        db.commit()

    _update_model(model_id, pipeline_status="done")
    logger.info("Export pipeline #%d DONE (zip=%s)", model_id, zip_path)


# --------------------------------------------------------------------------- #
# Garde anti-doublon : évite deux pipelines parallèles sur le même model_id.
# --------------------------------------------------------------------------- #

_running_ids: set[int] = set()
_running_lock = asyncio.Lock()


async def run_pipeline_guarded(
    model_id: int,
    prompt_override: str | None = None,
) -> None:
    """Lance `run_pipeline` avec anti-doublon sur model_id."""
    if not await _acquire(model_id):
        return
    try:
        await run_pipeline(model_id, prompt_override=prompt_override)
    finally:
        await _release(model_id)


async def run_remesh_guarded(model_id: int, target_polycount: int) -> None:
    """Lance `run_remesh_pipeline` avec anti-doublon sur model_id."""
    if not await _acquire(model_id):
        return
    try:
        await run_remesh_pipeline(model_id, target_polycount)
    finally:
        await _release(model_id)


async def run_export_guarded(model_id: int, template_name: str) -> None:
    """Lance `run_export_pipeline` avec anti-doublon sur model_id."""
    if not await _acquire(model_id):
        return
    try:
        await run_export_pipeline(model_id, template_name)
    finally:
        await _release(model_id)


async def _acquire(model_id: int) -> bool:
    async with _running_lock:
        if model_id in _running_ids:
            logger.warning("Pipeline #%d already running, skipping", model_id)
            return False
        _running_ids.add(model_id)
        return True


async def _release(model_id: int) -> None:
    async with _running_lock:
        _running_ids.discard(model_id)

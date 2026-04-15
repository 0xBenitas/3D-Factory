"""Moteur 3D Meshy (https://docs.meshy.ai/en/api).

Mode utilisé : **preview** (géométrie only, pas de texture) via meshy-5
→ 5 crédits/génération (~$0.10). Cf. ARCHITECTURE §"Coûts par modèle".

Endpoints couverts :
- POST /openapi/v2/text-to-3d  (mode preview)
- POST /openapi/v2/image-to-3d
- GET  /openapi/v2/{text-to-3d|image-to-3d}/{task_id}
- POST /openapi/v2/remesh
- GET  /openapi/v2/remesh/{task_id}
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import time
from pathlib import Path

import httpx

import config
from engines import register
from engines.base import (
    CancelCheck,
    CancelledByUser,
    Engine3D,
    EngineTaskFailed,
    EngineTransient,
    GenerationResult,
    InsufficientCredits,
    InvalidApiKey,
    NotSupported,
    ProgressCallback,
    RateLimited,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.meshy.ai/openapi/v2"
REMESH_BASE_URL = "https://api.meshy.ai/openapi/v1"  # /remesh n'existe pas en v2
AI_MODEL = "meshy-5"            # cf. SPECS §2.1 — 5 crédits preview
TARGET_POLYCOUNT = 30000        # défaut Meshy
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300            # 5 min max par task (cf. SPECS §5)
COST_CREDITS_PREVIEW = 5        # meshy-5 preview
COST_CREDITS_REMESH = 5


# --------------------------------------------------------------------------- #
# Helpers HTTP
# --------------------------------------------------------------------------- #

def _headers() -> dict[str, str]:
    key = config.get_api_key("meshy")
    if not key:
        raise InvalidApiKey("MESHY_API_KEY not configured (set it in Settings)")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    """Traduit un httpx.Response en exception typée Engine*.

    - 401 → InvalidApiKey (permanent)
    - 402 → InsufficientCredits (permanent)
    - 429 → RateLimited (retryable)
    - 5xx → EngineTransient (retryable — erreur serveur passagère)
    - autres 4xx → EngineTaskFailed (permanent — bad request, malformé, etc.)
    """
    if resp.status_code == 401:
        raise InvalidApiKey(f"Meshy 401 ({context}): invalid API key")
    if resp.status_code == 402:
        raise InsufficientCredits(f"Meshy 402 ({context}): insufficient credits")
    if resp.status_code == 429:
        raise RateLimited(f"Meshy 429 ({context}): rate limited")
    if resp.status_code >= 500:
        raise EngineTransient(f"Meshy {resp.status_code} ({context}): server error")
    if resp.status_code >= 400:
        raise EngineTaskFailed(
            f"Meshy {resp.status_code} ({context}): {resp.text[:500]}"
        )


async def _poll_task(
    client: httpx.AsyncClient,
    task_id: str,
    endpoint: str,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict:
    """Poll une task Meshy jusqu'à SUCCEEDED / FAILED / timeout.

    `endpoint` : "text-to-3d", "image-to-3d", ou "remesh".
    Le remesh vit sur l'API v1 (pas de /remesh en v2).
    `progress_callback(pct)` est appelé à chaque poll avec le `progress` (0-100).
    Si `cancel_check()` renvoie True, lève `CancelledByUser`.
    """
    base = REMESH_BASE_URL if endpoint == "remesh" else BASE_URL
    url = f"{base}/{endpoint}/{task_id}"
    start = time.monotonic()
    while True:
        if cancel_check is not None and cancel_check():
            raise CancelledByUser(f"Meshy task {task_id} cancelled by user")
        elapsed = time.monotonic() - start
        if elapsed > POLL_TIMEOUT_S:
            raise EngineTaskFailed(
                f"Meshy task {task_id} timed out after {POLL_TIMEOUT_S}s"
            )
        resp = await client.get(url, headers=_headers())
        _raise_for_status(resp, f"poll {endpoint}")
        data = resp.json()
        status = data.get("status")
        if progress_callback is not None:
            pct = data.get("progress")
            if isinstance(pct, (int, float)):
                try:
                    progress_callback(int(pct))
                except Exception:
                    pass  # ne jamais casser le poll pour un bug de callback
        if status == "SUCCEEDED":
            return data
        if status == "FAILED":
            msg = (data.get("task_error") or {}).get("message") or "unknown"
            raise EngineTaskFailed(f"Meshy task {task_id} FAILED: {msg}")
        await asyncio.sleep(POLL_INTERVAL_S)


async def _download_glb(url: str, output_path: Path) -> None:
    """Télécharge le .glb final."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
    if output_path.stat().st_size == 0:
        raise EngineTaskFailed(f"Downloaded .glb is empty ({output_path})")


def _image_to_data_uri(image_path: str) -> str:
    """Convertit une image locale en data URI pour `image_url` de Meshy."""
    p = Path(image_path)
    mime, _ = mimetypes.guess_type(p.name)
    mime = mime or "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


# --------------------------------------------------------------------------- #
# Implémentation
# --------------------------------------------------------------------------- #

class MeshyEngine(Engine3D):
    name = "meshy"
    supports_image_input = True

    async def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        output_dir: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> GenerationResult:
        start = time.monotonic()

        if image_path:
            payload = {
                "image_url": _image_to_data_uri(image_path),
                "ai_model": AI_MODEL,
                "should_texture": False,             # géo only
                "topology": "triangle",
                "target_polycount": TARGET_POLYCOUNT,
                "should_remesh": True,
            }
            endpoint = "image-to-3d"
        else:
            # Garde défensive : prompt_optimizer tronque déjà à 600, mais
            # un appel direct pourrait outrepasser la limite Meshy.
            prompt = prompt[:600] if len(prompt) > 600 else prompt
            payload = {
                "mode": "preview",
                "prompt": prompt,
                "ai_model": AI_MODEL,
                "topology": "triangle",
                "target_polycount": TARGET_POLYCOUNT,
                "should_remesh": True,
            }
            endpoint = "text-to-3d"

        async with httpx.AsyncClient(timeout=60) as client:
            # 1) Enqueue
            resp = await client.post(
                f"{BASE_URL}/{endpoint}", headers=_headers(), json=payload
            )
            _raise_for_status(resp, f"create {endpoint}")
            task_id = resp.json().get("result")
            if not task_id:
                raise EngineTaskFailed(f"Meshy {endpoint}: no task_id in response")
            logger.info("Meshy %s task created: %s", endpoint, task_id)

            # 2) Poll
            data = await _poll_task(
                client, task_id, endpoint,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        # 3) Download
        glb_url = (data.get("model_urls") or {}).get("glb")
        if not glb_url:
            raise EngineTaskFailed(f"Meshy task {task_id} SUCCEEDED but no glb url")
        out_dir = Path(output_dir) if output_dir else config.DATA_DIR / "models" / "_tmp"
        glb_path = out_dir / "model.glb"
        await _download_glb(glb_url, glb_path)

        return GenerationResult(
            glb_path=str(glb_path),
            engine_task_id=task_id,
            cost_credits=COST_CREDITS_PREVIEW,
            generation_time_s=time.monotonic() - start,
        )

    async def remesh(
        self,
        engine_task_id: str,
        target_polycount: int,
        output_dir: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> GenerationResult:
        start = time.monotonic()
        payload = {
            "input_task_id": engine_task_id,
            "target_polycount": target_polycount,
            "target_formats": ["glb", "stl"],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{REMESH_BASE_URL}/remesh", headers=_headers(), json=payload
            )
            _raise_for_status(resp, "create remesh")
            task_id = resp.json().get("result")
            if not task_id:
                raise EngineTaskFailed("Meshy remesh: no task_id in response")
            logger.info("Meshy remesh task created: %s", task_id)
            data = await _poll_task(
                client, task_id, "remesh",
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        glb_url = (data.get("model_urls") or {}).get("glb")
        if not glb_url:
            raise EngineTaskFailed(f"Meshy remesh {task_id}: no glb url")
        out_dir = Path(output_dir) if output_dir else config.DATA_DIR / "models" / "_tmp"
        glb_path = out_dir / "model.glb"
        await _download_glb(glb_url, glb_path)

        return GenerationResult(
            glb_path=str(glb_path),
            engine_task_id=task_id,
            cost_credits=COST_CREDITS_REMESH,
            generation_time_s=time.monotonic() - start,
        )


# Enregistrement automatique au chargement du module.
register(MeshyEngine())

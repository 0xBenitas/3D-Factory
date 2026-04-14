"""Moteur image Stability AI — Stable Image Core (text-to-image).

SPECS §2.2 : text-to-image (pas img2img — le screenshot d'un modèle sans
texture donne un résultat bizarre en img2img). 3 photos × 3 crédits =
~$0.09/modèle.

Endpoint : POST /v2beta/stable-image/generate/core (multipart/form-data).
Doc : https://platform.stability.ai/docs
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

import config
from image_engines import register
from image_engines.base import (
    ImageEngine,
    ImageEngineAuthError,
    ImageEngineInsufficientCredits,
    ImageEngineRateLimited,
    ImageEngineRefused,
    ImageEngineTransient,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.stability.ai/v2beta/stable-image/generate/core"
TIMEOUT_S = 60
DEFAULT_ASPECT = "16:9"
DEFAULT_FORMAT = "png"


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    """Traduit un httpx.Response en exception typée ImageEngine*.

    - 401 → ImageEngineAuthError (permanent)
    - 402 → ImageEngineInsufficientCredits (permanent)
    - 429 → ImageEngineRateLimited (retryable)
    - 5xx → ImageEngineTransient (retryable)
    - autres 4xx → ImageEngineRefused (permanent — safety/bad request)
    """
    if resp.status_code == 401:
        raise ImageEngineAuthError(f"Stability 401 ({context}): invalid API key")
    if resp.status_code == 402:
        raise ImageEngineInsufficientCredits(
            f"Stability 402 ({context}): insufficient credits"
        )
    if resp.status_code == 429:
        raise ImageEngineRateLimited(f"Stability 429 ({context}): rate limited")
    if resp.status_code >= 500:
        raise ImageEngineTransient(
            f"Stability {resp.status_code} ({context}): server error"
        )
    if resp.status_code >= 400:
        raise ImageEngineRefused(
            f"Stability {resp.status_code} ({context}): {resp.text[:500]}"
        )


class StabilityEngine(ImageEngine):
    name = "stability"

    async def generate(
        self,
        context_prompt: str,
        output_dir: str,
        n_images: int = 3,
        screenshot_path: str | None = None,  # ignoré (text-to-image)
    ) -> list[str]:
        if not config.STABILITY_API_KEY:
            raise ImageEngineAuthError("STABILITY_API_KEY not configured in .env")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "Authorization": f"Bearer {config.STABILITY_API_KEY}",
            "Accept": "image/*",
        }

        paths: list[str] = []
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for i in range(1, n_images + 1):
                data = {
                    "prompt": context_prompt,
                    "output_format": DEFAULT_FORMAT,
                    "aspect_ratio": DEFAULT_ASPECT,
                }
                # L'endpoint exige multipart/form-data même pour le pur
                # text-to-image : on envoie un champ `none` vide pour
                # forcer httpx à sérialiser en multipart.
                resp = await client.post(
                    ENDPOINT,
                    headers=headers,
                    data=data,
                    files={"none": ""},
                )
                _raise_for_status(resp, f"photo {i}/{n_images}")

                path = out_dir / f"photo_{i}.png"
                path.write_bytes(resp.content)
                if path.stat().st_size == 0:
                    raise ImageEngineTransient(
                        f"Stability returned empty image (photo {i})"
                    )
                paths.append(str(path))
                logger.info(
                    "Stability generated photo %d/%d → %s (%d bytes)",
                    i, n_images, path, path.stat().st_size,
                )

        return paths


register(StabilityEngine())

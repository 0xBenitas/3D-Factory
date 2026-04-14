"""Étape 7b : assemble le ZIP final (stl + photos + listing.txt).

Cf. SPECS §7 PACK.

Structure du ZIP :
    {model_id}_{slug_titre}.zip
    ├── model.stl
    ├── photo_1.png
    ├── photo_2.png
    ├── ...
    └── listing.txt

Le nom du ZIP inclut l'id modèle pour éviter les collisions + le slug
du titre SEO pour qu'il soit parlant côté marketplace.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


class PackagerError(Exception):
    """STL absent, disque plein, ZIP vide, etc."""


def build_zip(
    model_id: int,
    stl_path: str,
    photo_paths: list[str],
    listing_text: str,
    title: str,
    output_dir: str,
) -> str:
    """Construit le ZIP et retourne son chemin absolu.

    - Les photos manquantes sur disque sont loggées puis skippées (le pack
      continue sans planter, cf. SPECS §5 étape 7 : "listing vide, à la main").
    - Le STL est obligatoire : sans lui, l'export n'a aucun sens.
    """
    stl = Path(stl_path)
    if not stl.is_file() or stl.stat().st_size == 0:
        raise PackagerError(f"STL missing or empty: {stl_path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title or f"model_{model_id}")
    zip_path = out_dir / f"{model_id}_{slug}.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(stl, arcname="model.stl")

            for i, raw in enumerate(photo_paths, start=1):
                p = Path(raw)
                if not p.is_file() or p.stat().st_size == 0:
                    logger.warning("Packager: photo missing, skipping: %s", raw)
                    continue
                ext = p.suffix.lower() or ".png"
                z.write(p, arcname=f"photo_{i}{ext}")

            z.writestr("listing.txt", listing_text or "")
    except OSError as exc:
        raise PackagerError(f"Failed to write ZIP: {exc}") from exc

    if zip_path.stat().st_size == 0:
        raise PackagerError(f"Empty ZIP generated: {zip_path}")

    logger.info("Packaged ZIP: %s (%d bytes)", zip_path, zip_path.stat().st_size)
    return str(zip_path)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _slugify(text: str, max_length: int = 50) -> str:
    """Slug filesystem-safe : ASCII, minuscule, [a-z0-9-] uniquement."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length] or "model"

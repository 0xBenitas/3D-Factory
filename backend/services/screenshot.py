"""Étape 6a du pipeline : génère 4 screenshots PNG du `.glb` via pyrender.

Rôle : fournir des aperçus à l'interface (et théoriquement au moteur image
en img2img — mais SPECS §2.2 recommande le text-to-image, donc en pratique
les screenshots servent surtout de preview interne).

⚠️ `PYOPENGL_PLATFORM=osmesa` doit être défini AVANT l'import de pyrender,
sinon pyrender tente d'ouvrir un GL context X11 et crash sur le VPS.
On le force ici en fallback via `setdefault`, mais la méthode propre reste
`setup_vps.sh` (ajout au .bashrc).

pyrender/Pillow sont importés à l'appel (pas au chargement du module) pour
que les tests `mesh_repair` puissent tourner sans ces deps en dev.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Doit être set avant tout import pyrender (même indirect).
os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_SIZE = 512


class ScreenshotError(Exception):
    """Échec de génération des screenshots (pyrender absent, mesh vide, etc.)."""


# --------------------------------------------------------------------------- #
# Entrée publique
# --------------------------------------------------------------------------- #

def generate_screenshots(
    glb_path: str,
    output_dir: str,
    size: int = DEFAULT_SIZE,
) -> list[str]:
    """Génère 4 screenshots (front, 3/4, side, top) du `.glb`.

    Retourne la liste des chemins PNG générés (dans l'ordre).
    Lève `ScreenshotError` si pyrender est absent ou si le mesh est vide.
    """
    try:
        import pyrender  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise ScreenshotError(
            f"pyrender/Pillow not installed (or PYOPENGL_PLATFORM unset): {exc}"
        ) from exc

    glb = Path(glb_path)
    if not glb.is_file():
        raise ScreenshotError(f"GLB missing: {glb_path}")

    scene_trimesh = trimesh.load(str(glb))
    if not isinstance(scene_trimesh, trimesh.Scene):
        scene_trimesh = trimesh.Scene(scene_trimesh)

    meshes = scene_trimesh.dump()
    if not meshes:
        raise ScreenshotError("GLB contient aucune géométrie")

    bounds = scene_trimesh.bounds
    center = (bounds[0] + bounds[1]) / 2.0
    scale = float(np.max(bounds[1] - bounds[0]))
    distance = scale * 2.0

    angles: list[tuple[str, np.ndarray]] = [
        ("front",         np.array([0.0, -distance, center[2]])),
        ("three_quarter", np.array([distance * 0.7, -distance * 0.7, center[2] + scale * 0.3])),
        ("side",          np.array([distance, 0.0, center[2]])),
        ("top",           np.array([0.0, -distance * 0.3, center[2] + distance])),
    ]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for name, eye in angles:
        try:
            path = _render_one(pyrender, Image, meshes, center, eye, size, out_dir, name)
        except Exception as exc:
            raise ScreenshotError(f"Failed to render '{name}': {exc}") from exc
        paths.append(path)
        logger.info("Screenshot %s → %s", name, path)

    return paths


# --------------------------------------------------------------------------- #
# Helpers internes
# --------------------------------------------------------------------------- #

def _render_one(
    pyrender,
    Image,
    meshes: list,
    center: np.ndarray,
    eye: np.ndarray,
    size: int,
    out_dir: Path,
    name: str,
) -> str:
    """Rend une scène unique vers un PNG et retourne son chemin."""
    scene = pyrender.Scene(bg_color=[240, 240, 240, 255])

    for m in meshes:
        material = pyrender.MetallicRoughnessMaterial(
            baseColorFactor=[0.7, 0.7, 0.7, 1.0],
            metallicFactor=0.1,
            roughnessFactor=0.7,
        )
        scene.add(pyrender.Mesh.from_trimesh(m, material=material))

    camera = pyrender.PerspectiveCamera(yfov=float(np.pi) / 4.0)
    camera_pose = _look_at(eye, center)
    scene.add(camera, pose=camera_pose)

    # Lumière principale (depuis la caméra) + lumière d'appoint (opposée).
    light_main = pyrender.DirectionalLight(color=[255, 255, 255], intensity=3.0)
    scene.add(light_main, pose=camera_pose)
    light_fill = pyrender.DirectionalLight(color=[200, 200, 255], intensity=1.5)
    light_fill_pose = _look_at(eye * np.array([-1.0, 1.0, 1.0]), center)
    scene.add(light_fill, pose=light_fill_pose)

    renderer = pyrender.OffscreenRenderer(size, size)
    try:
        color, _ = renderer.render(scene)
    finally:
        renderer.delete()

    path = out_dir / f"{name}.png"
    Image.fromarray(color).save(str(path))
    return str(path)


def _look_at(
    eye: np.ndarray,
    target: np.ndarray,
    up: np.ndarray | None = None,
) -> np.ndarray:
    """Matrice de pose caméra 4×4 (convention OpenGL : caméra regarde -Z)."""
    if up is None:
        up = np.array([0.0, 0.0, 1.0])

    forward = target - eye
    norm = np.linalg.norm(forward)
    if norm < 1e-8:
        raise ValueError("eye and target coincide")
    forward = forward / norm

    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-6:
        # forward parallèle à up → on prend un autre vecteur up.
        up = np.array([0.0, 1.0, 0.0])
        right = np.cross(forward, up)
    right = right / np.linalg.norm(right)

    true_up = np.cross(right, forward)
    true_up = true_up / np.linalg.norm(true_up)

    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = true_up
    pose[:3, 2] = -forward
    pose[:3, 3] = eye
    return pose

"""Étape 3 du pipeline : mesh check + repair + métriques brutes + export STL.

Repair décomposé en 3 sous-étapes pour pouvoir les rejouer indépendamment
depuis l'endpoint `POST /api/models/{id}/repair` :

- `normalize(mesh)`    : merge vertices + recalc normals (toujours sûr)
- `fill_holes(mesh)`   : ferme les petits trous (trimesh.repair, gentle)
- `hard_repair(mesh)`  : pymeshfix forcé (peut distordre — last resort)

`auto_fix(mesh)` enchaîne normalize → fill_holes (si non-watertight) →
hard_repair (si toujours non-watertight). C'est ce que le pipeline appelle
par défaut.

Calibration `UNIT_TO_MM` :
  Les .glb Meshy/Tripo n'ont pas d'unité standardisée. Valeur par défaut
  supposée : 1 unité source = 1 mètre → facteur 1000 pour obtenir des mm.
  Overridable via `MESH_UNIT_TO_MM` après inspection d'un .glb réel.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import pymeshfix
import trimesh

logger = logging.getLogger(__name__)


UNIT_TO_MM: float = float(os.getenv("MESH_UNIT_TO_MM", "1000.0"))

REPAIR_MODES = ("auto", "normalize", "fill_holes", "hard")


class MeshRepairError(Exception):
    """Mesh totalement irrécupérable (vide, non chargeable, non exportable)."""


# --------------------------------------------------------------------------- #
# Sous-étapes de repair (chacune retourne (mesh, log_entry))
# --------------------------------------------------------------------------- #

def normalize(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, str]:
    """Merge vertices dupliqués + recalcule les normales. Toujours sûr."""
    try:
        mesh.merge_vertices()
        trimesh.repair.fix_normals(mesh)
        return mesh, "normalized (merge_vertices + fix_normals)"
    except Exception as exc:
        logger.warning("normalize failed: %s", exc)
        return mesh, f"normalize failed: {exc}"


def fill_holes(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, str]:
    """Ferme les petits trous via trimesh.repair.fill_holes (gentle)."""
    try:
        trimesh.repair.fill_holes(mesh)
        return mesh, "fill_holes applied"
    except Exception as exc:
        logger.warning("fill_holes failed: %s", exc)
        return mesh, f"fill_holes failed: {exc}"


def hard_repair(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, str]:
    """Reconstruction par pymeshfix. Peut distordre la géométrie — last resort."""
    try:
        verts = mesh.vertices.copy()
        faces = mesh.faces.copy()
        fix = pymeshfix.MeshFix(verts, faces)
        fix.repair()
        # pymeshfix ≥ 0.18 expose `points`/`faces` (v/f historiques supprimés).
        return trimesh.Trimesh(vertices=fix.points, faces=fix.faces, process=False), "pymeshfix hard repair applied"
    except Exception as exc:
        logger.warning("hard_repair failed: %s", exc)
        return mesh, f"hard_repair failed: {exc}"


# --------------------------------------------------------------------------- #
# Orchestrateur
# --------------------------------------------------------------------------- #

def auto_fix(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, list[str]]:
    """normalize → fill_holes (si non-watertight) → hard_repair (si toujours non-watertight)."""
    log: list[str] = []

    mesh, entry = normalize(mesh)
    log.append(entry)

    if not mesh.is_watertight:
        mesh, entry = fill_holes(mesh)
        log.append(entry)

    if not mesh.is_watertight:
        mesh, entry = hard_repair(mesh)
        log.append(entry)
        # re-normalise après hard_repair (process=False a sauté merge_vertices)
        mesh, entry = normalize(mesh)
        log.append(entry)

    return mesh, log


# --------------------------------------------------------------------------- #
# Entry point pipeline
# --------------------------------------------------------------------------- #

def analyze_and_repair(glb_path: str, stl_output_path: str, mode: str = "auto") -> dict:
    """Charge un .glb, applique le repair selon `mode`, calcule les métriques, exporte en .stl.

    `mode` ∈ REPAIR_MODES :
      - "auto"        : orchestrateur (normalize + fill_holes/hard si besoin)
      - "normalize"   : seulement merge_vertices + fix_normals
      - "fill_holes"  : seulement trimesh.repair.fill_holes (sans normalize préalable)
      - "hard"        : seulement pymeshfix forcé

    Retourne {mesh_metrics, repair_log, stl_path}. Lève MeshRepairError si mesh irrécupérable.
    """
    if mode not in REPAIR_MODES:
        raise ValueError(f"Unknown repair mode '{mode}'. Allowed: {REPAIR_MODES}")

    mesh = _load_glb(glb_path)

    if mode == "auto":
        mesh, log = auto_fix(mesh)
    else:
        single = {"normalize": normalize, "fill_holes": fill_holes, "hard": hard_repair}[mode]
        mesh, entry = single(mesh)
        log = [entry]

    try:
        metrics = _compute_metrics(mesh)
    except Exception as exc:
        raise MeshRepairError(f"Failed to compute metrics: {exc}") from exc

    out_path = _export(mesh, stl_output_path, log)

    return {
        "mesh_metrics": metrics,
        "repair_log": "\n".join(log) if log else "No repair needed",
        "stl_path": str(out_path),
    }


# --------------------------------------------------------------------------- #
# Helpers I/O
# --------------------------------------------------------------------------- #

def _load_glb(glb_path: str) -> trimesh.Trimesh:
    glb = Path(glb_path)
    if not glb.is_file() or glb.stat().st_size == 0:
        raise MeshRepairError(f"GLB missing or empty: {glb_path}")

    try:
        scene = trimesh.load(str(glb), force=None)
    except Exception as exc:
        raise MeshRepairError(f"Failed to load GLB: {exc}") from exc

    if isinstance(scene, trimesh.Scene):
        meshes = scene.dump()
        if len(meshes) == 0:
            raise MeshRepairError("GLB contient aucune géométrie")
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = scene

    if mesh is None or len(mesh.faces) == 0:
        raise MeshRepairError("Mesh vide après chargement")
    return mesh


def _export(mesh: trimesh.Trimesh, stl_output_path: str, log: list[str]) -> Path:
    out = Path(stl_output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        mesh.export(str(out), file_type="stl")
        return out
    except Exception as exc:
        # Fallback .obj cf. SPECS §5 "REPAIR — Export STL fail"
        obj_out = out.with_suffix(".obj")
        try:
            mesh.export(str(obj_out), file_type="obj")
            log.append(f"STL export failed ({exc}), fell back to OBJ")
            return obj_out
        except Exception as exc2:
            raise MeshRepairError(f"Failed to export (stl+obj): {exc2}") from exc2


# --------------------------------------------------------------------------- #
# Métriques
# --------------------------------------------------------------------------- #

def _compute_metrics(mesh: trimesh.Trimesh) -> dict:
    """Calcule le dict `mesh_metrics` (schéma ARCHITECTURE §Data Models)."""
    min_thickness = _estimate_min_wall_thickness(mesh)
    max_overhang = _compute_max_overhang(mesh)

    components = mesh.split(only_watertight=False)
    extents_mm = mesh.extents * UNIT_TO_MM

    edges = mesh.edges_sorted
    _, edge_counts = np.unique(edges, axis=0, return_counts=True)
    non_manifold_edges = int(np.sum(edge_counts > 2))
    is_manifold = non_manifold_edges == 0

    volume_cm3 = None
    if mesh.is_watertight:
        volume_cm3 = round(
            float(abs(mesh.volume)) * (UNIT_TO_MM ** 3) / 1000.0, 2
        )

    surface_area_cm2 = round(float(mesh.area) * (UNIT_TO_MM ** 2) / 100.0, 2)

    face_areas = mesh.area_faces
    area_threshold = max(float(np.max(face_areas)) * 1e-8, 1e-20) if len(face_areas) else 0.0
    degenerate_count = int(np.sum(face_areas <= area_threshold)) if len(face_areas) else 0

    return {
        "is_manifold": bool(is_manifold),
        "is_watertight": bool(mesh.is_watertight),
        "non_manifold_edges": non_manifold_edges,
        "face_count": int(len(mesh.faces)),
        "vertex_count": int(len(mesh.vertices)),
        "volume_cm3": volume_cm3,
        "surface_area_cm2": surface_area_cm2,
        "min_wall_thickness_mm": round(min_thickness * UNIT_TO_MM, 2),
        "has_degenerate_faces": degenerate_count > 0,
        "degenerate_face_count": degenerate_count,
        "max_overhang_angle_deg": round(max_overhang, 1),
        "has_floating_parts": len(components) > 1,
        "connected_components": len(components),
        "bounding_box_mm": [round(float(x), 1) for x in extents_mm.tolist()],
    }


def _estimate_min_wall_thickness(mesh: trimesh.Trimesh, n_samples: int = 500) -> float:
    """Estime l'épaisseur minimale des parois (unité source, pas mm)."""
    try:
        points, face_indices = trimesh.sample.sample_surface(mesh, n_samples)
        normals = mesh.face_normals[face_indices]

        offset = 0.001 * np.max(mesh.extents)
        ray_origins = points - normals * offset
        ray_directions = -normals

        locations, index_ray, _ = mesh.ray.intersects_location(
            ray_origins, ray_directions, multiple_hits=False
        )
        if len(locations) == 0:
            return 0.0

        origin_points = ray_origins[index_ray]
        distances = np.linalg.norm(locations - origin_points, axis=1)
        valid = distances > (offset * 2)
        if not np.any(valid):
            return 0.0
        return float(np.percentile(distances[valid], 5))
    except Exception as exc:
        logger.warning("Wall thickness estimation failed: %s", exc)
        return 0.0


def _compute_max_overhang(mesh: trimesh.Trimesh) -> float:
    """Angle de surplomb max (degrés, 0=OK, 90=pire)."""
    try:
        up = np.array([0.0, 0.0, 1.0])
        normals = mesh.face_normals
        dots = np.dot(normals, up)

        overhanging = dots < 0
        if not np.any(overhanging):
            return 0.0

        overhang_dots = -dots[overhanging]
        angles_from_vertical = np.degrees(np.arccos(np.clip(overhang_dots, 0.0, 1.0)))
        overhang_angles = 90.0 - angles_from_vertical
        return float(np.max(overhang_angles))
    except Exception as exc:
        logger.warning("Overhang computation failed: %s", exc)
        return 0.0

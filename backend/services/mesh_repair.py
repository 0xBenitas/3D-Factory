"""Étape 3 du pipeline : mesh check + repair + métriques brutes + export STL.

Implémentation de référence de SPECS §3 (reprise quasi-verbatim, avec
quelques ajustements pour la robustesse). Tout est synchrone (CPU-bound,
appelé depuis un thread dans `tasks.py` pour ne pas bloquer la loop).

Calibration `UNIT_TO_MM` :
  Les .glb Meshy/Tripo n'ont pas d'unité standardisée. Valeur par défaut
  supposée : 1 unité source = 1 mètre → facteur 1000 pour obtenir des mm.
  Overridable via la variable d'env `MESH_UNIT_TO_MM` au déploiement
  après inspection d'un .glb réel avec `mesh.extents`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import pymeshfix
import trimesh

logger = logging.getLogger(__name__)


# Facteur de conversion unités source → mm (SPECS §3).
UNIT_TO_MM: float = float(os.getenv("MESH_UNIT_TO_MM", "1000.0"))


class MeshRepairError(Exception):
    """Mesh totalement irrécupérable (vide, non chargeable, non exportable)."""


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def analyze_and_repair(glb_path: str, stl_output_path: str) -> dict:
    """Charge un .glb, tente un repair, calcule les métriques, exporte en .stl.

    Retourne un dict :
        {
            "mesh_metrics": { ... },       # voir schéma ARCHITECTURE §mesh_metrics
            "repair_log": "...",
            "stl_path": "...",
        }

    Lève `MeshRepairError` si le mesh est totalement irrécupérable.
    """
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

    repair_log: list[str] = []

    # 1) pymeshfix si non-watertight
    if not mesh.is_watertight:
        try:
            verts = mesh.vertices.copy()
            faces = mesh.faces.copy()
            fix = pymeshfix.MeshFix(verts, faces)
            fix.repair(verbose=False)
            mesh = trimesh.Trimesh(vertices=fix.v, faces=fix.f, process=False)
            repair_log.append("pymeshfix repair applied")
        except Exception as exc:
            repair_log.append(f"pymeshfix failed: {exc}")
            logger.warning("pymeshfix failed: %s", exc)

    # 2) fill_holes en fallback
    if not mesh.is_watertight:
        try:
            trimesh.repair.fill_holes(mesh)
            repair_log.append("trimesh fill_holes applied")
        except Exception as exc:
            repair_log.append(f"fill_holes failed: {exc}")

    # 3) normales toujours refixées
    try:
        trimesh.repair.fix_normals(mesh)
        repair_log.append("normals fixed")
    except Exception as exc:
        repair_log.append(f"fix_normals failed: {exc}")

    # 4) Métriques après repair
    try:
        metrics = _compute_metrics(mesh)
    except Exception as exc:
        raise MeshRepairError(f"Failed to compute metrics: {exc}") from exc

    # 5) Export STL
    out = Path(stl_output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        mesh.export(str(out), file_type="stl")
    except Exception as exc:
        # Fallback .obj cf. SPECS §5 "REPAIR — Export STL fail"
        obj_out = out.with_suffix(".obj")
        try:
            mesh.export(str(obj_out), file_type="obj")
            repair_log.append(f"STL export failed ({exc}), fell back to OBJ")
            out = obj_out
        except Exception as exc2:
            raise MeshRepairError(f"Failed to export (stl+obj): {exc2}") from exc2

    return {
        "mesh_metrics": metrics,
        "repair_log": "\n".join(repair_log) if repair_log else "No repair needed",
        "stl_path": str(out),
    }


# --------------------------------------------------------------------------- #
# Métriques
# --------------------------------------------------------------------------- #

def _compute_metrics(mesh: trimesh.Trimesh) -> dict:
    """Calcule le dict `mesh_metrics` (schéma ARCHITECTURE §Data Models)."""
    min_thickness = _estimate_min_wall_thickness(mesh)
    max_overhang = _compute_max_overhang(mesh)

    components = mesh.split(only_watertight=False)
    extents_mm = mesh.extents * UNIT_TO_MM

    # Manifold check (trimesh n'a pas de propriété dédiée) : chaque arête
    # doit être partagée par exactement 2 faces.
    edges = mesh.edges_sorted
    _, edge_counts = np.unique(edges, axis=0, return_counts=True)
    non_manifold_edges = int(np.sum(edge_counts > 2))
    is_manifold = non_manifold_edges == 0

    volume_cm3 = None
    if mesh.is_watertight:
        # vol source → mm³ → cm³
        volume_cm3 = round(
            float(abs(mesh.volume)) * (UNIT_TO_MM ** 3) / 1000.0, 2
        )

    surface_area_cm2 = round(float(mesh.area) * (UNIT_TO_MM ** 2) / 100.0, 2)

    # `mesh.degenerate_faces` a disparu en trimesh 4.x. On calcule via aires :
    # une face dégénérée a une aire ~0 (sommets colinéaires/confondus).
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

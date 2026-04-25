"""Tests pour services/mesh_repair.py.

On ne dépend pas d'un .glb Meshy réel : on génère un cube procédural via
trimesh et on l'écrit en .glb. Ça valide la chaîne complète
(load → metrics → export STL) en isolation des APIs externes.

Run : `pytest backend/tests/test_mesh_repair.py -v` depuis la racine,
ou `python -m unittest backend.tests.test_mesh_repair` sans pytest.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ajout du dossier backend au path pour les imports `services.*`.
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

import trimesh   # noqa: E402

from services import mesh_repair   # noqa: E402


class MeshRepairTest(unittest.TestCase):
    """Tests bout en bout sur des meshes générés procéduralement."""

    def _write_cube_glb(self, path: Path, extents: tuple[float, float, float]) -> None:
        """Crée un cube de dimensions `extents` (unités source) et l'exporte en .glb."""
        box = trimesh.creation.box(extents=extents)
        scene = trimesh.Scene(box)
        path.parent.mkdir(parents=True, exist_ok=True)
        scene.export(str(path))

    def test_cube_manifold_watertight(self) -> None:
        """Un cube propre : manifold, watertight, 12 faces, 1 composant."""
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "cube.glb"
            stl = Path(td) / "cube.stl"
            # 1m × 1m × 1m (UNIT_TO_MM=1000 → bbox 1000×1000×1000 mm)
            self._write_cube_glb(glb, (1.0, 1.0, 1.0))

            result = mesh_repair.analyze_and_repair(str(glb), str(stl))

            self.assertTrue(Path(stl).is_file(), "STL doit être exporté")
            self.assertGreater(Path(stl).stat().st_size, 0)

            m = result["mesh_metrics"]
            self.assertTrue(m["is_manifold"], f"cube attendu manifold, got {m}")
            self.assertTrue(m["is_watertight"])
            self.assertEqual(m["non_manifold_edges"], 0)
            self.assertEqual(m["connected_components"], 1)
            self.assertFalse(m["has_floating_parts"])
            self.assertFalse(m["has_degenerate_faces"])
            self.assertEqual(m["face_count"], 12)   # cube = 12 triangles
            self.assertEqual(len(m["bounding_box_mm"]), 3)
            # 1m → 1000mm
            for v in m["bounding_box_mm"]:
                self.assertAlmostEqual(v, 1000.0, delta=0.5)

    def test_bounding_box_scaling(self) -> None:
        """Bounding box respecte le facteur UNIT_TO_MM."""
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "c.glb"
            stl = Path(td) / "c.stl"
            self._write_cube_glb(glb, (0.05, 0.08, 0.12))   # 50, 80, 120 mm
            result = mesh_repair.analyze_and_repair(str(glb), str(stl))
            bb = result["mesh_metrics"]["bounding_box_mm"]
            self.assertAlmostEqual(bb[0], 50.0, delta=0.5)
            self.assertAlmostEqual(bb[1], 80.0, delta=0.5)
            self.assertAlmostEqual(bb[2], 120.0, delta=0.5)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(mesh_repair.MeshRepairError):
            mesh_repair.analyze_and_repair("/nonexistent.glb", "/tmp/out.stl")

    def test_empty_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty.glb"
            empty.write_bytes(b"")
            with self.assertRaises(mesh_repair.MeshRepairError):
                mesh_repair.analyze_and_repair(str(empty), str(Path(td) / "out.stl"))

    def test_repair_log_present(self) -> None:
        """Le repair_log contient au moins l'entrée 'normals fixed'."""
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "c.glb"
            stl = Path(td) / "c.stl"
            self._write_cube_glb(glb, (0.1, 0.1, 0.1))
            result = mesh_repair.analyze_and_repair(str(glb), str(stl))
            self.assertIn("normals", result["repair_log"].lower() + " ")

    def test_unknown_mode_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "c.glb"
            stl = Path(td) / "c.stl"
            self._write_cube_glb(glb, (0.1, 0.1, 0.1))
            with self.assertRaises(ValueError):
                mesh_repair.analyze_and_repair(str(glb), str(stl), mode="bogus")

    def test_normalize_mode_only_normalizes(self) -> None:
        """Mode 'normalize' n'applique que merge_vertices + fix_normals."""
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "c.glb"
            stl = Path(td) / "c.stl"
            self._write_cube_glb(glb, (0.1, 0.1, 0.1))
            result = mesh_repair.analyze_and_repair(str(glb), str(stl), mode="normalize")
            self.assertIn("normalized", result["repair_log"])
            self.assertNotIn("fill_holes", result["repair_log"])
            self.assertNotIn("pymeshfix", result["repair_log"])

    def test_hard_mode_runs_pymeshfix(self) -> None:
        """Mode 'hard' force pymeshfix même sur un cube watertight."""
        with tempfile.TemporaryDirectory() as td:
            glb = Path(td) / "c.glb"
            stl = Path(td) / "c.stl"
            self._write_cube_glb(glb, (0.1, 0.1, 0.1))
            result = mesh_repair.analyze_and_repair(str(glb), str(stl), mode="hard")
            self.assertIn("pymeshfix", result["repair_log"])


if __name__ == "__main__":
    unittest.main()

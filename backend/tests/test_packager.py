"""Tests du packager ZIP — zipfile seul, aucune dépendance externe."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

from services import packager  # noqa: E402


class PackagerTest(unittest.TestCase):
    def test_slugify_removes_accents_and_special_chars(self) -> None:
        self.assertEqual(packager._slugify("Pot de fleur — édition #42"),
                         "pot-de-fleur-edition-42")
        self.assertEqual(packager._slugify("  Hello  World  "), "hello-world")
        self.assertEqual(packager._slugify(""), "model")
        self.assertEqual(packager._slugify("!!!"), "model")

    def test_build_zip_contains_stl_photos_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            stl = td_path / "model.stl"
            stl.write_bytes(b"solid test\nendsolid\n")
            p1 = td_path / "photo_raw.png"
            p1.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            missing = td_path / "absent.png"  # ne l'écrivons pas

            out_dir = td_path / "exports"
            zip_path = packager.build_zip(
                model_id=42,
                stl_path=str(stl),
                photo_paths=[str(p1), str(missing)],
                listing_text="TITRE\n\nDESCRIPTION",
                title="Mon Super Modèle",
                output_dir=str(out_dir),
            )

            zp = Path(zip_path)
            self.assertTrue(zp.is_file())
            self.assertTrue(zp.name.startswith("42_"))
            self.assertIn("mon-super-modele", zp.name)

            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                self.assertIn("model.stl", names)
                self.assertIn("listing.txt", names)
                # La photo manquante doit avoir été skippée (pas de photo_2).
                self.assertIn("photo_1.png", names)
                self.assertNotIn("photo_2.png", names)
                self.assertEqual(z.read("listing.txt").decode("utf-8"),
                                 "TITRE\n\nDESCRIPTION")

    def test_build_zip_missing_stl_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(packager.PackagerError):
                packager.build_zip(
                    model_id=1,
                    stl_path=str(Path(td) / "nonexistent.stl"),
                    photo_paths=[],
                    listing_text="x",
                    title="t",
                    output_dir=str(Path(td) / "out"),
                )

    def test_build_zip_empty_stl_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stl = Path(td) / "model.stl"
            stl.write_bytes(b"")
            with self.assertRaises(packager.PackagerError):
                packager.build_zip(
                    model_id=1, stl_path=str(stl),
                    photo_paths=[], listing_text="x",
                    title="t", output_dir=str(Path(td) / "out"),
                )


if __name__ == "__main__":
    unittest.main()

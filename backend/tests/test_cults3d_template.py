"""Tests du template Cults3D — pure fonction, pas de dépendance externe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

from templates.cults3d import Cults3DTemplate  # noqa: E402


class Cults3DTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tpl = Cults3DTemplate()

    def test_format_listing_full(self) -> None:
        seo = {
            "title": "Hexagonal Plant Pot",
            "description": "A modern, minimalist pot.",
            "tags": ["plant pot", "geometric", "STL"],
            "price_eur": 2.49,
        }
        print_params = {
            "layer_height_mm": 0.2,
            "infill_percent": 20,
            "supports_needed": False,
            "support_notes": "Aucun surplomb",
            "nozzle_diameter_mm": 0.4,
            "material_recommended": "PLA",
            "estimated_print_time_h": 3.5,
            "estimated_material_g": 42,
            "orientation_tip": "Base vers le plateau",
            "difficulty": "facile",
        }
        text = self.tpl.format_listing(seo, print_params)
        # Sections attendues
        self.assertIn("# Hexagonal Plant Pot", text)
        self.assertIn("A modern, minimalist pot.", text)
        self.assertIn("## Paramètres d'impression recommandés", text)
        self.assertIn("Hauteur de couche", text)
        self.assertIn("0.2 mm", text)
        self.assertIn("PLA", text)
        self.assertIn("Supports", text)
        self.assertIn("non", text)
        self.assertIn("Aucun surplomb", text)
        self.assertIn("## Tags", text)
        self.assertIn("plant pot, geometric, STL", text)
        self.assertIn("## Prix suggéré", text)
        self.assertIn("2.49€", text)

    def test_format_listing_missing_print_params(self) -> None:
        """Les clés absentes ne doivent ni crasher ni produire de "None"."""
        seo = {"title": "T", "description": "D", "tags": [], "price_eur": 1.0}
        text = self.tpl.format_listing(seo, {})
        self.assertIn("# T", text)
        self.assertNotIn("None", text)

    def test_format_listing_empty_everything(self) -> None:
        text = self.tpl.format_listing({}, {})
        # Doit retourner au moins un "\n" (pas planter).
        self.assertIsInstance(text, str)
        self.assertNotIn("None", text)

    def test_tone_and_limits_are_cults3d(self) -> None:
        self.assertEqual(self.tpl.name, "cults3d")
        self.assertEqual(self.tpl.max_title_length, 80)
        self.assertEqual(self.tpl.max_tags, 15)
        self.assertGreater(len(self.tpl.tone), 0)


if __name__ == "__main__":
    unittest.main()

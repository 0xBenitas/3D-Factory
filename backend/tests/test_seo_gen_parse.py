"""Tests du parser JSON tolérant de seo_gen (pas d'appel Claude réel).

Requiert `anthropic` installé (import top-level dans services.seo_gen).
Si la lib manque, les tests sont skippés : on ne casse pas un test suite
minimal en environnement sans deps Claude.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

try:
    from services import seo_gen  # noqa: E402
    _SEO_GEN_AVAILABLE = True
except ImportError:
    seo_gen = None  # type: ignore[assignment]
    _SEO_GEN_AVAILABLE = False


@unittest.skipUnless(_SEO_GEN_AVAILABLE, "anthropic/seo_gen not installed")
class SeoGenParseTest(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        raw = '{"title": "Foo", "price_eur": 2.49}'
        self.assertEqual(seo_gen._parse_json(raw),
                         {"title": "Foo", "price_eur": 2.49})

    def test_parse_fenced_json(self) -> None:
        raw = "```json\n{\"a\": 1}\n```"
        self.assertEqual(seo_gen._parse_json(raw), {"a": 1})

    def test_parse_fenced_without_lang(self) -> None:
        raw = "```\n{\"a\": 1}\n```"
        self.assertEqual(seo_gen._parse_json(raw), {"a": 1})

    def test_parse_with_prefix_text(self) -> None:
        raw = 'Voici la réponse:\n{"x": "y"}\nFin.'
        # Le parser cherche le premier { ... }.
        self.assertEqual(seo_gen._parse_json(raw), {"x": "y"})

    def test_parse_invalid_returns_none(self) -> None:
        self.assertIsNone(seo_gen._parse_json(""))
        self.assertIsNone(seo_gen._parse_json("not json at all"))
        self.assertIsNone(seo_gen._parse_json("{ invalid json "))

    def test_truncate_respects_max(self) -> None:
        text = "a" * 300
        out = seo_gen._truncate(text, 100)
        self.assertLessEqual(len(out), 100)

    def test_truncate_keeps_short_text(self) -> None:
        self.assertEqual(seo_gen._truncate("short", 100), "short")

    def test_default_print_params_has_all_keys(self) -> None:
        # Sert de "contrat" pour le frontend PrintParams.
        expected_keys = {
            "layer_height_mm", "infill_percent", "supports_needed",
            "support_notes", "nozzle_diameter_mm", "material_recommended",
            "estimated_print_time_h", "estimated_material_g",
            "orientation_tip", "difficulty",
        }
        self.assertEqual(set(seo_gen.DEFAULT_PRINT_PARAMS.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()

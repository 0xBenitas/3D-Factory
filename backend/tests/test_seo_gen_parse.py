"""Tests des helpers de parsing JSON / troncature partagés entre seo_gen,
prompt_optimizer et quality_scorer (extraits dans `anthropic_helpers`).

+ contrat des `DEFAULT_PRINT_PARAMS` (frontend en dépend).

Requiert `anthropic` installé (import top-level dans `anthropic_helpers`).
Si la lib manque, les tests sont skippés.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

try:
    from services import anthropic_helpers, seo_gen  # noqa: E402
    _AVAILABLE = True
except ImportError:
    anthropic_helpers = None  # type: ignore[assignment]
    seo_gen = None  # type: ignore[assignment]
    _AVAILABLE = False


@unittest.skipUnless(_AVAILABLE, "anthropic SDK not installed")
class ParseJsonTolerantTest(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        raw = '{"title": "Foo", "price_eur": 2.49}'
        self.assertEqual(
            anthropic_helpers.parse_json_tolerant(raw),
            {"title": "Foo", "price_eur": 2.49},
        )

    def test_parse_fenced_json(self) -> None:
        raw = "```json\n{\"a\": 1}\n```"
        self.assertEqual(anthropic_helpers.parse_json_tolerant(raw), {"a": 1})

    def test_parse_fenced_without_lang(self) -> None:
        raw = "```\n{\"a\": 1}\n```"
        self.assertEqual(anthropic_helpers.parse_json_tolerant(raw), {"a": 1})

    def test_parse_with_prefix_text(self) -> None:
        raw = 'Voici la réponse:\n{"x": "y"}\nFin.'
        self.assertEqual(anthropic_helpers.parse_json_tolerant(raw), {"x": "y"})

    def test_parse_invalid_returns_none(self) -> None:
        self.assertIsNone(anthropic_helpers.parse_json_tolerant(""))
        self.assertIsNone(anthropic_helpers.parse_json_tolerant("not json at all"))
        self.assertIsNone(anthropic_helpers.parse_json_tolerant("{ invalid json "))


@unittest.skipUnless(_AVAILABLE, "anthropic SDK not installed")
class TruncateSmartTest(unittest.TestCase):
    def test_respects_max(self) -> None:
        text = "a" * 300
        self.assertLessEqual(len(anthropic_helpers.truncate_smart(text, 100)), 100)

    def test_keeps_short_text(self) -> None:
        self.assertEqual(anthropic_helpers.truncate_smart("short", 100), "short")

    def test_breaks_on_word_boundary_when_close(self) -> None:
        text = "the quick brown fox jumps over"
        out = anthropic_helpers.truncate_smart(text, 15)
        # cut à 15 = "the quick brown" — pas de break en plein mot
        self.assertFalse(out.endswith("brow") or out.endswith("brow "))


@unittest.skipUnless(_AVAILABLE, "anthropic SDK not installed")
class DefaultPrintParamsTest(unittest.TestCase):
    def test_has_all_keys(self) -> None:
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

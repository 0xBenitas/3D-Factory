"""Tests pour services/scoring_profiles.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

from services import scoring_profiles  # noqa: E402


class ScoringProfilesTest(unittest.TestCase):

    def _criteria_all(self, score: float) -> dict:
        return {
            c: {"score": score, "note": "x"} for c in scoring_profiles.CRITERIA
        }

    def test_all_perfect_returns_10(self) -> None:
        for cat in (None, "Figurine", "Fonctionnel", "Déco"):
            self.assertEqual(
                scoring_profiles.compute_weighted_score(self._criteria_all(10), cat),
                10.0,
                f"perfect score should give 10 for category={cat}",
            )

    def test_unknown_category_uses_default(self) -> None:
        c = self._criteria_all(8)
        self.assertEqual(
            scoring_profiles.compute_weighted_score(c, "Unknown"),
            scoring_profiles.compute_weighted_score(c, None),
        )

    def test_profile_changes_score(self) -> None:
        """Wall thickness 0/10, autres 10/10 → Fonctionnel doit pénaliser plus."""
        c = self._criteria_all(10)
        c["wall_thickness"] = {"score": 0, "note": "very thin"}

        figurine = scoring_profiles.compute_weighted_score(c, "Figurine")
        functional = scoring_profiles.compute_weighted_score(c, "Fonctionnel")

        self.assertIsNotNone(figurine)
        self.assertIsNotNone(functional)
        # Fonctionnel a un poids 2.5 sur wall_thickness (vs 1.0 Figurine)
        # → score plus bas pour Fonctionnel.
        self.assertLess(functional, figurine)

    def test_score_clamped_to_0_10(self) -> None:
        c = self._criteria_all(15)  # surenchère Claude
        result = scoring_profiles.compute_weighted_score(c, "Figurine")
        self.assertEqual(result, 10.0)

        c2 = self._criteria_all(-5)  # négatif
        result2 = scoring_profiles.compute_weighted_score(c2, "Figurine")
        self.assertEqual(result2, 0.0)

    def test_missing_criteria_returns_none(self) -> None:
        self.assertIsNone(
            scoring_profiles.compute_weighted_score({}, "Figurine"),
        )

    def test_invalid_score_skipped(self) -> None:
        c = {
            "manifold": {"score": "not a number", "note": "x"},
            "watertight": {"score": 8, "note": "x"},
        }
        # Seul `watertight` est exploitable → score = 8.
        self.assertEqual(
            scoring_profiles.compute_weighted_score(c, None),
            8.0,
        )

    def test_get_weights_fallback(self) -> None:
        self.assertEqual(scoring_profiles.get_weights(None), scoring_profiles.DEFAULT_WEIGHTS)
        self.assertEqual(scoring_profiles.get_weights("Bogus"), scoring_profiles.DEFAULT_WEIGHTS)
        self.assertEqual(
            scoring_profiles.get_weights("Figurine"),
            scoring_profiles.PROFILE_WEIGHTS["Figurine"],
        )


if __name__ == "__main__":
    unittest.main()

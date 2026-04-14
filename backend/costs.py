"""Coûts EUR estimés par étape du pipeline.

Approximation : les APIs facturent en USD, mais à l'échelle des ordres de
grandeur du projet (~0.20€ / modèle), la différence USD/EUR est dans le
bruit. On garde donc des valeurs arrondies en EUR.

Source : SPECS §"Coûts par modèle" et §2 "APIs externes détaillées".

Convention : toutes les constantes sont des float EUR.
"""

from __future__ import annotations


# --- Claude API ---
# (Prompt d'optimisation, scoring, lifestyle, listing, print_params.)
# Sonnet 4.5 sur ~500 tokens output + ~1k input ≈ $0.003-$0.005 par appel.
PROMPT_OPTIMIZE_EUR: float = 0.003
SCORING_EUR: float = 0.005
LIFESTYLE_PROMPT_EUR: float = 0.002
LISTING_EUR: float = 0.003
PRINT_PARAMS_EUR: float = 0.002


# --- Meshy API ---
# meshy-5 preview = 5 crédits = ~$0.10 / génération (SPECS §2.1).
MESHY_PREVIEW_EUR: float = 0.10
MESHY_REMESH_EUR: float = 0.10


# --- Stability AI ---
# Stable Image Core = 3 crédits = $0.03 / image (SPECS §2.2).
STABILITY_PER_IMAGE_EUR: float = 0.03


def engine_generate_eur(engine_name: str) -> float:
    """Coût estimé d'une génération pour un moteur donné.

    Le prix Meshy est celui du mode preview (5 crédits). Les autres moteurs
    retombent sur le même ordre de grandeur par défaut.
    """
    if engine_name == "meshy":
        return MESHY_PREVIEW_EUR
    return MESHY_PREVIEW_EUR  # défaut conservateur


def engine_remesh_eur(engine_name: str) -> float:
    if engine_name == "meshy":
        return MESHY_REMESH_EUR
    return MESHY_REMESH_EUR

"""Router : GET /api/stats.

Agrégations légères sur la table `models` pour alimenter le CostTracker
et la SettingsPage (budget en cours, nombre de modèles, taux d'approbation,
score moyen).

Les totaux sont bornés à 365 jours d'historique (index sur `created_at`
garantit une latence OK même à plusieurs milliers de lignes).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

import costs
from app_settings import get_float_setting
from database import get_db
from models import Model

router = APIRouter(prefix="/api", tags=["stats"])


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

class StatsView(BaseModel):
    today_cost_eur: float
    today_count: int
    month_cost_eur: float
    month_count: int
    total_count: int
    approved_count: int
    rejected_count: int
    pending_count: int
    approval_rate: float | None
    avg_score: float | None
    max_daily_budget_eur: float
    budget_exceeded: bool
    # True si `max_daily_budget_eur <= 0` → plafond journalier désactivé,
    # aucune limite sur les appels API payants. L'UI affiche un bandeau.
    budget_disabled: bool


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _today_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _sum_cost_since(db: Session, since: datetime) -> tuple[float, int]:
    """Retourne (somme EUR, nb modèles) depuis `since` (UTC)."""
    row = (
        db.query(
            func.coalesce(func.sum(Model.cost_eur_estimate), 0.0),
            func.count(Model.id),
        )
        .filter(Model.created_at >= since)
        .one()
    )
    return float(row[0] or 0.0), int(row[1] or 0)


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@router.get("/stats", response_model=StatsView)
def get_stats(db: Session = Depends(get_db)) -> StatsView:
    today_cost, today_count = _sum_cost_since(db, _today_start_utc())
    month_cost, month_count = _sum_cost_since(db, _month_start_utc())

    # Décompte par validation + score moyen — 2 requêtes sont amplement OK.
    total_count = db.query(func.count(Model.id)).scalar() or 0
    approved = db.query(func.count(Model.id)).filter(Model.validation == "approved").scalar() or 0
    rejected = db.query(func.count(Model.id)).filter(Model.validation == "rejected").scalar() or 0
    pending = db.query(func.count(Model.id)).filter(Model.validation == "pending").scalar() or 0

    avg_score_raw = db.query(func.avg(Model.qc_score)).scalar()
    avg_score = float(avg_score_raw) if avg_score_raw is not None else None

    # Taux d'approbation : approved / (approved + rejected), ignore les pending.
    finalized = approved + rejected
    approval_rate = (approved / finalized) if finalized > 0 else None

    budget = get_float_setting(db, "max_daily_budget_eur", 2.0)

    budget_disabled = budget <= 0
    return StatsView(
        today_cost_eur=round(today_cost, 4),
        today_count=today_count,
        month_cost_eur=round(month_cost, 4),
        month_count=month_count,
        total_count=int(total_count),
        approved_count=int(approved),
        rejected_count=int(rejected),
        pending_count=int(pending),
        approval_rate=round(approval_rate, 3) if approval_rate is not None else None,
        avg_score=round(avg_score, 2) if avg_score is not None else None,
        max_daily_budget_eur=budget,
        # `budget_exceeded` reste false tant que la garde est désactivée :
        # sans plafond, le concept "dépassé" n'a pas de sens.
        budget_exceeded=(not budget_disabled) and today_cost >= budget,
        budget_disabled=budget_disabled,
    )


# --------------------------------------------------------------------------- #
# Cost hints — source de vérité pour les estimations affichées dans l'UI
# (au lieu de valeurs hardcodées dans InputForm qui divergent au premier
# changement de pricing côté providers).
# --------------------------------------------------------------------------- #

class CostHintsView(BaseModel):
    generation_eur: float
    export_eur: float
    # Détail pour tooltip / debugging — pas requis par l'UI mais peu cher.
    breakdown: dict[str, float]


@router.get("/costs/hints", response_model=CostHintsView)
def get_cost_hints() -> CostHintsView:
    """Estimation des coûts par étape du pipeline (EUR).

    Basé sur `backend/costs.py` — le moteur de référence est Meshy (préview
    5 crédits). Les autres moteurs tombent sur le même ordre de grandeur.
    3 photos lifestyle par export (cohérent avec tasks.py).
    """
    gen_total = (
        costs.PROMPT_OPTIMIZE_EUR
        + costs.engine_generate_eur("meshy")
        + costs.SCORING_EUR
    )
    export_total = (
        costs.LIFESTYLE_PROMPT_EUR
        + costs.STABILITY_PER_IMAGE_EUR * 3
        + costs.LISTING_EUR
        + costs.PRINT_PARAMS_EUR
    )
    return CostHintsView(
        generation_eur=round(gen_total, 4),
        export_eur=round(export_total, 4),
        breakdown={
            "prompt_optimize": costs.PROMPT_OPTIMIZE_EUR,
            "engine_generate": costs.engine_generate_eur("meshy"),
            "scoring": costs.SCORING_EUR,
            "lifestyle_prompt": costs.LIFESTYLE_PROMPT_EUR,
            "stability_per_image": costs.STABILITY_PER_IMAGE_EUR,
            "listing": costs.LISTING_EUR,
            "print_params": costs.PRINT_PARAMS_EUR,
        },
    )

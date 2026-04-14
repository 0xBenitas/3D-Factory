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
        budget_exceeded=today_cost >= budget,
    )

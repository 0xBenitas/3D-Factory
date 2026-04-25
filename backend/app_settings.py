"""Accès runtime aux settings applicatifs (table `settings`).

Les valeurs par défaut viennent de `config.py` (chargé de `.env` au boot,
seedé en BDD par `database.init_db`). Ensuite la BDD est la source de
vérité : une modification via `PUT /api/settings` est prise en compte
immédiatement par tous les consommateurs qui utilisent ces helpers.

Helpers disponibles :
- `get_setting(db, key, fallback)` → str
- `get_float_setting(db, key, fallback)` → float (cast tolérant)
- `set_setting(db, key, value)` → upsert + commit

Les clés officielles (SPECS §"Settings") :
- default_engine        : moteur 3D par défaut
- default_image_engine  : moteur image par défaut
- default_template      : template marketplace par défaut
- max_daily_budget_eur  : budget quotidien en EUR
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from models import GenerationPrompt, Model, Prompt, Setting

logger = logging.getLogger(__name__)

# Clés API gérables via l'UI (stockées en BDD avec préfixe `api_key_`).
API_KEY_NAMES: tuple[str, ...] = ("anthropic", "meshy", "tripo", "stability")
API_KEY_SETTING_KEYS: frozenset[str] = frozenset(
    f"api_key_{n}" for n in API_KEY_NAMES
)

# Clés connues exposées par l'API settings. Les PUT sur une clé inconnue
# sont rejetés pour éviter le key-spam via l'API.
KNOWN_KEYS: frozenset[str] = frozenset({
    "default_engine",
    "default_image_engine",
    "default_template",
    "max_daily_budget_eur",
}) | API_KEY_SETTING_KEYS

# Taille max du contenu d'un preset (Phase 1.5).
PROMPT_OVERRIDE_MAX = 8000


def get_active_prompt(brick_id: str) -> Prompt | None:
    """Preset actif pour la brique (ligne `prompts.is_active=1`)."""
    try:
        from database import SessionLocal

        with SessionLocal() as db:
            return (
                db.query(Prompt)
                .filter(Prompt.brick_id == brick_id, Prompt.is_active.is_(True))
                .first()
            )
    except Exception as exc:
        logger.warning("get_active_prompt(%s): DB read failed (%s)", brick_id, exc)
        return None


def get_effective_prompt(brick_id: str) -> str:
    """System prompt à utiliser pour une brique : contenu du preset actif,
    fallback sur le défaut du registry si la biblio est vide (cas avant
    `init_db`).
    """
    from services.prompt_registry import get_default

    active = get_active_prompt(brick_id)
    if active and active.content:
        return active.content
    return get_default(brick_id)


def get_active_prompt_id(brick_id: str) -> int | None:
    """Helper pour le tracking generation_prompts."""
    active = get_active_prompt(brick_id)
    return active.id if active else None


def track_prompt_use(model_id: int, brick_id: str) -> int | None:
    """Enregistre que le prompt actif de `brick_id` a servi à `model_id`.

    Idempotent (UPSERT sur PK composite (model_id, brick_id)) — refaire
    le pipeline sur le même modèle écrase la traçabilité avec le prompt
    courant. `usage_count` est incrémenté seulement si la ligne est neuve.

    Retourne le prompt_id tracé, ou None si pas de prompt actif (cas de
    bug — la migration init_db garantit qu'il y en a un).
    """
    try:
        from database import SessionLocal

        with SessionLocal() as db:
            active = (
                db.query(Prompt)
                .filter(Prompt.brick_id == brick_id, Prompt.is_active.is_(True))
                .first()
            )
            if active is None:
                logger.warning("track_prompt_use: no active prompt for brick='%s'", brick_id)
                return None

            existing = (
                db.query(GenerationPrompt)
                .filter(
                    GenerationPrompt.model_id == model_id,
                    GenerationPrompt.brick_id == brick_id,
                )
                .first()
            )
            if existing is None:
                db.add(GenerationPrompt(
                    model_id=model_id,
                    brick_id=brick_id,
                    prompt_id=active.id,
                ))
                active.usage_count = (active.usage_count or 0) + 1
            else:
                # Re-run du pipeline → on écrase mais sans incrémenter
                # (sinon le compteur explose à chaque regen).
                existing.prompt_id = active.id

            db.commit()
            return active.id
    except Exception as exc:
        logger.warning("track_prompt_use(%d, %s) failed: %s", model_id, brick_id, exc)
        return None


def update_prompt_avg_score_for_model(model_id: int, score: float) -> None:
    """Moyenne mobile : `avg_score` de chaque prompt utilisé par ce model.

    Formule : new_avg = old_avg * (n-1)/n + score * 1/n
    avec n = usage_count actuel (déjà incrémenté par `track_prompt_use`).
    """
    try:
        from database import SessionLocal

        with SessionLocal() as db:
            rows = (
                db.query(GenerationPrompt)
                .filter(GenerationPrompt.model_id == model_id)
                .all()
            )
            for gp in rows:
                p = db.get(Prompt, gp.prompt_id)
                if p is None or (p.usage_count or 0) <= 0:
                    continue
                n = float(p.usage_count)
                old = float(p.avg_score) if p.avg_score is not None else float(score)
                p.avg_score = round(old * (n - 1) / n + score / n, 2)
            db.commit()
    except Exception as exc:
        logger.warning("update_prompt_avg_score_for_model(%d, %s) failed: %s",
                       model_id, score, exc)


def get_setting(db: Session, key: str, fallback: str = "") -> str:
    s = db.get(Setting, key)
    if s is None or s.value is None:
        return fallback
    return str(s.value)


def get_float_setting(db: Session, key: str, fallback: float) -> float:
    raw = get_setting(db, key, "")
    if not raw:
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Setting %s='%s' is not a float, using fallback=%s",
                       key, raw, fallback)
        return fallback


def set_setting(db: Session, key: str, value: str) -> None:
    """Upsert d'une clé. Le commit est à la charge de l'appelant (batch)."""
    existing = db.get(Setting, key)
    if existing is None:
        db.add(Setting(key=key, value=value))
    else:
        existing.value = value


def today_cost_eur(db: Session) -> float:
    """Somme de `cost_eur_estimate` pour les modèles créés depuis minuit UTC."""
    start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    return float(
        db.query(func.coalesce(func.sum(Model.cost_eur_estimate), 0.0))
        .filter(Model.created_at >= start)
        .scalar()
        or 0.0
    )


_BUDGET_DISABLED_WARNED: bool = False


def check_budget_or_raise(db: Session) -> None:
    """Lève HTTPException 429 si le budget quotidien est dépassé.

    Utilisé par les endpoints qui déclenchent des appels API payants :
    POST /api/pipeline/run, /api/models/{id}/regenerate, /api/models/{id}/remesh,
    /api/exports/generate. Le check intentionnellement ne s'applique PAS
    aux actions gratuites (validation, consultation).

    Si `max_daily_budget_eur <= 0`, la garde est désactivée — on log un
    WARNING une fois par process pour que l'opérateur s'en rende compte
    (config accidentelle vs intentionnelle). `GET /api/stats` expose aussi
    `budget_disabled: true` pour que l'UI affiche un bandeau.
    """
    global _BUDGET_DISABLED_WARNED

    budget = get_float_setting(
        db, "max_daily_budget_eur", config.MAX_DAILY_BUDGET_EUR
    )
    if budget <= 0:
        if not _BUDGET_DISABLED_WARNED:
            logger.warning(
                "Budget guard DISABLED (max_daily_budget_eur=%.2f). "
                "Set a positive value in Settings to cap daily spend.",
                budget,
            )
            _BUDGET_DISABLED_WARNED = True
        return
    # Budget réactivé : on réarme le warning pour le prochain passage à 0.
    _BUDGET_DISABLED_WARNED = False

    spent = today_cost_eur(db)
    if spent >= budget:
        raise HTTPException(
            429,
            f"Daily budget exceeded ({spent:.2f}€ / {budget:.2f}€). "
            "Raise it in Settings or wait until tomorrow.",
        )

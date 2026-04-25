"""Append-only timeline d'événements modèle (Phase 2.10b).

Le pipeline et les routers appellent `log_event(...)` aux moments-clés
(création, optimisation, génération, repair, scoring, regen, remesh,
repair-only). Chaque insert est best-effort : toute erreur est loggée
en warning et silenciée pour ne JAMAIS casser le pipeline si la BDD
est verrouillée, le modèle déjà supprimé (FK CASCADE en course), etc.

L'UI lit ces events via `GET /api/models/{id}/events` (ordre ASC).
"""

from __future__ import annotations

import logging
from typing import Any

from database import SessionLocal
from models import ModelEvent

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "created",
    "optimized",
    "generated",
    "repaired",
    "scored",
    "regenerated",
    "remeshed",
    "repair_only",
})


def log_event(
    model_id: int,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Insère un événement dans `model_events`. Jamais bloquant."""
    if event_type not in VALID_EVENT_TYPES:
        logger.warning(
            "model_events: unknown event_type %r (model_id=%d) — dropping",
            event_type, model_id,
        )
        return
    try:
        with SessionLocal() as db:
            db.add(ModelEvent(
                model_id=model_id,
                event_type=event_type,
                details_json=details,
            ))
            db.commit()
    except Exception as exc:
        logger.warning(
            "model_events: log_event(%d, %r) failed: %s",
            model_id, event_type, exc,
        )

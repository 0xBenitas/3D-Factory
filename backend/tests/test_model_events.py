"""Tests pour la timeline d'événements modèle (Phase 2.10b).

Couvre l'endpoint `GET /api/models/{id}/events` :
- 200 + ordre chronologique ASC sur un modèle qui a 3 events
- 404 si le modèle n'existe pas

On exerce la fonction du router directement avec une session SQLite
en mémoire : pas besoin de FastAPI TestClient, ça évite d'importer
toute la chaîne (engines/services réels) pour tester une query SQL.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from database import Base  # noqa: E402
from models import Model, ModelEvent  # noqa: E402
from routers.models3d import list_model_events  # noqa: E402


class ModelEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def test_endpoint_returns_events_in_chronological_order(self) -> None:
        with self.Session() as db:
            m = Model(input_type="text", input_text="cube", engine="meshy")
            db.add(m)
            db.commit()
            db.refresh(m)

            base = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
            db.add(ModelEvent(
                model_id=m.id, event_type="created",
                created_at=base, details_json={"source": "pipeline"},
            ))
            db.add(ModelEvent(
                model_id=m.id, event_type="generated",
                created_at=base + timedelta(seconds=10),
                details_json={"engine": "meshy", "duration_s": 12.4},
            ))
            db.add(ModelEvent(
                model_id=m.id, event_type="scored",
                created_at=base + timedelta(seconds=20),
                details_json={"score": 7.2, "previous_score": None, "delta": None},
            ))
            db.commit()

            events = list_model_events(m.id, db=db)

            self.assertEqual(len(events), 3)
            self.assertEqual(
                [e.event_type for e in events],
                ["created", "generated", "scored"],
            )
            self.assertEqual(events[2].details, {
                "score": 7.2, "previous_score": None, "delta": None,
            })
            self.assertTrue(events[0].created_at.startswith("2026-04-26T12:00:00"))

    def test_returns_empty_list_for_model_with_no_events(self) -> None:
        with self.Session() as db:
            m = Model(input_type="text", input_text="legacy", engine="meshy")
            db.add(m)
            db.commit()
            db.refresh(m)

            events = list_model_events(m.id, db=db)

            self.assertEqual(events, [])

    def test_unknown_model_raises_404(self) -> None:
        with self.Session() as db:
            with self.assertRaises(HTTPException) as ctx:
                list_model_events(9999, db=db)
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

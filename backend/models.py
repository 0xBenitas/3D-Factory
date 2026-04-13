"""Modèles SQLAlchemy — 3 tables : models, exports, settings.

Correspondance champ par champ avec la section "Data Models (SQLite)" de
`ARCHITECTURE_FINALE.md`. Les champs JSON (mesh_metrics, qc_details,
screenshot_paths, photo_paths, tags, print_params) utilisent le type
`JSON` natif de SQLAlchemy (compatible SQLite via sérialisation).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from database import Base


def _utcnow() -> datetime:
    """Timestamp UTC timezone-aware (remplace `datetime.utcnow` déprécié)."""
    return datetime.now(timezone.utc)


class Model(Base):
    """Un modèle 3D généré par le pipeline."""

    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Input utilisateur
    input_type = Column(String, nullable=False)          # "text" | "image"
    input_text = Column(Text, nullable=True)
    input_image_path = Column(String, nullable=True)

    # Prompt optimisé par Claude
    optimized_prompt = Column(Text, nullable=True)

    # Moteur 3D utilisé
    engine = Column(String, nullable=False, index=True)  # "meshy" | "tripo" | ...
    engine_task_id = Column(String, nullable=True)

    # Fichiers générés
    glb_path = Column(String, nullable=True)
    stl_path = Column(String, nullable=True)

    # Mesh repair + métriques brutes (voir ARCHITECTURE pour le schéma JSON)
    mesh_metrics = Column(JSON, nullable=True)
    repair_log = Column(Text, nullable=True)

    # Scoring qualité (informatif) — indexé : tri par score dans le dashboard
    qc_score = Column(Float, nullable=True, index=True)
    qc_details = Column(JSON, nullable=True)

    # Validation humaine — indexée : filtre principal du dashboard
    validation = Column(String, nullable=False, default="pending", index=True)
    rejection_reason = Column(Text, nullable=True)

    # Studio (photos)
    screenshot_paths = Column(JSON, nullable=True)
    photo_paths = Column(JSON, nullable=True)
    image_engine = Column(String, nullable=True)

    # Coûts
    cost_credits = Column(Integer, nullable=False, default=0)
    cost_eur_estimate = Column(Float, nullable=False, default=0.0)

    # Pipeline — indexé : filtre "en cours" + poll rapide
    # prompt | generating | repairing | scoring | pending | photos | packing | done | failed
    pipeline_status = Column(String, nullable=False, default="prompt", index=True)
    pipeline_error = Column(Text, nullable=True)

    # Indexé : tri par date dans le dashboard (le plus récent d'abord)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class Export(Base):
    """Un export marketplace (ZIP + listing SEO) pour un modèle validé."""

    __tablename__ = "exports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ondelete="CASCADE" : si un Model est supprimé, ses exports le sont aussi.
    # Fonctionne uniquement si `PRAGMA foreign_keys=ON` (cf. database.py).
    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    template = Column(String, nullable=False)            # "cults3d" | "printables" | ...

    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(JSON, nullable=False)
    price_suggested = Column(Float, nullable=False)

    # Paramètres d'impression recommandés (voir ARCHITECTURE pour le schéma JSON)
    print_params = Column(JSON, nullable=False)

    zip_path = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Setting(Base):
    """Key/value store des settings de l'application."""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)

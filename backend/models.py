"""Modèles SQLAlchemy — 3D Print Factory.

Schéma legacy actif :
- models    : modèle 3D généré (text/image-to-3d → glb → repair → stl + score)
- exports   : export marketplace (ZIP + listing SEO) pour un modèle validé
- settings  : key/value store (clés API, defaults, overrides prompts)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Model(Base):
    """Modèle 3D généré par le pipeline."""

    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    input_type = Column(String, nullable=False)
    input_text = Column(Text, nullable=True)
    input_image_path = Column(String, nullable=True)
    optimized_prompt = Column(Text, nullable=True)
    engine = Column(String, nullable=False, index=True)
    engine_task_id = Column(String, nullable=True)
    glb_path = Column(String, nullable=True)
    stl_path = Column(String, nullable=True)
    mesh_metrics = Column(JSON, nullable=True)
    repair_log = Column(Text, nullable=True)
    qc_score = Column(Float, nullable=True, index=True)
    qc_details = Column(JSON, nullable=True)
    validation = Column(String, nullable=False, default="pending", index=True)
    rejection_reason = Column(Text, nullable=True)
    screenshot_paths = Column(JSON, nullable=True)
    photo_paths = Column(JSON, nullable=True)
    image_engine = Column(String, nullable=True)
    cost_credits = Column(Integer, nullable=False, default=0)
    cost_eur_estimate = Column(Float, nullable=False, default=0.0)
    pipeline_status = Column(String, nullable=False, default="prompt", index=True)
    pipeline_error = Column(Text, nullable=True)
    pipeline_progress = Column(Integer, nullable=True)
    cancel_requested = Column(Integer, nullable=False, default=0)
    # Profil catégoriel détecté par l'optimizer (Phase 1.4) :
    # "Figurine" | "Fonctionnel" | "Déco" | NULL pour les modèles antérieurs.
    category = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class Export(Base):
    """Un export marketplace (ZIP + listing SEO) pour un modèle validé."""

    __tablename__ = "exports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(JSON, nullable=False)
    price_suggested = Column(Float, nullable=False)
    print_params = Column(JSON, nullable=False)
    zip_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Setting(Base):
    """Key/value store : clés API, defaults runtime."""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class Prompt(Base):
    """Bibliothèque versionnée des system prompts (Phase 1.5).

    Un seul `is_active=True` par `brick_id` à un instant T (contrainte
    appliquée par index partiel SQLite, cf. `_create_partial_indexes` dans
    database.py).
    """

    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brick_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    # Catégorie cible pour ce preset (None = générique, applicable à tous).
    category = Column(String, nullable=True, index=True)
    tags = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    # is_default = True pour le preset système initial (contenu = défaut du
    # registry au moment de la création). Sert d'ancrage pour le bouton
    # "Reset" et empêche la suppression depuis l'API.
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    usage_count = Column(Integer, nullable=False, default=0)
    avg_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class GenerationPrompt(Base):
    """Traçabilité : quel prompt a servi à quelle génération, par brique.

    Un Model peut avoir plusieurs lignes (1 par brique utilisée dans le
    pipeline : optimizer, scorer, seo_listing, etc.). PK composite
    (model_id, brick_id) garantit l'unicité.
    """

    __tablename__ = "generation_prompts"
    __table_args__ = (PrimaryKeyConstraint("model_id", "brick_id"),)

    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brick_id = Column(String, nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Recipe(Base):
    """Recette de génération (Phase 1.8) — preset config pour InputForm + batch.

    v1 minimaliste : engine + image_engine + category (hint) + notes.
    Phase 2.13 enrichira avec prompt FK, viewer_preset_id, slicer_preset_id,
    listing_template, etc.
    """

    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    engine = Column(String, nullable=False)
    image_engine = Column(String, nullable=True)
    category = Column(String, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class BatchJob(Base):
    """Job batch (Phase 1.9) — N items partageant la même recette.

    Statuts :
      - "pending"          : créé, worker pas encore démarré
      - "running"          : en cours, items en train d'être traités
      - "done"             : tous les items terminés (peut inclure des failed)
      - "cancelled"        : arrêté par l'utilisateur
      - "budget_exceeded"  : stoppé parce que `spent_eur >= max_budget_eur`
      - "failed"           : crash inattendu du worker
    """

    __tablename__ = "batch_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    status = Column(String, nullable=False, default="pending", index=True)
    total = Column(Integer, nullable=False, default=0)
    done = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    max_budget_eur = Column(Float, nullable=True)
    spent_eur = Column(Float, nullable=False, default=0.0)
    cancel_requested = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class ModelEvent(Base):
    """Timeline d'événements append-only sur un Model (Phase 2.10b).

    Une ligne par étape pipeline ou action utilisateur (created, optimized,
    generated, repaired, scored, regenerated, remeshed, repair_only).
    Sert à afficher un historique compact dans l'UI panneau modèle.

    Pas de backfill : l'historique commence au déploiement de la feature.
    """

    __tablename__ = "model_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String, nullable=False)
    details_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class BatchItem(Base):
    """Item d'un BatchJob — 1 ligne = 1 modèle à générer.

    Statuts :
      - "pending"   : pas encore traité
      - "running"   : pipeline en cours pour cet item
      - "done"      : modèle généré (peut être de mauvaise qualité, ce n'est
                       pas la même chose que approved/rejected)
      - "failed"    : pipeline a échoué (cf. `error`)
      - "skipped"   : sauté (cancel ou budget_exceeded avant traitement)
    """

    __tablename__ = "batch_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(
        Integer,
        ForeignKey("batch_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)   # ordre dans le batch (0-based)
    prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    model_id = Column(
        Integer, ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

"""Modèles SQLAlchemy — Printed.

Séparation Request (besoin humain) / Model3D (fichier technique).
Une request peut avoir 0, 1 ou N models3d (génération IA, upload manuel,
re-génération…). Les utilisateurs sont identifiés par TEXT id (hex random)
pour éviter l'énumération séquentielle qu'on aurait avec des int auto.

Tables :
- users          : comptes (employee | validator | operator | admin)
- requests       : demandes (workflow complet avec state machine)
- models3d       : fichiers 3D attachés à une request (ai_generated / manual_upload)
- comments       : timeline messages + events système
- votes          : upvote par (user, request) unique
- library_items  : archivage des pièces validées pour réutilisation
- settings       : key/value store (garde compat avec l'app précédente)
"""

from __future__ import annotations

import secrets
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
    UniqueConstraint,
)

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id() -> str:
    """16 hex chars (8 bytes) — collision improbable, énumération infaisable."""
    return secrets.token_hex(8)


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_gen_id)
    email = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    # Rôle simple V1 (employee | validator | operator | admin). Plus tard
    # potentiellement une vraie table roles/permissions.
    role = Column(String, nullable=False, default="employee", index=True)
    department = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# Requests (demandes)
# --------------------------------------------------------------------------- #

class Request(Base):
    """Demande d'une pièce imprimée.

    Source de vérité pour le workflow. Le fichier 3D est séparé (Model3D).
    Tous les timestamps sont stockés en UTC.
    """

    __tablename__ = "requests"

    id = Column(String, primary_key=True, default=_gen_id)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    author_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Statuts (cf. workflow.py) :
    # draft | submitted | under_review | needs_info | approved | printing
    # | delivered | feedback | archived | rejected | on_hold
    status = Column(String, nullable=False, default="draft", index=True)
    priority = Column(String, nullable=False, default="normal")   # low | normal | high | urgent
    department = Column(String, nullable=True, index=True)
    category = Column(String, nullable=True, index=True)

    # Validation
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    review_notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    hold_reason = Column(Text, nullable=True)
    hold_until = Column(DateTime(timezone=True), nullable=True)

    # Impression
    print_material = Column(String, nullable=True)   # "PETG" | "PLA" | "ABS" | ...
    print_infill = Column(Integer, nullable=True)    # % remplissage
    print_cost_estimate = Column(Float, nullable=True)
    print_time_estimate = Column(String, nullable=True)   # "2h40"

    # Feedback terrain
    feedback_text = Column(Text, nullable=True)
    feedback_rating = Column(Integer, nullable=True)      # 1-5 étoiles
    feedback_at = Column(DateTime(timezone=True), nullable=True)

    # Méta dénormalisée pour tri rapide
    vote_count = Column(Integer, nullable=False, default=0, index=True)
    view_count = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# Model3D (fichiers 3D rattachés à une request)
# --------------------------------------------------------------------------- #

class Model3D(Base):
    """Fichier 3D attaché à une request.

    Une même request peut avoir plusieurs Model3D (plusieurs générations IA,
    upload manuel en remplacement, re-modélisation par le validateur). Un
    seul à la fois a `is_selected=True` — c'est celui qu'on imprime.
    """

    __tablename__ = "models3d"

    id = Column(String, primary_key=True, default=_gen_id)
    request_id = Column(
        String,
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provenance
    source_type = Column(String, nullable=False)    # 'ai_generated' | 'manual_upload' | 'validator_upload'
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=True)

    # Fichier
    file_path = Column(String, nullable=True)        # chemin relatif sous /data/models/
    file_name = Column(String, nullable=True)        # nom d'origine (pour download)
    file_size_bytes = Column(Integer, nullable=True)
    file_format = Column(String, nullable=True)      # 'stl' | 'obj' | 'glb' | '3mf'
    thumbnail_path = Column(String, nullable=True)

    # Génération IA (source_type='ai_generated')
    engine = Column(String, nullable=True)           # 'meshy' | 'tripo'
    engine_task_id = Column(String, nullable=True)   # pour remesh ultérieur
    prompt_input = Column(Text, nullable=True)       # input utilisateur brut
    prompt_optimized = Column(Text, nullable=True)   # prompt post-Claude
    generation_cost_eur = Column(Float, nullable=True)
    generation_time_s = Column(Integer, nullable=True)

    # Scoring qualité (tourne sur TOUT fichier, généré ou uploadé)
    quality_score = Column(Float, nullable=True)     # 0-10
    is_manifold = Column(Boolean, nullable=True)
    is_watertight = Column(Boolean, nullable=True)
    min_thickness_mm = Column(Float, nullable=True)
    max_overhang_deg = Column(Float, nullable=True)
    face_count = Column(Integer, nullable=True)
    component_count = Column(Integer, nullable=True)
    dimensions_mm = Column(String, nullable=True)    # "150x120x80"
    is_printable = Column(Boolean, nullable=True)    # verdict global
    score_details = Column(JSON, nullable=True)      # mesh_metrics + qc_details

    # État de l'objet
    is_selected = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)

    # Suivi pipeline IA (équivalent de l'ancien Model.pipeline_* pour les
    # génération asynchrones)
    pipeline_status = Column(String, nullable=True, index=True)     # prompt|generating|repairing|scoring|ready|failed|cancelled
    pipeline_progress = Column(Integer, nullable=True)              # 0-100
    pipeline_error = Column(Text, nullable=True)
    cancel_requested = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# --------------------------------------------------------------------------- #
# Comments (timeline + events)
# --------------------------------------------------------------------------- #

class Comment(Base):
    """Entrée dans la timeline d'une request.

    Couvre :
    - les commentaires humains (`comment_type='message'`)
    - les changements de statut générés par le workflow (`'status_change'`)
    - les événements système (scoring done, impression lancée…) (`'system'`)
    - les Q/A explicites (`'question'` / `'answer'`)
    """

    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=_gen_id)
    request_id = Column(
        String,
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)

    # Pièce jointe optionnelle (photo, STL de référence, PDF…)
    attachment_path = Column(String, nullable=True)
    attachment_type = Column(String, nullable=True)   # 'image' | 'model' | 'document'

    comment_type = Column(String, nullable=False, default="message")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# --------------------------------------------------------------------------- #
# Votes
# --------------------------------------------------------------------------- #

class Vote(Base):
    """Upvote sur une request. Un user ne peut voter qu'une fois par request."""

    __tablename__ = "votes"
    __table_args__ = (PrimaryKeyConstraint("user_id", "request_id"),)

    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    request_id = Column(
        String,
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


# --------------------------------------------------------------------------- #
# Library (pièces archivées réutilisables)
# --------------------------------------------------------------------------- #

class LibraryItem(Base):
    """Pièce validée archivée dans la bibliothèque pour réutilisation.

    Créée automatiquement lors de la transition `archive` (workflow). Garde
    une référence vers la request d'origine + le Model3D figé qu'on réimprimera.
    """

    __tablename__ = "library_items"

    id = Column(String, primary_key=True, default=_gen_id)
    request_id = Column(String, ForeignKey("requests.id"), nullable=False, index=True)
    model3d_id = Column(String, ForeignKey("models3d.id"), nullable=False)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)
    tags = Column(JSON, nullable=True)               # ["capteur", "support", "ligne3"]
    department = Column(String, nullable=True, index=True)

    reprint_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)


# --------------------------------------------------------------------------- #
# Model + Export — legacy, conservés pour compat (routeurs non migrés)
# --------------------------------------------------------------------------- #

class Model(Base):
    """Modèle 3D legacy (ancienne app). Table 'models' conservée intacte."""

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


# Settings (key/value) — garde compat avec l'app précédente
# --------------------------------------------------------------------------- #

class Setting(Base):
    """Key/value store pour config runtime (clés API, defaults, prompt instructions…).

    Préservé tel quel depuis l'app précédente pour que config.get_api_key() et
    app_settings.get_setting() continuent à fonctionner sans refacto.
    """

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)

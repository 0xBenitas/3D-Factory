"""Base de données SQLite + session SQLAlchemy.

Expose :
- `engine`        : SQLAlchemy engine (SQLite)
- `SessionLocal`  : factory de sessions
- `Base`          : base declarative pour les models ORM
- `get_db()`      : dependency FastAPI (générateur de session)
- `init_db()`     : crée les tables + seed settings + seed demo users/requests

Note : les anciennes tables `models` / `exports` (schéma 3D-Factory précédent)
peuvent exister dans le fichier SQLite si on réutilise un `DATA_DIR` existant.
Elles ne sont pas droppées automatiquement — inoffensives, elles cohabitent
le temps de la transition. Un script dédié `scripts/cleanup_legacy.py` peut
les supprimer après le cutover.
"""

from __future__ import annotations

import logging
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import (
    ANTHROPIC_API_KEY,
    DATA_DIR,
    DB_PATH,
    DEFAULT_ENGINE,
    DEFAULT_IMAGE_ENGINE,
    DEFAULT_TEMPLATE,
    MAX_DAILY_BUDGET_EUR,
    MESHY_API_KEY,
    STABILITY_API_KEY,
    TRIPO_API_KEY,
)

logger = logging.getLogger(__name__)


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_conn, connection_record) -> None:
    """Réglages SQLite à chaque connexion :

    - WAL mode : lecteurs ne bloquent pas les écrivains (utile avec les
      BackgroundTasks en parallèle du dashboard).
    - foreign_keys=ON : SQLite les ignore par défaut ; sans ça, nos FK
      (ex. `Model3D.request_id → requests.id ON DELETE CASCADE`) sont
      purement décoratives.
    - synchronous=NORMAL : bon compromis durabilité/perf avec WAL.
    """
    if not hasattr(dbapi_conn, "executescript"):
        return
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def get_db() -> Iterator[Session]:
    """Dependency FastAPI : fournit une session et la referme proprement."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialise la BDD : création des tables, seed settings, seed démo.

    Idempotent : chaque `_seed_*` vérifie avant d'insérer, donc redémarrer
    l'app n'écrase rien.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Enregistre tous les mappers sur Base.metadata (import avant create_all).
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _seed_default_settings()
    _seed_demo_users()
    _seed_demo_requests()
    logger.info("Database initialized at %s", DB_PATH)


# --------------------------------------------------------------------------- #
# Seeds
# --------------------------------------------------------------------------- #

def _seed_default_settings() -> None:
    """Settings de base + clés API depuis .env (si présentes)."""
    from models import Setting

    defaults = {
        "default_engine": DEFAULT_ENGINE,
        "default_image_engine": DEFAULT_IMAGE_ENGINE,
        "default_template": DEFAULT_TEMPLATE,
        "max_daily_budget_eur": str(MAX_DAILY_BUDGET_EUR),
    }
    api_key_seeds = {
        "api_key_anthropic": ANTHROPIC_API_KEY,
        "api_key_meshy": MESHY_API_KEY,
        "api_key_tripo": TRIPO_API_KEY,
        "api_key_stability": STABILITY_API_KEY,
    }

    with SessionLocal() as db:
        for key, value in defaults.items():
            if db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        for key, value in api_key_seeds.items():
            if value and db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        db.commit()


# Utilisateurs de démo (mot de passe commun : "demo1234"). Ne sont créés que
# si la table est vide — ne pas appeler en prod sans précaution.
DEMO_PASSWORD = "demo1234"
DEMO_USERS = [
    {"email": "marc@demo.local",   "display_name": "Marc Dupont",   "role": "employee",  "department": "Production Ligne 3"},
    {"email": "sophie@demo.local", "display_name": "Sophie Laurent", "role": "validator", "department": "Bureau d'études"},
    {"email": "thomas@demo.local", "display_name": "Thomas Martin",  "role": "operator",  "department": "Atelier impression"},
    {"email": "admin@demo.local",  "display_name": "Admin",          "role": "admin",     "department": "Direction technique"},
]


def _hash_password(plain: str) -> str:
    """Bcrypt hash. Import local pour laisser `init_db` fonctionner même
    si bcrypt est momentanément absent en dev (seed sera skippé).
    """
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _seed_demo_users() -> None:
    from models import User

    with SessionLocal() as db:
        if db.query(User).count() > 0:
            return  # déjà seedée ou utilisateurs réels présents

        try:
            pw_hash = _hash_password(DEMO_PASSWORD)
        except ImportError:
            logger.warning("bcrypt not installed — skipping demo user seed")
            return

        for u in DEMO_USERS:
            db.add(User(
                email=u["email"],
                display_name=u["display_name"],
                role=u["role"],
                department=u["department"],
                password_hash=pw_hash,
            ))
        db.commit()
        logger.info("Seeded %d demo users (password: %s)", len(DEMO_USERS), DEMO_PASSWORD)


# Requests de démo pour illustrer différents états du workflow.
DEMO_REQUESTS = [
    {
        "title": "Support capteur vibration — Ligne 3",
        "description": (
            "Le support actuel en métal vibre trop et fausse les mesures du capteur "
            "de température. Il faudrait un support imprimé avec un amortissement."
        ),
        "author_email": "marc@demo.local",
        "status": "archived",
        "category": "Outillage",
        "priority": "high",
    },
    {
        "title": "Gabarit de perçage panneau arrière",
        "description": (
            "On perce 6 trous sur chaque panneau à la main avec un marqueur. "
            "Un gabarit de perçage accélérerait le process et réduirait les erreurs."
        ),
        "author_email": "marc@demo.local",
        "status": "approved",
        "category": "Gabarit",
        "priority": "normal",
    },
    {
        "title": "Cache-câbles poste soudure",
        "description": (
            "Les câbles traînent au sol et on se prend les pieds dedans. "
            "Un guide-câbles à clipser sur le pied de table serait top."
        ),
        "author_email": "sophie@demo.local",
        "status": "submitted",
        "category": "Support",
        "priority": "normal",
    },
]


def _seed_demo_requests() -> None:
    from datetime import datetime, timezone
    from models import Request, User

    with SessionLocal() as db:
        if db.query(Request).count() > 0:
            return

        emails = {u["email"] for u in DEMO_USERS}
        users_by_email = {
            u.email: u
            for u in db.query(User).filter(User.email.in_(emails)).all()
        }
        if not users_by_email:
            return  # pas de users → pas de requests (intégrité FK)

        now = datetime.now(timezone.utc)
        for r in DEMO_REQUESTS:
            author = users_by_email.get(r["author_email"])
            if author is None:
                continue
            req = Request(
                title=r["title"],
                description=r["description"],
                author_id=author.id,
                status=r["status"],
                priority=r["priority"],
                department=author.department,
                category=r["category"],
                submitted_at=now if r["status"] != "draft" else None,
            )
            db.add(req)
        db.commit()
        logger.info("Seeded %d demo requests", len(DEMO_REQUESTS))

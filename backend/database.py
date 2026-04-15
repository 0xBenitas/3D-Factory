"""Base de données SQLite + session SQLAlchemy.

Expose :
- `engine`           : SQLAlchemy engine (SQLite)
- `SessionLocal`     : factory de sessions
- `Base`             : base declarative pour les models ORM
- `get_db()`         : dependency FastAPI (générateur de session)
- `init_db()`        : crée les tables + seed les settings par défaut
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


# SQLite + FastAPI : `check_same_thread=False` est requis parce que la
# session peut être utilisée depuis un thread différent (BackgroundTasks).
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_conn, connection_record) -> None:
    """À chaque nouvelle connexion SQLite :

    - WAL mode : les lecteurs ne bloquent plus les écrivains (critique
      pour Phase 2 où les BackgroundTasks écrivent pendant que le
      dashboard lit).
    - foreign_keys=ON : SQLite les ignore par défaut — sans ça, nos FK
      (ex. `Export.model_id → models.id` avec ondelete=CASCADE) sont
      purement décoratives.
    - synchronous=NORMAL : bon compromis durabilité/perf avec WAL.
    """
    # Ne s'applique qu'aux connexions SQLite (pour protéger contre
    # d'autres engines qui pourraient partager cet écouteur).
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
    """Initialise la BDD : crée le dossier data, les tables, seed les settings.

    Idempotent : peut être appelé à chaque démarrage sans effet de bord si
    les tables et les settings existent déjà.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Import local pour éviter l'import circulaire (models importe Base d'ici).
    import models  # noqa: F401  (enregistre les mappers sur Base.metadata)

    Base.metadata.create_all(bind=engine)
    _apply_column_migrations()
    _seed_default_settings()
    logger.info("Database initialized at %s", DB_PATH)


def _apply_column_migrations() -> None:
    """Ajoute les colonnes manquantes sur des BDD existantes.

    `create_all` ne modifie jamais les tables existantes ; on complète à
    la main pour les colonnes ajoutées après coup. Idempotent.
    """
    migrations = [
        # (table, column, ddl)
        ("models", "pipeline_progress", "INTEGER"),
        ("models", "cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if column not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                )
                logger.info("Added column %s.%s", table, column)


def _seed_default_settings() -> None:
    """Insère les settings par défaut s'ils ne sont pas déjà présents."""
    from models import Setting  # import local pour éviter le cycle

    defaults = {
        "default_engine": DEFAULT_ENGINE,
        "default_image_engine": DEFAULT_IMAGE_ENGINE,
        "default_template": DEFAULT_TEMPLATE,
        "max_daily_budget_eur": str(MAX_DAILY_BUDGET_EUR),
    }
    # Seed des clés API depuis .env si présentes (elles restent modifiables via l'UI ensuite).
    api_key_seeds = {
        "api_key_anthropic": ANTHROPIC_API_KEY,
        "api_key_meshy": MESHY_API_KEY,
        "api_key_tripo": TRIPO_API_KEY,
        "api_key_stability": STABILITY_API_KEY,
    }

    with SessionLocal() as db:
        for key, value in defaults.items():
            existing = db.get(Setting, key)
            if existing is None:
                db.add(Setting(key=key, value=value))
        for key, value in api_key_seeds.items():
            if value and db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        db.commit()

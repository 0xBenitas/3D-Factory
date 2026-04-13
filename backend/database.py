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

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import (
    DATA_DIR,
    DB_PATH,
    DEFAULT_ENGINE,
    DEFAULT_IMAGE_ENGINE,
    DEFAULT_TEMPLATE,
    MAX_DAILY_BUDGET_EUR,
)

logger = logging.getLogger(__name__)


# SQLite + FastAPI : `check_same_thread=False` est requis parce que la
# session peut être utilisée depuis un thread différent (BackgroundTasks).
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)

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
    _seed_default_settings()
    logger.info("Database initialized at %s", DB_PATH)


def _seed_default_settings() -> None:
    """Insère les settings par défaut s'ils ne sont pas déjà présents."""
    from models import Setting  # import local pour éviter le cycle

    defaults = {
        "default_engine": DEFAULT_ENGINE,
        "default_image_engine": DEFAULT_IMAGE_ENGINE,
        "default_template": DEFAULT_TEMPLATE,
        "max_daily_budget_eur": str(MAX_DAILY_BUDGET_EUR),
    }

    with SessionLocal() as db:
        for key, value in defaults.items():
            existing = db.get(Setting, key)
            if existing is None:
                db.add(Setting(key=key, value=value))
        db.commit()

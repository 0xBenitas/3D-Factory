"""Base de données SQLite + session SQLAlchemy.

Expose :
- `engine`        : SQLAlchemy engine (SQLite)
- `SessionLocal`  : factory de sessions
- `Base`          : base declarative pour les models ORM
- `get_db()`      : dependency FastAPI (générateur de session)
- `init_db()`     : crée les tables + seed settings
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
    - foreign_keys=ON : SQLite les ignore par défaut.
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
    """Initialise la BDD : tables, index partiels, seed settings,
    migration des overrides Settings → biblio Prompt (Phase 1.5).

    Idempotent : chaque étape vérifie avant d'agir, donc redémarrer
    l'app n'écrase rien.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Enregistre tous les mappers sur Base.metadata (import avant create_all).
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_partial_indexes()
    _ensure_generation_prompts_cascade()
    _seed_default_settings()
    _seed_prompt_library_and_migrate_overrides()
    logger.info("Database initialized at %s", DB_PATH)


def _ensure_partial_indexes() -> None:
    """SQLAlchemy ne pose pas d'index partiels via Column → on les crée à la main.

    Garantit qu'au plus un Prompt est `is_active=True` par `brick_id`.
    """
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_prompts_active_per_brick "
            "ON prompts(brick_id) WHERE is_active = 1"
        )
        conn.commit()


def _ensure_generation_prompts_cascade() -> None:
    """Migre `generation_prompts.prompt_id` FK pour avoir ON DELETE CASCADE.

    SQLAlchemy `create_all` ne modifie pas les FK des tables existantes, et
    SQLite n'a pas d'ALTER pour FK. Donc si la table a été créée avant le
    fix, elle a une FK sans CASCADE → on recrée proprement (rename + copy
    + drop). Idempotent : si la FK est déjà CASCADE, no-op.
    """
    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='generation_prompts'"
        ).fetchone()
        if row is None:
            return  # première création — create_all s'en occupe
        sql = (row[0] or "").lower()
        # Cherche "references prompts" suivi (proche) de "on delete cascade".
        # Si déjà présent → rien à faire.
        if "references prompts" in sql and "on delete cascade" in sql.split("references prompts", 1)[1][:80]:
            return
        logger.info("Migrating generation_prompts FK → ON DELETE CASCADE")
        conn.exec_driver_sql("ALTER TABLE generation_prompts RENAME TO generation_prompts_old")
        conn.exec_driver_sql(
            """
            CREATE TABLE generation_prompts (
                model_id INTEGER NOT NULL,
                brick_id VARCHAR NOT NULL,
                prompt_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (model_id, brick_id),
                FOREIGN KEY(model_id) REFERENCES models (id) ON DELETE CASCADE,
                FOREIGN KEY(prompt_id) REFERENCES prompts (id) ON DELETE CASCADE
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO generation_prompts (model_id, brick_id, prompt_id, created_at) "
            "SELECT model_id, brick_id, prompt_id, created_at FROM generation_prompts_old"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_generation_prompts_model_id ON generation_prompts(model_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_generation_prompts_prompt_id ON generation_prompts(prompt_id)"
        )
        conn.exec_driver_sql("DROP TABLE generation_prompts_old")
        conn.commit()


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


def _seed_prompt_library_and_migrate_overrides() -> None:
    """Crée le preset "Default" pour chaque brique du registry, puis migre
    les overrides Settings (`prompt_override_<brick_id>`) en presets
    "User custom" actifs (option A — clean migration).

    Idempotent :
    - Le preset Default n'est créé qu'au premier passage (filtre `is_default=True`)
    - Le preset User custom n'est créé que si la ligne settings existe encore ;
      après migration, la ligne settings est supprimée → ne sera plus migrée
    - Si aucun preset n'est `is_active=True` pour une brique, le Default
      est promu actif (cas du tout premier boot, ou si l'utilisateur a
      supprimé son User custom)
    """
    from models import Prompt, Setting
    from services.prompt_registry import list_bricks

    with SessionLocal() as db:
        for brick in list_bricks():
            existing_default = (
                db.query(Prompt)
                .filter(Prompt.brick_id == brick.id, Prompt.is_default.is_(True))
                .first()
            )
            if existing_default is None:
                db.add(Prompt(
                    brick_id=brick.id,
                    name="Default",
                    content=brick.default,
                    is_default=True,
                    is_active=False,
                    notes="Preset système — synchronisé avec services/prompt_registry.py",
                ))

            override_key = f"prompt_override_{brick.id}"
            override_row = db.get(Setting, override_key)
            if override_row is not None:
                override_value = (override_row.value or "").strip()
                if override_value:
                    # Migrer l'override actif → preset "User custom"
                    db.add(Prompt(
                        brick_id=brick.id,
                        name="User custom (migrated)",
                        content=override_value,
                        is_default=False,
                        is_active=True,
                        notes="Migré depuis prompt_override_* le 2026-04-25.",
                    ))
                # Drop la ligne settings dans tous les cas (vide ou pleine).
                db.delete(override_row)

        db.commit()

        # Une seule passe d'activation par défaut : pour chaque brique sans
        # prompt actif, on active le Default.
        for brick in list_bricks():
            has_active = db.query(Prompt).filter(
                Prompt.brick_id == brick.id,
                Prompt.is_active.is_(True),
            ).first()
            if has_active is None:
                default_row = db.query(Prompt).filter(
                    Prompt.brick_id == brick.id,
                    Prompt.is_default.is_(True),
                ).first()
                if default_row is not None:
                    default_row.is_active = True
        db.commit()

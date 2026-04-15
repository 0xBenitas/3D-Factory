"""Configuration centrale du backend.

Charge `.env` (si présent) dans `os.environ` via un petit parseur maison,
puis expose les constantes de configuration utilisées par le reste de
l'application. Aucune dépendance externe requise (pas de `python-dotenv`
ni `pydantic-settings`) — on reste strictement sur les deps listées
dans `ARCHITECTURE_FINALE.md`.
"""

from __future__ import annotations

import os
from pathlib import Path


# --------------------------------------------------------------------------- #
# Loader .env minimaliste
# --------------------------------------------------------------------------- #

def _load_env_file(env_path: Path) -> None:
    """Parse un fichier `.env` basique et peuple `os.environ` sans écraser
    les variables déjà définies (priorité à l'environnement réel du
    processus, utile en prod où les variables viennent du service).
    """
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # Support commentaire en fin de ligne: VAR=val  # commentaire
        if "#" in value and not (value.startswith('"') or value.startswith("'")):
            value = value.split("#", 1)[0].strip()
        # Strip guillemets optionnels
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


# Racine du projet = parent de `backend/`
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_load_env_file(PROJECT_ROOT / ".env")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _resolve_data_dir(raw: str) -> Path:
    """Si le chemin est relatif, il est résolu depuis `backend/` (cohérent
    avec `DATA_DIR=./data` de l'archi, et avec le fait qu'uvicorn est
    lancé depuis `backend/` en prod — cf. `deploy.sh`).
    """
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path(__file__).resolve().parent / p).resolve()
    return p


# --------------------------------------------------------------------------- #
# Constantes publiques
# --------------------------------------------------------------------------- #

# Auth
APP_USER: str = _get("APP_USER", "admin")
APP_PASS: str = _get("APP_PASS", "")

# APIs externes (peuvent être vides en Phase 1) — valeurs initiales depuis .env.
# À l'exécution, `get_api_key()` privilégie la valeur stockée en BDD (seedée depuis
# ces constantes au 1er boot, puis modifiable via PUT /api/settings).
ANTHROPIC_API_KEY: str = _get("ANTHROPIC_API_KEY", "")
MESHY_API_KEY: str = _get("MESHY_API_KEY", "")
TRIPO_API_KEY: str = _get("TRIPO_API_KEY", "")
STABILITY_API_KEY: str = _get("STABILITY_API_KEY", "")


_API_KEY_ENV_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "meshy": "MESHY_API_KEY",
    "tripo": "TRIPO_API_KEY",
    "stability": "STABILITY_API_KEY",
}


def get_api_key(name: str) -> str:
    """Résout une clé API à l'exécution.

    Priorité : valeur stockée en BDD (table `settings`, clé `api_key_<name>`)
    puis variable d'environnement. Permet de configurer/mettre à jour les clés
    via l'UI sans redémarrer.
    """
    key = name.lower()
    env_var = _API_KEY_ENV_MAP.get(key)
    if env_var is None:
        return ""
    try:
        from database import SessionLocal
        from models import Setting

        with SessionLocal() as db:
            row = db.get(Setting, f"api_key_{key}")
            if row and row.value:
                return str(row.value)
    except Exception:
        pass
    return os.environ.get(env_var, "")

# Défauts métier
DEFAULT_ENGINE: str = _get("DEFAULT_ENGINE", "meshy")
DEFAULT_IMAGE_ENGINE: str = _get("DEFAULT_IMAGE_ENGINE", "stability")
DEFAULT_TEMPLATE: str = _get("DEFAULT_TEMPLATE", "cults3d")
MAX_DAILY_BUDGET_EUR: float = float(_get("MAX_DAILY_BUDGET_EUR", "2.00"))

# Claude API — overridable pour ajuster qualité/coût sans redéployer.
# La ligne Sonnet 4.5 est le successeur direct de celle citée par les specs
# ("Sonnet pour rapport qualité/coût optimal") et reste moins chère qu'Opus.
CLAUDE_MODEL: str = _get("CLAUDE_MODEL", "claude-sonnet-4-5")

# Serveur
HOST: str = _get("HOST", "0.0.0.0")
PORT: int = int(_get("PORT", "8000"))
DATA_DIR: Path = _resolve_data_dir(_get("DATA_DIR", "./data"))

# Chemins dérivés
DB_PATH: Path = DATA_DIR / "db.sqlite"
FRONTEND_DIST: Path = PROJECT_ROOT / "frontend" / "dist"

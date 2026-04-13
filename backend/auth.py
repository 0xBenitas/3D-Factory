"""Basic Auth — middleware HTTP pour FastAPI.

Règles :
- `/api/health` est public (monitoring externe / uptime).
- Les requêtes OPTIONS (préflight CORS) passent sans challenge.
- Tout le reste (API + frontend static) exige Basic Auth.
- Comparaison des credentials en temps constant (`secrets.compare_digest`).
- Un échec renvoie 401 avec le header `WWW-Authenticate` pour déclencher
  la popup de login du navigateur.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import PlainTextResponse

import config

# Chemins qui ne nécessitent pas d'auth
_PUBLIC_PATHS: frozenset[str] = frozenset({"/api/health"})

# Realm affiché dans la popup Basic Auth du navigateur
_REALM = "3D Factory"


def _unauthorized(reason: str = "Authentication required") -> Response:
    return PlainTextResponse(
        status_code=401,
        content=reason,
        headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
    )


def _check_credentials(header_value: str) -> bool:
    """Parse le header `Authorization` et compare aux credentials attendus."""
    if not header_value or not header_value.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header_value[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    user, password = decoded.split(":", 1)

    expected_user = config.APP_USER or ""
    expected_pass = config.APP_PASS or ""

    # Comparaison en temps constant pour éviter les timing attacks.
    user_ok = secrets.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = secrets.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
    return user_ok and pass_ok


async def basic_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Middleware ASGI pour FastAPI : vérifie Basic Auth sur toutes les
    routes sauf les chemins publics et les requêtes OPTIONS.
    """
    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    # Refus explicite si pas de mot de passe configuré (évite un accès libre).
    if not config.APP_PASS:
        return _unauthorized("Server auth not configured (APP_PASS missing)")

    auth_header = request.headers.get("authorization", "")
    if not _check_credentials(auth_header):
        return _unauthorized()

    return await call_next(request)

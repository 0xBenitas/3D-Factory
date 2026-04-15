"""Router : GET /api/credits — balance des APIs externes.

Objectif : afficher en temps réel le solde de crédits Meshy / Stability /
Tripo dans l'UI, pour que l'utilisateur sache quand recharger. Anthropic
n'exposant pas d'endpoint de solde côté API utilisateur, on fallback sur
la conso cumulée du mois calculée depuis la BDD locale.

Design :
- Appels parallèles (`asyncio.gather`) avec timeout individuel (5s) pour
  qu'une API lente ne bloque jamais le retour global.
- Cache en mémoire avec TTL de 5 min pour ne pas spammer les fournisseurs
  à chaque navigation (ils ont des rate limits). Lock asynchrone pour
  éviter le thundering herd au premier hit après expiration.
- Paramètre `?refresh=1` pour forcer un cache miss (utile pour le bouton
  manuel côté UI).
- Les erreurs sont converties en messages courts, **sans** inclure le
  texte de la réponse HTTP (qui peut contenir des fragments de la clé
  dans certains cas — principe de prudence).
- La clé API n'est jamais renvoyée dans la réponse.

Auth : protégé par le middleware Basic Auth global (cf. auth.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from database import get_db
from models import Model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credits", tags=["credits"])

CACHE_TTL_S = 300           # 5 min — compromis fraîcheur / rate limit
PROVIDER_TIMEOUT_S = 5.0    # Chaque provider a 5s max avant timeout


# --------------------------------------------------------------------------- #
# Cache global
# --------------------------------------------------------------------------- #

@dataclass
class _CacheEntry:
    data: dict[str, Any]
    expires_at: float


_cache: _CacheEntry | None = None
_cache_lock = asyncio.Lock()


# --------------------------------------------------------------------------- #
# Schéma public
# --------------------------------------------------------------------------- #

class ProviderCredits(BaseModel):
    available: bool                 # True si on a pu lire le solde
    credits: float | None = None    # Solde brut (en crédits fournisseur)
    unit: str = "credits"           # "credits" | "eur" (fallback Anthropic)
    month_cost_eur: float | None = None  # Utilisé pour Anthropic (fallback)
    error: str | None = None        # Raison courte si indisponible
    fetched_at: str                 # ISO-8601 UTC


class CreditsResponse(BaseModel):
    meshy: ProviderCredits
    stability: ProviderCredits
    tripo: ProviderCredits
    anthropic: ProviderCredits
    cache_hit: bool


# --------------------------------------------------------------------------- #
# Fetchers individuels — chacun catch tout pour ne jamais casser gather
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_configured(provider: str) -> ProviderCredits:
    return ProviderCredits(
        available=False,
        error="API key not configured",
        fetched_at=_now_iso(),
    )


async def _fetch_meshy() -> ProviderCredits:
    key = config.get_api_key("meshy")
    if not key:
        return _not_configured("meshy")
    try:
        async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT_S) as client:
            resp = await client.get(
                "https://api.meshy.ai/openapi/v1/balance",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            return ProviderCredits(available=False, error="invalid API key", fetched_at=_now_iso())
        if resp.status_code >= 400:
            return ProviderCredits(
                available=False,
                error=f"HTTP {resp.status_code}",
                fetched_at=_now_iso(),
            )
        data = resp.json()
        # Meshy renvoie {"balance": 1585}
        balance = data.get("balance")
        if balance is None:
            return ProviderCredits(available=False, error="no 'balance' field", fetched_at=_now_iso())
        return ProviderCredits(
            available=True,
            credits=float(balance),
            unit="credits",
            fetched_at=_now_iso(),
        )
    except httpx.TimeoutException:
        return ProviderCredits(available=False, error="timeout", fetched_at=_now_iso())
    except Exception as exc:
        logger.warning("Meshy balance fetch failed: %s", type(exc).__name__)
        return ProviderCredits(available=False, error=type(exc).__name__, fetched_at=_now_iso())


async def _fetch_stability() -> ProviderCredits:
    key = config.get_api_key("stability")
    if not key:
        return _not_configured("stability")
    try:
        async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT_S) as client:
            resp = await client.get(
                "https://api.stability.ai/v1/user/balance",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            return ProviderCredits(available=False, error="invalid API key", fetched_at=_now_iso())
        if resp.status_code >= 400:
            return ProviderCredits(
                available=False,
                error=f"HTTP {resp.status_code}",
                fetched_at=_now_iso(),
            )
        data = resp.json()
        # Stability renvoie {"credits": 16}
        credits = data.get("credits")
        if credits is None:
            return ProviderCredits(available=False, error="no 'credits' field", fetched_at=_now_iso())
        return ProviderCredits(
            available=True,
            credits=float(credits),
            unit="credits",
            fetched_at=_now_iso(),
        )
    except httpx.TimeoutException:
        return ProviderCredits(available=False, error="timeout", fetched_at=_now_iso())
    except Exception as exc:
        logger.warning("Stability balance fetch failed: %s", type(exc).__name__)
        return ProviderCredits(available=False, error=type(exc).__name__, fetched_at=_now_iso())


async def _fetch_tripo() -> ProviderCredits:
    key = config.get_api_key("tripo")
    if not key:
        return _not_configured("tripo")
    try:
        async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT_S) as client:
            resp = await client.get(
                "https://api.tripo3d.ai/v2/openapi/user/balance",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            return ProviderCredits(available=False, error="invalid API key", fetched_at=_now_iso())
        if resp.status_code >= 400:
            return ProviderCredits(
                available=False,
                error=f"HTTP {resp.status_code}",
                fetched_at=_now_iso(),
            )
        data = resp.json()
        # Tripo renvoie {"code":0,"data":{"balance":X,"frozen":Y}}
        if data.get("code") != 0:
            return ProviderCredits(
                available=False,
                error=f"API error code {data.get('code')}",
                fetched_at=_now_iso(),
            )
        balance = (data.get("data") or {}).get("balance")
        if balance is None:
            return ProviderCredits(available=False, error="no 'balance' field", fetched_at=_now_iso())
        return ProviderCredits(
            available=True,
            credits=float(balance),
            unit="credits",
            fetched_at=_now_iso(),
        )
    except httpx.TimeoutException:
        return ProviderCredits(available=False, error="timeout", fetched_at=_now_iso())
    except Exception as exc:
        logger.warning("Tripo balance fetch failed: %s", type(exc).__name__)
        return ProviderCredits(available=False, error=type(exc).__name__, fetched_at=_now_iso())


def _anthropic_month_cost(db: Session) -> float:
    """Somme de `cost_eur_estimate` des modèles créés depuis le 1er du mois UTC.

    Approximation : inclut TOUS les coûts (Meshy, Stability, Claude…), pas
    uniquement Claude. Mais comme on veut surtout un ordre de grandeur de la
    dépense mensuelle pour l'UI, c'est acceptable.
    """
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    total = (
        db.query(func.coalesce(func.sum(Model.cost_eur_estimate), 0.0))
        .filter(Model.created_at >= month_start)
        .scalar()
        or 0.0
    )
    return round(float(total), 2)


def _build_anthropic(db: Session) -> ProviderCredits:
    key = config.get_api_key("anthropic")
    if not key:
        return _not_configured("anthropic")
    return ProviderCredits(
        available=True,
        month_cost_eur=_anthropic_month_cost(db),
        unit="eur",
        error=None,
        fetched_at=_now_iso(),
    )


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@router.get("", response_model=CreditsResponse)
async def get_credits(
    refresh: bool = False,
    db: Session = Depends(get_db),
) -> CreditsResponse:
    """Retourne le solde des APIs externes (cache 5 min).

    - `?refresh=1` force un nouvel appel aux fournisseurs.
    - Anthropic : pas d'endpoint de balance → fallback = cumul mensuel
      local basé sur `models.cost_eur_estimate`.
    """
    global _cache

    now = time.monotonic()

    async with _cache_lock:
        if not refresh and _cache is not None and _cache.expires_at > now:
            data = _cache.data
            # Anthropic change en temps réel (c'est un cumul DB) : on le
            # recalcule même en cache hit — coût négligeable.
            data["anthropic"] = _build_anthropic(db).model_dump()
            return CreditsResponse(**data, cache_hit=True)

        # Miss → on refetch en parallèle. Chaque fetcher catch ses erreurs,
        # donc gather ne peut pas échouer globalement.
        meshy, stability, tripo = await asyncio.gather(
            _fetch_meshy(),
            _fetch_stability(),
            _fetch_tripo(),
        )
        anthropic = _build_anthropic(db)

        payload = {
            "meshy": meshy.model_dump(),
            "stability": stability.model_dump(),
            "tripo": tripo.model_dump(),
            "anthropic": anthropic.model_dump(),
        }
        _cache = _CacheEntry(data=payload, expires_at=now + CACHE_TTL_S)
        return CreditsResponse(**payload, cache_hit=False)

"""Router : GET /api/engines (liste des moteurs 3D disponibles).

Utilisé par EngineSelector côté frontend pour peupler le dropdown.
Les autres endpoints (/api/image-engines, /api/templates, /api/settings,
/api/stats) arriveront en Phase 4/5.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from engines import list_engines

router = APIRouter(prefix="/api", tags=["services"])


class EngineInfo(BaseModel):
    name: str
    supports_image: bool


@router.get("/engines", response_model=list[EngineInfo])
def get_engines() -> list[EngineInfo]:
    return [
        EngineInfo(name=e.name, supports_image=e.supports_image_input)
        for e in list_engines()
    ]

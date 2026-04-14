"""Router : services pluggables (moteurs 3D, moteurs image, templates).

Utilisé par les dropdowns du frontend (EngineSelector, ExportPanel,
SettingsPage). Les autres endpoints de services (/api/settings,
/api/stats) arriveront en Phase 5.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from engines import list_engines
from image_engines import list_image_engines
from templates import list_templates

router = APIRouter(prefix="/api", tags=["services"])


class EngineInfo(BaseModel):
    name: str
    supports_image: bool


class ImageEngineInfo(BaseModel):
    name: str


class TemplateInfo(BaseModel):
    name: str
    max_title_length: int
    max_description_length: int
    max_tags: int
    tone: str


@router.get("/engines", response_model=list[EngineInfo])
def get_engines() -> list[EngineInfo]:
    return [
        EngineInfo(name=e.name, supports_image=e.supports_image_input)
        for e in list_engines()
    ]


@router.get("/image-engines", response_model=list[ImageEngineInfo])
def get_image_engines() -> list[ImageEngineInfo]:
    return [ImageEngineInfo(name=e.name) for e in list_image_engines()]


@router.get("/templates", response_model=list[TemplateInfo])
def get_templates() -> list[TemplateInfo]:
    return [
        TemplateInfo(
            name=t.name,
            max_title_length=t.max_title_length,
            max_description_length=t.max_description_length,
            max_tags=t.max_tags,
            tone=t.tone,
        )
        for t in list_templates()
    ]

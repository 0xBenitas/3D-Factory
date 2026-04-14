"""Template marketplace Cults3D.

Règles utilisateur (cf. https://cults3d.com/) :
- Titre ≤ 80 chars (affichage liste/SEO)
- Description : Markdown accepté, 2000 chars raisonnable
- Tags : 15 max recommandé (l'UI permet plus, mais les 15 premiers pèsent)
- Ton : moderne, axé design/usage, pas de jargon technique lourd
"""

from __future__ import annotations

from typing import Any

from templates import register
from templates.base import MarketplaceTemplate


class Cults3DTemplate(MarketplaceTemplate):
    name = "cults3d"
    max_title_length = 80
    max_description_length = 2000
    max_tags = 15
    tone = "moderne, élégant, axé bénéfices utilisateur et design"

    def format_listing(
        self,
        seo_data: dict[str, Any],
        print_params: dict[str, Any],
    ) -> str:
        title = str(seo_data.get("title", "")).strip()
        description = str(seo_data.get("description", "")).strip()
        tags = seo_data.get("tags") or []
        price = seo_data.get("price_eur", seo_data.get("price"))

        lines: list[str] = []
        if title:
            lines.append(f"# {title}")
            lines.append("")
        if description:
            lines.append(description)
            lines.append("")

        # Paramètres impression
        params_lines = _format_print_params(print_params)
        if params_lines:
            lines.append("## Paramètres d'impression recommandés")
            lines.extend(params_lines)
            lines.append("")

        # Tags
        if tags:
            lines.append("## Tags")
            lines.append(", ".join(str(t) for t in tags))
            lines.append("")

        # Prix suggéré
        if price is not None:
            try:
                lines.append(f"## Prix suggéré")
                lines.append(f"{float(price):.2f}€")
            except (TypeError, ValueError):
                pass

        return "\n".join(lines).rstrip() + "\n"


def _format_print_params(p: dict[str, Any]) -> list[str]:
    """Formate les print_params en liste Markdown, en sautant les valeurs manquantes."""
    if not p:
        return []
    out: list[str] = []

    def _row(label: str, value: Any, suffix: str = "") -> None:
        if value in (None, "", "—"):
            return
        out.append(f"- **{label}** : {value}{suffix}")

    _row("Hauteur de couche", p.get("layer_height_mm"), " mm")
    _row("Infill", p.get("infill_percent"), " %")

    supports = p.get("supports_needed")
    if supports is not None:
        note = p.get("support_notes")
        suffix = f" — {note}" if note and note != "—" else ""
        out.append(f"- **Supports** : {'oui' if supports else 'non'}{suffix}")

    _row("Diamètre de buse", p.get("nozzle_diameter_mm"), " mm")
    _row("Matériau recommandé", p.get("material_recommended"))
    _row("Temps d'impression estimé", p.get("estimated_print_time_h"), " h")
    _row("Matière estimée", p.get("estimated_material_g"), " g")
    _row("Orientation conseillée", p.get("orientation_tip"))
    _row("Difficulté", p.get("difficulty"))

    return out


register(Cults3DTemplate())

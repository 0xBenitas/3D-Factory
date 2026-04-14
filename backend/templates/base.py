"""Interface commune des templates marketplace pluggables.

Un template connaît les contraintes de sa marketplace (longueurs max,
nombre de tags, ton) et sait formater un listing final (texte prêt à
copier-coller dans le formulaire de la marketplace).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MarketplaceTemplate(ABC):
    """Interface abstraite d'un template marketplace."""

    #: Nom court, utilisé dans l'UI et la BDD ("cults3d", "printables", ...).
    name: str = ""

    #: Longueur maximale du titre pour cette marketplace.
    max_title_length: int = 100

    #: Longueur maximale de la description.
    max_description_length: int = 2000

    #: Nombre maximum de tags / mots-clés.
    max_tags: int = 20

    #: Ton recommandé pour les descriptions ("moderne, élégant, ...").
    tone: str = "professionnel, orienté bénéfices utilisateur"

    @abstractmethod
    def format_listing(
        self,
        seo_data: dict[str, Any],
        print_params: dict[str, Any],
    ) -> str:
        """Formate le listing complet selon les règles de la marketplace.

        `seo_data` : { title, description, tags, price_eur }
        `print_params` : schéma `print_params` de ARCHITECTURE §Data Models
        Retour : texte prêt à copier-coller (Markdown toléré).
        """
        raise NotImplementedError

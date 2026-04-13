"""Interface commune des moteurs 3D pluggables.

Pour ajouter un moteur : créer un fichier dans `backend/engines/`, hériter
de `Engine3D`, définir les attributs de classe `name` + `supports_image_input`,
et implémenter `generate()` (+ `remesh()` si supporté). Le moteur est
enregistré automatiquement par le registry (cf. `engines/__init__.py`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# Exceptions communes aux moteurs
# --------------------------------------------------------------------------- #

class EngineError(Exception):
    """Base de toutes les erreurs remontées par un moteur 3D."""


class InsufficientCredits(EngineError):
    """402-like : l'API du moteur refuse parce qu'il n'y a plus de crédits."""


class InvalidApiKey(EngineError):
    """401-like : clé d'API manquante ou invalide."""


class RateLimited(EngineError):
    """429 : retry après backoff (géré par `tasks.retry_async`)."""


class EngineTaskFailed(EngineError):
    """La tâche a été acceptée puis a échoué côté serveur du moteur."""


class NotSupported(EngineError):
    """L'action demandée (ex. image-to-3d, remesh) n'est pas supportée."""


# --------------------------------------------------------------------------- #
# Résultat d'une génération
# --------------------------------------------------------------------------- #

@dataclass
class GenerationResult:
    """Retour normalisé de `Engine3D.generate()` et `.remesh()`.

    - `glb_path` : chemin absolu vers le .glb téléchargé en local
    - `engine_task_id` : identifiant de la task côté API (pour remesh
      ultérieur ou debug). Persisté dans la colonne `engine_task_id` du modèle.
    - `cost_credits` : crédits consommés côté API (meshy-5 = 5, etc.).
    - `generation_time_s` : durée totale (enqueue + polling + download).
    """

    glb_path: str
    engine_task_id: str
    cost_credits: int
    generation_time_s: float


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #

class Engine3D(ABC):
    """Interface abstraite d'un moteur 3D.

    Les sous-classes définissent `name` et `supports_image_input` en
    attributs de classe. Elles sont enregistrées automatiquement au moment
    de leur import (cf. `engines/__init__.py`).
    """

    #: Nom court du moteur, utilisé dans l'UI et la BDD ("meshy", "tripo", ...).
    name: str = ""

    #: True si le moteur accepte une image en entrée (image-to-3d).
    supports_image_input: bool = False

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        output_dir: str | None = None,
    ) -> GenerationResult:
        """Génère un modèle 3D à partir d'un prompt (+ image optionnelle).

        - Enqueue la task côté API
        - Poll jusqu'à complétion
        - Télécharge le .glb dans `output_dir` (ou emplacement par défaut)
        - Retourne `GenerationResult`

        Lève une sous-classe de `EngineError` en cas d'échec.
        """
        raise NotImplementedError

    async def remesh(
        self,
        engine_task_id: str,
        target_polycount: int,
        output_dir: str | None = None,
    ) -> GenerationResult:
        """Remesh un modèle existant (ajuste poly count).

        Par défaut : lève `NotSupported`. Les moteurs qui supportent le
        remesh l'implémentent.
        """
        raise NotSupported(f"Engine '{self.name}' does not support remesh")

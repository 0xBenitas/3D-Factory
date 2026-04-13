# 3D Print Factory — SPECS.md (v1.1 — corrigé)

> Ce document complète ARCHITECTURE_v4.md avec toutes les spécifications techniques nécessaires à l'implémentation par Claude Code. Il contient les prompts Claude exacts, les appels API détaillés, les specs composants frontend, la gestion d'erreurs par étape, et un exemple de flow complet.

---

## Table des matières

1. Prompts Claude (system prompts exacts)
2. API externes détaillées (Meshy, Tripo, Stability AI)
3. Service mesh_repair — calcul des métriques
4. Composants frontend — props, layout, interactions
5. Gestion d'erreurs par étape du pipeline
6. Exemple de flow complet (end-to-end)
7. Conventions de code

---

## 1. Prompts Claude

Chaque service qui appelle Claude API utilise un system prompt précis. Le modèle utilisé est `claude-sonnet-4-20250514` pour tous les appels (rapport qualité/coût optimal).

### 1.1 prompt_optimizer.py — System prompt (input texte)

```
SYSTEM:
Tu es un expert en modélisation 3D pour l'impression. Ton rôle est de transformer une description vague en un prompt optimisé pour un générateur 3D IA.

Règles :
- Le prompt doit décrire UNIQUEMENT la géométrie (forme, proportions, détails structurels). JAMAIS de couleurs, textures, matériaux visuels.
- L'objet doit être imprimable en 3D : formes solides, épaisseur minimale 1.5mm partout, pas de parties flottantes, pas de surplombs > 60° si possible.
- Sois précis sur les proportions relatives (ex: "le pied fait 1/4 de la hauteur totale").
- Mentionne la symétrie si applicable.
- Limite : 600 caractères max (limite du moteur).
- Réponds UNIQUEMENT avec le prompt optimisé, rien d'autre.

USER:
Moteur cible : {engine_name}
Description utilisateur : {user_input}
```

### 1.2 prompt_optimizer.py — System prompt (input photo)

```
SYSTEM:
Tu es un expert en modélisation 3D pour l'impression. On te montre une photo d'un objet. Tu dois générer un prompt pour un générateur 3D IA qui reproduira cet objet.

Règles :
- Décris UNIQUEMENT la géométrie : forme globale, proportions, détails structurels, symétrie.
- JAMAIS de couleurs, textures, matériaux visuels — on imprime en monochrome.
- L'objet doit être imprimable : formes solides, épaisseur min 1.5mm, pas de parties flottantes.
- Si l'objet a des détails trop fins pour l'impression, simplifie-les.
- Limite : 600 caractères max.
- Réponds UNIQUEMENT avec le prompt optimisé, rien d'autre.

USER:
Moteur cible : {engine_name}
[IMAGE ATTACHÉE]
```

### 1.3 quality_scorer.py — System prompt

```
SYSTEM:
Tu es un expert en impression 3D FDM/SLA. On te donne les métriques brutes d'un mesh 3D. Tu dois évaluer sa qualité pour l'impression et donner un score sur 10.

Évalue chaque critère sur 10 et donne un score global (moyenne pondérée) :

1. Manifold (poids 2) : is_manifold=true → 10/10, false → 2/10. Un mesh non-manifold a des arêtes partagées par plus de 2 faces.
2. Watertight (poids 2) : is_watertight=true → 10/10, false → 3/10. Nécessaire pour le slicing.
3. Épaisseur des parois (poids 2) : min_wall_thickness_mm >= 1.5mm = 10/10, entre 0.8 et 1.5 = 5/10, < 0.8 = 2/10.
4. Surplombs (poids 1) : max_overhang_angle_deg <= 45° = 10/10, 45-60° = 7/10, > 60° = 4/10 (supports nécessaires).
5. Parties flottantes (poids 2) : connected_components == 1 = 10/10, > 1 = 2/10.
6. Faces dégénérées (poids 1) : 0 = 10/10, < 1% du total = 7/10, > 1% = 3/10.
7. Nombre de faces (poids 0.5) : 5k-50k = 10/10, 50k-100k = 7/10, > 100k = 5/10 (lourd pour les slicers).
8. Proportions (poids 0.5) : bounding_box cohérent avec le type d'objet.

Réponds UNIQUEMENT en JSON, pas de texte autour :
{
  "score": 7.5,
  "criteria": {
    "manifold": { "score": 10, "note": "OK" },
    "watertight": { "score": 10, "note": "OK" },
    "wall_thickness": { "score": 6, "note": "Min 1.2mm, un peu juste" },
    "overhangs": { "score": 8, "note": "Max 52°, supports optionnels" },
    "floating_parts": { "score": 10, "note": "1 seul composant" },
    "degenerate_faces": { "score": 10, "note": "0 faces dégénérées" },
    "face_count": { "score": 10, "note": "12.4k faces, optimal" },
    "proportions": { "score": 9, "note": "Bounding box cohérent" }
  },
  "summary": "Bon modèle, attention à l'épaisseur minimale sur les bords fins. Imprimable sans supports."
}

USER:
Type d'objet demandé : {object_description}
Métriques mesh :
{json.dumps(mesh_metrics, indent=2)}
```

### 1.4 seo_gen.py — System prompt

```
SYSTEM:
Tu es un expert en vente de fichiers STL sur les marketplaces d'impression 3D (Cults3D, Printables, Thangs). Tu génères des listings optimisés pour maximiser les ventes.

Règles :
- Le titre doit être accrocheur ET contenir des mots-clés recherchés (max {max_title_length} caractères).
- La description doit vendre le produit : bénéfices, originalité, cas d'usage. PAS de jargon technique excessif (max {max_description_length} caractères).
- Inclure les dimensions approximatives basées sur le bounding_box.
- {max_tags} tags pertinents, mélange de termes génériques ("3D print", "STL") et spécifiques (type d'objet).
- Prix suggéré en EUR basé sur la complexité (simple = 1-2€, moyen = 2-4€, complexe = 4-8€).
- Ton : {tone}

Réponds UNIQUEMENT en JSON :
{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "price_eur": 2.99
}

USER:
Type d'objet : {object_description}
Métriques mesh : faces={face_count}, volume={volume_cm3}cm³, bounding_box={bounding_box_mm}mm
Marketplace cible : {template_name}
```

### 1.5 seo_gen.py — System prompt paramètres impression

```
SYSTEM:
Tu es un expert en impression 3D FDM. À partir des métriques d'un mesh, tu recommandes les paramètres d'impression optimaux.

Réponds UNIQUEMENT en JSON :
{
  "layer_height_mm": 0.2,
  "infill_percent": 20,
  "supports_needed": false,
  "support_notes": "Aucun surplomb > 55°",
  "nozzle_diameter_mm": 0.4,
  "material_recommended": "PLA",
  "estimated_print_time_h": 4.5,
  "estimated_material_g": 35,
  "orientation_tip": "Imprimer debout, base plate vers le bas",
  "difficulty": "facile"
}

Règles :
- layer_height : 0.2 par défaut, 0.12 si détails fins (faces > 30k), 0.28 si objet simple gros
- infill : 15% pour déco, 20-30% pour fonctionnel, 50%+ pour pièces mécaniques
- supports : basé sur max_overhang_angle_deg (> 55° = supports nécessaires)
- matériau : PLA par défaut, PETG si pièce fonctionnelle, résine si très détaillé (faces > 50k)
- temps estimé : approximation basée sur volume et infill
- difficulty : "facile" (pas de supports, simple), "moyen" (supports ou calibration), "avancé" (multi-matériau ou fragile)

USER:
Type d'objet : {object_description}
Métriques : {json.dumps(mesh_metrics, indent=2)}
```

### 1.6 Prompt contexte lifestyle (utilisé dans tasks.py avant l'appel au moteur image)

```
SYSTEM:
Tu génères un prompt pour une API de génération d'image. Le but : créer une photo lifestyle d'un objet imprimé en 3D, comme une photo produit professionnelle.

Règles :
- L'objet est imprimé en PLA blanc/gris (pas de couleur flashy).
- Le contexte doit correspondre au type d'objet.
- Photo réaliste, éclairage doux naturel, haute qualité.
- Limite : 200 caractères.
- Réponds UNIQUEMENT avec le prompt image, rien d'autre.

Exemples par type :
- Déco/pot : "3D printed white geometric plant pot on wooden shelf, Scandinavian interior, soft natural light, product photography"
- Figurine : "3D printed gray dragon figurine in glass display case, dramatic side lighting, dark background, product photography"
- Technique/support : "3D printed white phone stand on minimalist desk, laptop in background, clean studio lighting, product photography"
- Rangement : "3D printed desk organizer with pens and supplies, modern home office, warm natural light, lifestyle photography"

USER:
Type d'objet : {object_description}
```

---

## 2. API externes détaillées

### ⚠️ Note importante sur les APIs
Les endpoints et payloads documentés ci-dessous sont basés sur la documentation disponible en avril 2026. Les APIs évoluent. Claude Code devra vérifier la doc officielle au moment de l'implémentation et adapter si nécessaire :
- Meshy : https://docs.meshy.ai/en/api
- Tripo : https://platform.tripo3d.ai/docs
- Stability AI : https://platform.stability.ai/docs

### 2.1 Meshy API

**Base URL** : `https://api.meshy.ai/openapi/v2`
**Auth** : Header `Authorization: Bearer {MESHY_API_KEY}`
**Modèle recommandé** : `meshy-5` (5 crédits preview) ou `meshy-6` (20 crédits preview, meilleure qualité)

#### Créer une task Text-to-3D Preview (géométrie only)
```python
# POST https://api.meshy.ai/openapi/v2/text-to-3d
payload = {
    "mode": "preview",
    "prompt": optimized_prompt,        # Max 600 chars
    "ai_model": "meshy-5",             # 5 crédits (vs 20 pour meshy-6)
    "topology": "triangle",
    "target_polycount": 30000,
    "should_remesh": True
    # NB : ne pas inclure art_style, deprecated pour les modèles récents
}
headers = {
    "Authorization": f"Bearer {MESHY_API_KEY}",
    "Content-Type": "application/json"
}
response = await httpx.post(url, json=payload, headers=headers)
# Retourne : {"result": "task_id_here"}
task_id = response.json()["result"]
```

#### Créer une task Image-to-3D (si input = photo)
```python
# POST https://api.meshy.ai/openapi/v2/image-to-3d
payload = {
    "image_url": image_data_uri,       # "data:image/jpeg;base64,..."
    "ai_model": "meshy-5",
    "should_texture": False,           # IMPORTANT : pas de texture = moins cher
    "topology": "triangle",
    "target_polycount": 30000,
    "should_remesh": True
}
```

#### Poll le statut
```python
# GET https://api.meshy.ai/openapi/v2/text-to-3d/{task_id}
# Pour image-to-3d : GET https://api.meshy.ai/openapi/v2/image-to-3d/{task_id}
# Réponse quand terminé :
{
    "id": "task_id",
    "status": "SUCCEEDED",            # ou "PENDING", "IN_PROGRESS", "FAILED"
    "progress": 100,
    "model_urls": {
        "glb": "https://assets.meshy.ai/...",
        "stl": "https://assets.meshy.ai/..."
    },
    "thumbnail_url": "https://assets.meshy.ai/..."
}
```

**Stratégie de polling** :
```python
async def poll_meshy_task(task_id: str, endpoint: str, max_wait: int = 300) -> dict:
    """
    endpoint : "text-to-3d" ou "image-to-3d"
    """
    url = f"https://api.meshy.ai/openapi/v2/{endpoint}/{task_id}"
    start = time.time()
    while time.time() - start < max_wait:
        resp = await httpx.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "SUCCEEDED":
            return data
        if data["status"] == "FAILED":
            raise MeshyError(f"Task failed: {data.get('task_error', {}).get('message', 'Unknown')}")
        await asyncio.sleep(5)  # Poll toutes les 5s
    raise TimeoutError(f"Meshy task {task_id} timed out after {max_wait}s")
```

#### Remesh un modèle existant
```python
# POST https://api.meshy.ai/openapi/v2/remesh
payload = {
    "input_task_id": original_task_id,  # OU model_url pour un .glb uploadé
    "target_polycount": target_polycount,
    "target_formats": ["glb", "stl"]
}
# Poll : GET https://api.meshy.ai/openapi/v2/remesh/{task_id}
```

#### Télécharger le .glb
```python
async def download_model(url: str, output_path: str):
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
```

#### Coûts Meshy
| Action | meshy-5 | meshy-6 |
|---|---|---|
| Text-to-3D Preview (géo only) | 5 crédits | 20 crédits |
| Image-to-3D (should_texture=false) | 5 crédits | 20 crédits |
| Remesh | 5 crédits | 5 crédits |
| Refine (texture) — NON UTILISÉ | 10 crédits | 10 crédits |

Plan Pro : ~$20/mois pour 1000 crédits → 1 crédit ≈ $0.02
Coût preview meshy-5 : 5 × $0.02 = **~$0.10/modèle**

#### Erreurs Meshy courantes
| Code | Signification | Action |
|---|---|---|
| 401 | API key invalide | Vérifier .env |
| 402 | Plus de crédits | Alerte dashboard + stop pipeline |
| 429 | Rate limit | Retry après 30s (backoff exponentiel, max 3 fois) |
| 500 | Erreur serveur Meshy | Retry 2 fois avec backoff, puis fail |
| FAILED status | Génération échouée | Log l'erreur, proposer regénérer |

### 2.2 Tripo API

**⚠️ Deux options d'accès. Choisir au moment de l'implémentation :**

**Option A — API officielle Tripo (recommandé)**
- Base URL : `https://api.tripo3d.ai/v2/openapi`
- Auth : Header `Authorization: Bearer {TRIPO_API_KEY}`
- Doc : https://platform.tripo3d.ai/docs

**Option B — Via 3D AI Studio (wrapper tiers)**
- Base URL : `https://api.3daistudio.com/v1`
- Auth : Header `Authorization: Bearer {TRIPO_API_KEY}`
- Avantage : interface unifiée multi-moteurs
- Risque : intermédiaire supplémentaire

#### Créer une task Text-to-3D (API officielle Tripo)
```python
# POST https://api.tripo3d.ai/v2/openapi/task
payload = {
    "type": "text_to_model",
    "prompt": optimized_prompt
    # Vérifier les paramètres exacts dans la doc Tripo au moment de l'implémentation
    # Tripo supporte texture=false mais le nom du paramètre peut varier
}
headers = {
    "Authorization": f"Bearer {TRIPO_API_KEY}",
    "Content-Type": "application/json"
}
```

#### Poll le statut (API officielle Tripo)
```python
# GET https://api.tripo3d.ai/v2/openapi/task/{task_id}
# Réponse quand terminé :
{
    "code": 0,
    "data": {
        "task_id": "...",
        "status": "success",       # ou "queued", "running", "failed"
        "output": {
            "model": "https://..."  # URL du .glb
        }
    }
}
```

#### Créer une task Text-to-3D (via 3D AI Studio)
```python
# POST https://api.3daistudio.com/v1/3d-models/tripo/text-to-3d/
payload = {
    "prompt": optimized_prompt,
    "texture": False,
    "pbr": False
}
```

#### Poll le statut (via 3D AI Studio)
```python
# GET https://api.3daistudio.com/v1/generation-request/{task_id}/status/
{
    "status": "FINISHED",          # ou "QUEUED", "RUNNING", "FAILED"
    "progress": 100,
    "results": [{ "asset": "https://storage.3daistudio.com/assets/abc123.glb" }]
}
```

**Stratégie de polling** : identique à Meshy (toutes les 5s, timeout 300s).

#### Coûts Tripo
Base : ~20 crédits avec texture, réduit sans texture. Prix exact à vérifier au moment de l'implémentation.

### 2.3 Stability AI — Image Generation

**Base URL** : `https://api.stability.ai/v2beta`
**Auth** : Header `Authorization: Bearer {STABILITY_API_KEY}`
**1 crédit = $0.01**

**⚠️ L'API Stability évolue régulièrement. Les endpoints ci-dessous sont à vérifier dans la doc officielle au moment de l'implémentation : https://platform.stability.ai/docs**

#### Approche recommandée : Text-to-image (plus fiable que img2img pour notre cas)
Le screenshot d'un modèle 3D sans texture donne un résultat bizarre en img2img. Mieux vaut faire du text-to-image pur avec un prompt décrivant l'objet en contexte.

```python
async def generate_lifestyle_photo(context_prompt: str) -> bytes:
    """
    Génère une photo lifestyle via text-to-image.
    Le context_prompt est généré par Claude (voir prompt 1.6).
    """
    data = {
        "prompt": context_prompt,
        "output_format": "png",
        "aspect_ratio": "16:9"
    }
    headers = {
        "Authorization": f"Bearer {STABILITY_API_KEY}",
        "Accept": "image/*"
    }
    resp = await httpx.post(
        "https://api.stability.ai/v2beta/stable-image/generate/core",
        data=data, headers=headers,
        timeout=60
    )
    resp.raise_for_status()
    return resp.content  # Bytes PNG
```

#### Alternative : Image-to-image (si text-to-image donne des résultats trop éloignés)
```python
async def generate_lifestyle_photo_img2img(screenshot_path: str, context_prompt: str) -> bytes:
    with open(screenshot_path, "rb") as f:
        files = {"image": ("screenshot.png", f, "image/png")}
        data = {
            "prompt": context_prompt,
            "strength": 0.65,          # 0.65 = garde la forme, change le contexte
            "output_format": "png"
        }
        headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "image/*"
        }
        # NB : l'endpoint exact pour img2img peut varier, vérifier la doc
        resp = await httpx.post(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            files=files, data=data, headers=headers,
            timeout=60
        )
        resp.raise_for_status()
        return resp.content
```

**Recommandation** : commencer par text-to-image. Tester img2img plus tard si besoin.

#### Coûts Stability AI
| Modèle | Crédits/image | Coût/image |
|---|---|---|
| Stable Image Core | 3 | $0.03 |
| SD 3.5 Large Turbo | 4 | $0.04 |
| SD 3.5 Large | 6.5 | $0.065 |

**Recommandation** : Stable Image Core à $0.03/image.
3 photos par modèle = **$0.09/modèle** pour les photos.

---

## 3. Service mesh_repair — Calcul des métriques

### Note sur les unités
Les .glb exportés par Meshy/Tripo n'ont pas d'unité standardisée. En général les modèles sont normalisés autour de 1 unité = 1 mètre. Le code ci-dessous traite les données brutes telles quelles. Le bounding_box est retourné dans l'unité du fichier source — il faudra potentiellement multiplier par 1000 pour obtenir des mm si le modèle est en mètres.

**Action Claude Code** : lors de la Phase 3, télécharger un .glb test depuis Meshy, inspecter les unités avec `mesh.extents`, et calibrer la conversion une fois pour toutes.

### Code de référence pour mesh_repair.py

```python
import trimesh
import numpy as np
import pymeshfix
import logging

logger = logging.getLogger(__name__)

# Facteur de conversion unités source → mm
# À calibrer lors de la Phase 3 en inspectant un .glb Meshy/Tripo
UNIT_TO_MM = 1000.0  # Si source en mètres → mm. Mettre 1.0 si déjà en mm.


def analyze_and_repair(glb_path: str, stl_output_path: str) -> dict:
    """
    Charge un .glb, analyse les métriques, répare si possible, exporte en .stl.
    Retourne les mesh_metrics et le repair_log.
    """
    # Charger le mesh
    scene = trimesh.load(glb_path)
    if isinstance(scene, trimesh.Scene):
        meshes = scene.dump()
        if len(meshes) == 0:
            raise ValueError("Le fichier .glb ne contient aucune géométrie")
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = scene

    # Tentative de repair
    repair_log = []

    if not mesh.is_watertight:
        try:
            verts = mesh.vertices.copy()
            faces = mesh.faces.copy()
            meshfix = pymeshfix.MeshFix(verts, faces)
            meshfix.repair(verbose=False)
            mesh = trimesh.Trimesh(vertices=meshfix.v, faces=meshfix.f)
            repair_log.append("pymeshfix repair applied")
        except Exception as e:
            repair_log.append(f"pymeshfix failed: {str(e)}")
            logger.warning(f"pymeshfix failed: {e}")

    if not mesh.is_watertight:
        try:
            trimesh.repair.fill_holes(mesh)
            repair_log.append("trimesh fill_holes applied")
        except Exception as e:
            repair_log.append(f"fill_holes failed: {str(e)}")

    # Toujours fixer les normals
    trimesh.repair.fix_normals(mesh)
    repair_log.append("normals fixed")

    # Calculer les métriques APRÈS repair
    metrics = _compute_metrics(mesh)

    # Export STL
    mesh.export(stl_output_path, file_type="stl")

    return {
        "mesh_metrics": metrics,
        "repair_log": "\n".join(repair_log) if repair_log else "No repair needed",
        "stl_path": stl_output_path
    }


def _compute_metrics(mesh: trimesh.Trimesh) -> dict:
    """Calcule toutes les métriques brutes du mesh."""

    min_thickness = _estimate_min_wall_thickness(mesh)
    max_overhang = _compute_max_overhang(mesh)
    components = mesh.split(only_watertight=False)

    # Bounding box converti en mm
    extents_mm = mesh.extents * UNIT_TO_MM

    # Manifold check : trimesh n'a pas de vrai is_manifold séparé.
    # On utilise : is_watertight + vérification edges (chaque arête partagée par exactement 2 faces)
    edges = mesh.edges_sorted
    unique_edges, edge_counts = np.unique(edges, axis=0, return_counts=True)
    non_manifold_edges = np.sum(edge_counts > 2)
    is_manifold = bool(non_manifold_edges == 0)

    return {
        "is_manifold": is_manifold,
        "is_watertight": bool(mesh.is_watertight),
        "non_manifold_edges": int(non_manifold_edges),
        "face_count": int(len(mesh.faces)),
        "vertex_count": int(len(mesh.vertices)),
        "volume_cm3": round(float(abs(mesh.volume)) * (UNIT_TO_MM / 10) ** 3 / 1000, 2) if mesh.is_watertight else None,
        "surface_area_cm2": round(float(mesh.area) * (UNIT_TO_MM / 10) ** 2 / 100, 2),
        "min_wall_thickness_mm": round(min_thickness * UNIT_TO_MM, 2),
        "has_degenerate_faces": bool(mesh.degenerate_faces.sum() > 0),
        "degenerate_face_count": int(mesh.degenerate_faces.sum()),
        "max_overhang_angle_deg": round(max_overhang, 1),
        "has_floating_parts": len(components) > 1,
        "connected_components": len(components),
        "bounding_box_mm": [round(x, 1) for x in extents_mm.tolist()]
    }


def _estimate_min_wall_thickness(mesh: trimesh.Trimesh, n_samples: int = 500) -> float:
    """
    Estime l'épaisseur minimale des parois en lançant des rayons depuis la surface
    vers l'intérieur et en mesurant la distance jusqu'à la face opposée.
    Retourne la valeur dans l'unité du mesh source (pas en mm).
    """
    try:
        points, face_indices = trimesh.sample.sample_surface(mesh, n_samples)
        normals = mesh.face_normals[face_indices]

        # Lancer des rayons vers l'intérieur (direction opposée à la normale)
        offset = 0.001 * np.max(mesh.extents)  # Offset proportionnel à la taille
        ray_origins = points - normals * offset
        ray_directions = -normals

        # intersects_location retourne les positions ET les indices des rayons correspondants
        locations, index_ray, index_tri = mesh.ray.intersects_location(
            ray_origins, ray_directions, multiple_hits=False
        )

        if len(locations) == 0:
            return 0.0

        # Calculer la distance entre chaque point de départ et son intersection
        origin_points = ray_origins[index_ray]
        distances = np.linalg.norm(locations - origin_points, axis=1)

        # Filtrer les distances trop petites (auto-intersection) et aberrantes
        valid = distances > (offset * 2)
        if not np.any(valid):
            return 0.0

        # 5ème percentile = épaisseur minimale typique
        return float(np.percentile(distances[valid], 5))
    except Exception as e:
        logger.warning(f"Wall thickness estimation failed: {e}")
        return 0.0


def _compute_max_overhang(mesh: trimesh.Trimesh) -> float:
    """
    Calcule l'angle de surplomb maximal.
    L'angle de surplomb = angle entre la face et le plan horizontal.
    0° = face horizontale vers le bas (pire surplomb)
    90° = face verticale (pas de surplomb)
    On retourne l'angle de surplomb max en degrés (0-90).

    Convention impression 3D :
    - < 45° de surplomb = OK sans support
    - 45-60° = supports recommandés
    - > 60° = supports nécessaires
    """
    try:
        # Vecteur "vers le haut" — en 3D print, Z est généralement le haut
        up = np.array([0, 0, 1])
        normals = mesh.face_normals

        # Dot product avec le vecteur "vers le haut"
        dots = np.dot(normals, up)

        # Les faces en surplomb sont celles dont la normale pointe vers le bas (dot < 0)
        overhanging = dots < 0
        if not np.any(overhanging):
            return 0.0  # Aucun surplomb

        # Angle entre la normale et le vecteur "bas" pour les faces en surplomb
        # L'angle de surplomb par rapport à l'horizontale = 90° - angle_avec_le_bas
        overhang_dots = -dots[overhanging]  # Inverser pour avoir l'angle avec le bas
        angles_from_vertical = np.degrees(np.arccos(np.clip(overhang_dots, 0, 1)))

        # Angle de surplomb = 90° - angle_from_vertical
        # Plus l'angle est grand (proche de 90°), plus le surplomb est sévère
        overhang_angles = 90 - angles_from_vertical

        return float(np.max(overhang_angles))
    except Exception as e:
        logger.warning(f"Overhang computation failed: {e}")
        return 0.0
```

### Screenshots pour image gen (screenshot.py)

```python
import os
import numpy as np
import trimesh

# IMPORTANT : sur le VPS, cette variable d'environnement DOIT être définie
# avant d'importer pyrender, sinon crash.
# Ajouter dans .env ou dans le script de démarrage :
os.environ["PYOPENGL_PLATFORM"] = "osmesa"

import pyrender
from PIL import Image


def _look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = np.array([0, 0, 1])) -> np.ndarray:
    """
    Crée une matrice 4x4 de pose caméra (look_at).
    eye : position de la caméra
    target : point regardé
    up : vecteur "haut" du monde
    """
    forward = target - eye
    forward = forward / np.linalg.norm(forward)

    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-6:
        # Si forward est parallèle à up, choisir un autre vecteur up
        up = np.array([0, 1, 0])
        right = np.cross(forward, up)
    right = right / np.linalg.norm(right)

    true_up = np.cross(right, forward)
    true_up = true_up / np.linalg.norm(true_up)

    pose = np.eye(4)
    pose[:3, 0] = right
    pose[:3, 1] = true_up
    pose[:3, 2] = -forward  # OpenGL convention : caméra regarde vers -Z
    pose[:3, 3] = eye
    return pose


def generate_screenshots(glb_path: str, output_dir: str, size: int = 512) -> list[str]:
    """Génère 4 screenshots du modèle sous différents angles."""

    scene_trimesh = trimesh.load(glb_path)
    if not isinstance(scene_trimesh, trimesh.Scene):
        scene_trimesh = trimesh.Scene(scene_trimesh)

    # Centrer et calculer l'échelle
    bounds = scene_trimesh.bounds
    center = (bounds[0] + bounds[1]) / 2
    scale = np.max(bounds[1] - bounds[0])
    distance = scale * 2  # Distance caméra proportionnelle à la taille

    # Angles de caméra : face, 3/4, profil, dessus
    camera_angles = [
        ("front",         [0, -distance, center[2]]),
        ("three_quarter", [distance * 0.7, -distance * 0.7, center[2] + scale * 0.3]),
        ("side",          [distance, 0, center[2]]),
        ("top",           [0, -distance * 0.3, center[2] + distance])
    ]

    os.makedirs(output_dir, exist_ok=True)
    paths = []

    for name, eye_pos in camera_angles:
        # Créer scène pyrender
        scene = pyrender.Scene(bg_color=[240, 240, 240, 255])

        # Ajouter les meshes
        for m in scene_trimesh.dump():
            # Appliquer une couleur grise uniforme (pas de texture)
            material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[0.7, 0.7, 0.7, 1.0],
                metallicFactor=0.1,
                roughnessFactor=0.7
            )
            pr_mesh = pyrender.Mesh.from_trimesh(m, material=material)
            scene.add(pr_mesh)

        # Caméra
        camera = pyrender.PerspectiveCamera(yfov=np.pi / 4)
        eye = np.array(eye_pos)
        camera_pose = _look_at(eye, center)
        scene.add(camera, pose=camera_pose)

        # Lumières
        light1 = pyrender.DirectionalLight(color=[255, 255, 255], intensity=3.0)
        scene.add(light1, pose=camera_pose)
        # Lumière d'appoint
        light2 = pyrender.DirectionalLight(color=[200, 200, 255], intensity=1.5)
        light2_pose = _look_at(eye * np.array([-1, 1, 1]), center)
        scene.add(light2, pose=light2_pose)

        # Rendu off-screen (OSMesa sur VPS, pas de GPU)
        renderer = pyrender.OffscreenRenderer(size, size)
        color, _ = renderer.render(scene)
        renderer.delete()

        path = f"{output_dir}/{name}.png"
        Image.fromarray(color).save(path)
        paths.append(path)

    return paths
```

---

## 4. Composants frontend — Specs détaillées

### 4.1 InputForm.jsx

```
Props : { onSubmit: (input_text, input_image, engine, image_engine) => void }

Layout :
┌──────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────┐ │
│  │  Zone texte (placeholder: "Décris l'objet    │ │
│  │  à créer : pot de plante, figurine dragon,   │ │
│  │  support téléphone...")                       │ │
│  │  textarea, 3 lignes, auto-resize             │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  ┌──── OU ─────────────────────────────────────┐  │
│  │  📷 Drop une photo ici (ou cliquer)          │  │
│  │  Accepte : .jpg, .png — max 5MB              │  │
│  │  Preview de la photo si uploadée             │  │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  Moteur 3D: [Meshy ▾]    Moteur image: [Stability ▾] │
│                                                    │
│  [ 🚀 Générer ]                                   │
└──────────────────────────────────────────────────┘

Comportement :
- Le bouton "Générer" est disabled si aucun input (ni texte ni photo)
- Si les deux sont remplis, le texte est prioritaire (la photo est ignorée)
- Au clic : appelle POST /api/pipeline/run, récupère model_id
- Transition vers PipelineTracker avec ce model_id
- Les dropdowns sont pré-remplis avec les défauts de settings
- Validation côté client : photo max 5MB, format jpg/png uniquement
```

### 4.2 PipelineTracker.jsx

```
Props : { modelId: number }

Layout :
┌──────────────────────────────────────────────────┐
│  Pipeline #42                                     │
│                                                    │
│  ✅ Prompt ─── ⏳ Génération 3D ─── ○ Repair     │
│  ─── ○ Score ─── ○ Validation ─── ○ Photos       │
│  ─── ○ Export                                     │
│                                                    │
│  Étape en cours : Génération 3D (45%)             │
│  Temps écoulé : 0:32                              │
│  Prompt utilisé : "Geometric plant pot with       │
│  hexagonal pattern, solid base..."                │
└──────────────────────────────────────────────────┘

Comportement :
- Poll GET /api/pipeline/status/{modelId} toutes les 3 secondes
- Chaque étape : ○ (pas commencé), ⏳ (en cours), ✅ (terminé), ❌ (erreur)
- Si étape = "pending" (validation humaine), afficher lien vers ModelsPage
- Si étape = "done", afficher lien vers le modèle dans ModelsPage
- Si étape = "failed", afficher le message d'erreur + bouton "Regénérer"
- Afficher le prompt optimisé (pour que l'utilisateur comprenne ce qui a été envoyé)
- Stopper le polling quand status = "pending", "done", ou "failed"
```

### 4.3 ModelViewer.jsx

```
Props : { glbUrl: string }

Code de référence :
import { Canvas } from '@react-three/fiber'
import { OrbitControls, useGLTF, Center, Stage } from '@react-three/drei'

function Model({ url }) {
  const { scene } = useGLTF(url)
  return <primitive object={scene} />
}

export default function ModelViewer({ glbUrl }) {
  return (
    <Canvas camera={{ position: [0, 0, 3], fov: 45 }} style={{ height: 400 }}>
      <Stage environment="city" intensity={0.5}>
        <Center>
          <Model url={glbUrl} />
        </Center>
      </Stage>
      <OrbitControls />
    </Canvas>
  )
}

Comportement :
- OrbitControls : rotation souris, zoom molette
- Le modèle est auto-centré et auto-scalé par <Stage> + <Center>
- Éclairage fourni par <Stage>
- Fond gris clair
- Si le .glb ne charge pas : afficher un message "Impossible de charger le modèle"
```

### 4.4 ScoreCard.jsx

```
Props : {
  score: number | null,    // 0-10, null si scoring a échoué
  criteria: object | null,
  meshMetrics: object,
  summary: string | null
}

Layout :
┌──────────────────────────────────────────┐
│  Score : 7.5 / 10    [████████░░]        │
│  (ou "Score indisponible" si null)       │
│                                           │
│  ✅ Manifold          ✅ Watertight       │
│  ⚠️ Épaisseur: 1.2mm  ✅ Surplomb: 52°  │
│  ✅ 1 composant       ✅ 0 faces dégén.  │
│  ✅ 12.4k faces       ✅ 80×80×120mm     │
│                                           │
│  💬 "Bon modèle, attention à l'épaisseur │
│  minimale. Imprimable sans supports."     │
└──────────────────────────────────────────┘

Comportement :
- Score : rouge < 4, orange 4-6, vert > 6
- Chaque métrique : ✅ (OK), ⚠️ (limite), ❌ (problème)
- Seuils :
  - Épaisseur : ✅ >= 1.5mm, ⚠️ 0.8-1.5, ❌ < 0.8
  - Surplomb : ✅ <= 45°, ⚠️ 45-60°, ❌ > 60°
  - Faces : ✅ <= 50k, ⚠️ 50-100k, ❌ > 100k
- Les métriques mesh sont TOUJOURS affichées même si le score Claude est null
```

### 4.5 ModelActions.jsx

```
Props : {
  modelId: number,
  currentPrompt: string,
  onAction: (action, data?) => void
}

Layout :
┌──────────────────────────────────────────┐
│  [ ✅ Approuver ]  [ 🔄 Regénérer ]     │
│  [ 🔧 Remesh ]     [ ❌ Rejeter ]        │
│                                           │
│  (si Regénérer cliqué :)                  │
│  ┌────────────────────────────────────┐   │
│  │ Prompt : [prompt actuel, éditable] │   │
│  │ [ Confirmer regénération ]         │   │
│  └────────────────────────────────────┘   │
│                                           │
│  (si Remesh cliqué :)                     │
│  ┌────────────────────────────────────┐   │
│  │ Target polycount : [ 30000 ]       │   │
│  │ [ Confirmer remesh ]               │   │
│  └────────────────────────────────────┘   │
│                                           │
│  (si Rejeter cliqué :)                    │
│  ┌────────────────────────────────────┐   │
│  │ Raison : [champ texte optionnel]   │   │
│  │ [ Confirmer rejet ]                │   │
│  └────────────────────────────────────┘   │
└──────────────────────────────────────────┘

Comportement :
- Approuver → PUT /api/models/{id}/validate { action: "approve" }
  → déclenche photos + SEO + ZIP en BackgroundTask
- Regénérer → affiche champ prompt éditable → POST /api/models/{id}/regenerate
- Remesh → affiche champ polycount → POST /api/models/{id}/remesh
- Rejeter → champ raison optionnel → PUT /api/models/{id}/validate { action: "reject", reason: "..." }
- Après toute action : refresh la page ou naviguer vers PipelineTracker
```

### 4.6 ExportPanel.jsx

```
Props : {
  modelId: number,
  export: object | null
}

Layout :
┌──────────────────────────────────────────┐
│  Template : [Cults3D ▾]                  │
│                                           │
│  (si export généré :)                     │
│  Titre : "Geometric Hexagonal Plant Pot   │
│  – Modern Minimalist Planter STL"         │
│                                           │
│  Prix suggéré : 2.99€                     │
│                                           │
│  Impression :                             │
│  Couche 0.2mm | Infill 20% | PLA         │
│  Pas de supports | ~4h30 | 35g           │
│                                           │
│  [ 📋 Copier listing ]  [ 📥 ZIP ]       │
│  [ 🔄 Regénérer photos ]                 │
└──────────────────────────────────────────┘

Comportement :
- Si pas d'export : bouton "Générer export" → POST /api/exports/generate
- "Copier listing" → clipboard : titre + \n\n + description + \n\n + tags (comma-separated)
- "ZIP" → window.open(GET /api/exports/{id}/zip)
- "Regénérer photos" → POST /api/exports/{model_id}/photos/regenerate
```

### 4.7 CostTracker.jsx

```
Props : { }  (fetch via GET /api/stats)

Layout (bandeau en bas de CreatePage) :
┌──────────────────────────────────────────┐
│  💰 Aujourd'hui : 0.45€ / 2.00€         │
│  Ce mois : 3.20€ | Modèles : 28         │
│  [████████████░░░░] 62% du budget        │
└──────────────────────────────────────────┘

Comportement :
- Refresh toutes les 30s
- Barre orange > 80%, rouge > 95%
- Si budget dépassé : bandeau rouge fixe "Budget dépassé — le pipeline est bloqué"
```

---

## 5. Gestion d'erreurs par étape

### Étape 1 — PROMPT
| Erreur | Cause | Action |
|---|---|---|
| Claude API timeout | Serveur Anthropic surchargé | Retry 2 fois avec backoff (5s, 15s), puis fail |
| Claude refuse le prompt | Contenu filtré par safety | pipeline_status="failed", message "Prompt refusé, essaie une autre description" |
| Photo trop grande | > 5MB | Reject côté frontend avant envoi |
| Photo format invalide | Pas jpg/png | Reject côté frontend |

### Étape 2 — FORGE
| Erreur | Cause | Action |
|---|---|---|
| 402 Insufficient credits | Plus de crédits Meshy/Tripo | pipeline_status="failed", message clair, alerte CostTracker |
| 429 Rate limit | Trop de requêtes | Retry après 30s, backoff exponentiel, max 3 fois |
| Task FAILED | Meshy/Tripo n'a pas pu générer | Log le failure_reason, fail, proposer regénérer |
| Timeout (> 5 min) | Serveur lent | pipeline_status="failed", message "Timeout génération" |
| .glb corrompu / vide | Téléchargement partiel | Re-télécharger 1 fois, si échec → fail |

### Étape 3 — REPAIR
| Erreur | Cause | Action |
|---|---|---|
| Mesh vide | .glb sans géométrie | pipeline_status="failed", message "Modèle vide" |
| pymeshfix crash | Mesh trop cassé | Log l'erreur, continuer SANS repair, marquer dans repair_log |
| Export STL fail | Mesh non-exportable | Tenter export .obj en fallback, sinon fail |

### Étape 4 — SCORE
| Erreur | Cause | Action |
|---|---|---|
| Claude renvoie pas du JSON | Mauvaise réponse | Retry 1 fois, si échec → score = null, pipeline continue |
| Claude API timeout | Surcharge | Retry 2 fois, si échec → score = null, continue |

**Important : le score est informatif. Si le scoring échoue, le pipeline continue. Le modèle arrive en "pending" sans score. Les métriques mesh brutes sont toujours disponibles.**

### Étape 5 — VALIDATION
Pas d'erreur technique — action humaine.

### Étape 6 — STUDIO (photos)
| Erreur | Cause | Action |
|---|---|---|
| pyrender fail | Dépendance manquante / PYOPENGL_PLATFORM pas set | Log, utiliser thumbnail Meshy/Tripo comme fallback |
| Stability API erreur | 402, 429, 500 | Retry 2 fois, si échec → exporter SANS photos (STL + listing) |
| Stability API pas configurée | Pas de clé API | Skip les photos, exporter STL + listing seulement |

### Étape 7 — PACK
| Erreur | Cause | Action |
|---|---|---|
| Espace disque plein | VPS saturé | Alerte, stop pipeline, message "Espace disque insuffisant" |
| SEO gen fail | Claude API | Retry, si échec → listing vide, l'utilisateur remplit manuellement |

### Règle globale de retry
```python
import asyncio
import logging

logger = logging.getLogger(__name__)

async def retry_async(func, *args, max_retries: int = 2, backoff_base: float = 5.0, **kwargs):
    """Wrapper de retry avec backoff exponentiel."""
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = backoff_base * (2 ** attempt)
            logger.warning(f"{func.__name__} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
```

### Pipeline concurrency
```python
# Dans tasks.py — limiter les tasks simultanées
import asyncio

# Sémaphore global : max 2 pipelines en parallèle
# Évite de spammer les APIs et de dépasser le budget
PIPELINE_SEMAPHORE = asyncio.Semaphore(2)

async def run_pipeline(model_id: int, ...):
    async with PIPELINE_SEMAPHORE:
        # ... exécuter les étapes
```

### Cleanup des fichiers
```python
# Dans un cron ou dans le router models3d.py après un rejet
import shutil

async def cleanup_rejected_model(model_id: int, data_dir: str):
    """Supprime les fichiers d'un modèle rejeté pour libérer l'espace disque."""
    model_dir = f"{data_dir}/models/{model_id}"
    screenshots_dir = f"{data_dir}/screenshots/{model_id}"
    photos_dir = f"{data_dir}/photos/{model_id}"

    for dir_path in [model_dir, screenshots_dir, photos_dir]:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)

# Option : cleanup auto des modèles rejetés de plus de 7 jours via APScheduler
# Option : bouton "Nettoyer" dans SettingsPage
```

---

## 6. Exemple de flow complet (end-to-end)

### Input utilisateur
```
Texte : "pot de plante géométrique style nordique"
Moteur 3D : meshy (meshy-5)
Moteur image : stability (Stable Image Core)
```

### Étape 1 — PROMPT (~5s, ~$0.003)
```
→ POST /api/pipeline/run { input_text: "pot de plante géométrique style nordique", engine: "meshy", image_engine: "stability" }
← { model_id: 42 }

→ prompt_optimizer.py envoie à Claude sonnet :
  "Moteur cible : meshy
   Description utilisateur : pot de plante géométrique style nordique"

← Claude répond :
  "Cylindrical plant pot with hexagonal faceted exterior surface, 6 distinct flat faces forming geometric pattern. Solid flat base with drainage hole, 3mm wall thickness throughout. Height equals 1.2x diameter. Smooth interior, sharp exterior edges between facets. Single piece, no separate parts."

→ Stocké dans models.optimized_prompt
→ pipeline_status = "generating"
```

### Étape 2 — FORGE (~60-90s, ~$0.10)
```
→ POST https://api.meshy.ai/openapi/v2/text-to-3d
  { mode: "preview", prompt: "Cylindrical plant pot...", ai_model: "meshy-5", topology: "triangle", target_polycount: 30000, should_remesh: true }
← { result: "mtask_abc123" }

→ Poll toutes les 5s pendant ~90s
← status: "SUCCEEDED"
   model_urls.glb: "https://assets.meshy.ai/xyz.glb"

→ Télécharge le .glb → data/models/42/model.glb
→ engine_task_id = "mtask_abc123"
→ cost_credits = 5
→ pipeline_status = "repairing"
```

### Étape 3 — REPAIR (~5s, $0)
```
→ mesh_repair.py charge data/models/42/model.glb
→ Analyse :
  {
    "is_manifold": true,
    "is_watertight": true,
    "non_manifold_edges": 0,
    "face_count": 12400,
    "vertex_count": 6200,
    "volume_cm3": 245.3,
    "surface_area_cm2": 380.5,
    "min_wall_thickness_mm": 2.8,
    "has_degenerate_faces": false,
    "degenerate_face_count": 0,
    "max_overhang_angle_deg": 12,
    "has_floating_parts": false,
    "connected_components": 1,
    "bounding_box_mm": [82.0, 82.0, 98.0]
  }
→ Pas de repair nécessaire
→ Export → data/models/42/model.stl
→ pipeline_status = "scoring"
```

### Étape 4 — SCORE (~5s, ~$0.005)
```
→ quality_scorer.py envoie les métriques brutes à Claude sonnet
← Claude répond :
  {
    "score": 9.2,
    "criteria": {
      "manifold": { "score": 10, "note": "OK" },
      "watertight": { "score": 10, "note": "OK" },
      "wall_thickness": { "score": 10, "note": "2.8mm, excellent" },
      "overhangs": { "score": 10, "note": "Max 12°, aucun support" },
      "floating_parts": { "score": 10, "note": "1 composant" },
      "degenerate_faces": { "score": 10, "note": "0" },
      "face_count": { "score": 10, "note": "12.4k, optimal" },
      "proportions": { "score": 8, "note": "82×82×98mm, pot de taille moyenne" }
    },
    "summary": "Excellent modèle, parfaitement imprimable. Géométrie propre, pas de supports nécessaires."
  }
→ pipeline_status = "pending"
→ validation = "pending"
```

### Étape 5 — VALIDATION (humaine)
```
L'utilisateur ouvre ModelsPage, voit le modèle #42 en haut (score 9.2).
Il ouvre le viewer Three.js, tourne le modèle, vérifie que la forme correspond.
Il clique ✅ Approuver.

→ PUT /api/models/42/validate { action: "approve" }
→ validation = "approved"
→ pipeline_status = "photos"
→ BackgroundTask déclenché (limité par PIPELINE_SEMAPHORE)
```

### Étape 6 — STUDIO (~20s, ~$0.09)
```
→ screenshot.py génère 4 PNGs du .glb → data/screenshots/42/

→ Claude génère le prompt lifestyle :
  "3D printed white geometric plant pot with succulent, on wooden shelf,
   Scandinavian interior, soft natural light, product photography"

→ Stability AI text-to-image × 3 photos (Stable Image Core, $0.03 chacune)
← 3 photos lifestyle → data/photos/42/
→ pipeline_status = "packing"
```

### Étape 7 — PACK (~5s, ~$0.005)
```
→ seo_gen.py envoie à Claude :
  Objet : "pot de plante géométrique style nordique"
  Métriques : faces=12.4k, volume=245cm³, bbox=82×82×98mm
  Template : cults3d

← Claude :
  {
    "title": "Geometric Hexagonal Plant Pot – Modern Minimalist Planter STL File",
    "description": "Bring a touch of Scandinavian design to your space...",
    "tags": ["plant pot", "geometric", "planter", "minimalist", "nordic", "3D print", "STL", "home decor", "succulent pot", "hexagonal", "modern", "desk planter", "indoor garden", "gift idea", "printable"],
    "price_eur": 2.49
  }

→ Paramètres impression :
  {
    "layer_height_mm": 0.2,
    "infill_percent": 15,
    "supports_needed": false,
    "support_notes": "Aucun surplomb, impression directe",
    "nozzle_diameter_mm": 0.4,
    "material_recommended": "PLA",
    "estimated_print_time_h": 3.5,
    "estimated_material_g": 42,
    "orientation_tip": "Imprimer debout, base vers le plateau",
    "difficulty": "facile"
  }

→ packager.py assemble :
  42_geometric_plant_pot.zip/
    ├── model.stl
    ├── photo_1.png
    ├── photo_2.png
    ├── photo_3.png
    └── listing.txt

→ pipeline_status = "done"
```

### Coût total de ce modèle
| Étape | Coût |
|---|---|
| Prompt (Claude sonnet) | ~$0.003 |
| Meshy preview meshy-5 (5 crédits) | ~$0.10 |
| Score (Claude sonnet) | ~$0.005 |
| Photos (3× Stability Core) | ~$0.09 |
| SEO + print params (Claude) | ~$0.005 |
| **Total** | **~$0.20** |

Prix de vente : 2.49€ → **marge ~90%**
Coût fixe VPS : 4,35€/mois → break-even : 2-3 ventes/mois

---

## 7. Conventions de code

### Python (backend)
- Python 3.11+
- Async/await pour tous les appels réseau (httpx.AsyncClient)
- Type hints partout
- Un fichier = un service = une responsabilité
- Logging avec `logging` standard (pas de print)
- Toutes les configs via `config.py` qui lit `.env`
- Tests : un fichier `test_{service}.py` par service dans `backend/tests/`

### React (frontend)
- Functional components + hooks uniquement
- Pas de state management global (useState/useEffect suffisent)
- Fetch API pour les appels (pas d'axios)
- CSS : Tailwind classes si dispo, sinon CSS modules
- Pas de TypeScript (overkill pour un outil perso)

### Nommage
- Backend : snake_case partout
- Frontend : camelCase pour les variables, PascalCase pour les composants
- API routes : kebab-case (`/api/image-engines`)
- Fichiers : snake_case backend, PascalCase frontend

### Git
```
.gitignore:
backend/data/
.env
node_modules/
frontend/dist/
__pycache__/
*.pyc
```

Commit messages : `[phase-N] description courte`
Exemple : `[phase-2] add meshy engine with polling`

### Variables d'environnement VPS (à ajouter dans le service ou .bashrc)
```bash
export PYOPENGL_PLATFORM=osmesa  # Obligatoire pour pyrender sans GPU
```

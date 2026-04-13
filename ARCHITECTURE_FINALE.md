# 3D Print Factory v4 — Architecture Finale

## Vision
Machine de production de fichiers STL imprimables. L'utilisateur entre un texte ou une photo, le pipeline fait tout le reste : génération 3D, repair, scoring, photos lifestyle, SEO, paramètres d'impression, ZIP prêt à upload sur marketplace.

Tout tourne sur un VPS. L'utilisateur accède au dashboard depuis un navigateur desktop.

---

## Évolution du projet

| Version | Changement clé |
|---|---|
| v1 | Archi locale, Blender headless, pipeline basique |
| v2 | BlenderMCP semi-auto, presets par niche |
| v3 | Full VPS cloud, Blender headless sur serveur |
| v3.1 | Blender supprimé, Three.js viewer, IA quality scoring, photos IA |
| **v4** | **Flow simplifié (input direct, pas de scraping), services pluggables (3D, image, marketplace), paramètres impression, module INTEL en bonus** |

---

## Flow principal

```
INPUT              PROMPT             FORGE              REPAIR + SCORE
Texte ou photo  →  Claude optimise →  API 3D au choix →  trimesh : manifold,
"pot de plante     le prompt pour      (Meshy/Tripo/      watertight, épaisseur,
 géométrique"      le moteur choisi    autre)             volume, faces
                                       mode géo only      + Claude note /10
                                       → .glb             sur données brutes
                                                          → .stl

VALIDATION          STUDIO             SEO + PRINT         PACK
Viewer Three.js  →  API image IA    →  Claude génère    →  ZIP
trier par score     au choix           titre, desc,        .stl
valider/regénérer   (Stability/        tags, prix,         + photos
/remesh             autre)             + paramètres        + listing.txt
                    screenshot →       impression :        template marketplace
                    photo lifestyle    couche, infill,     au choix
                                       supports, buse      → download
```

---

## Décisions techniques

| Choix | Décision |
|---|---|
| Runtime | VPS Hetzner CX22 (2 vCPU, 4 Go, 4,35€/mois) |
| Frontend | React (Vite), servi en static par FastAPI, desktop only |
| Backend | Python FastAPI + BackgroundTasks |
| Storage | SQLite + backup cron quotidien |
| Moteurs 3D | Pluggables : Meshy, Tripo (+ autres ajoutables) |
| Moteurs image | Pluggables : Stability AI (+ autres ajoutables) |
| Mesh repair | trimesh + pymeshfix |
| Scoring | Claude API sur données brutes mesh (pas de vision, pas de rejet auto) |
| Viewer | Three.js dans le dashboard |
| Templates marketplace | Un fichier par plateforme (Cults3D, Printables, etc.) |
| Auth | Basic Auth + HTTPS obligatoire (Caddy) |

---

## Architecture services pluggables

Chaque moteur (3D ou image) et chaque template marketplace est un fichier Python indépendant avec la même interface. Pour ajouter un nouveau service : créer un fichier, l'enregistrer, il apparaît dans le dropdown.

### Moteurs 3D (backend/engines/)
```python
# Interface commune — backend/engines/base.py
class Engine3D:
    name: str
    supports_image_input: bool

    async def generate(self, prompt: str, image_path: str | None) -> GenerationResult:
        """Envoie le prompt, poll le résultat, télécharge le .glb"""
        ...

    async def remesh(self, task_id: str, target_polycount: int) -> GenerationResult:
        """Remesh un modèle existant (si supporté)"""
        ...

class GenerationResult:
    glb_path: str
    engine_task_id: str
    cost_credits: int
    generation_time_s: float
```

### Moteurs image (backend/image_engines/)
```python
# Interface commune — backend/image_engines/base.py
class ImageEngine:
    name: str

    async def generate(self, context_prompt: str, screenshot_path: str | None = None) -> list[str]:
        """Prompt contexte (+ screenshot optionnel) → chemins des photos générées"""
        ...
```

### Templates marketplace (backend/templates/)
```python
# Interface commune — backend/templates/base.py
class MarketplaceTemplate:
    name: str
    max_title_length: int
    max_description_length: int
    max_tags: int
    tone: str

    def format_listing(self, seo_data: dict, print_params: dict) -> str:
        """Formate le listing complet selon les règles de la marketplace"""
        ...
```

### Ajout d'un nouveau service
```bash
# Exemple : ajouter un moteur 3D "trellis"
# 1. Créer backend/engines/trellis.py (implémente Engine3D)
# 2. L'ajouter dans backend/engines/__init__.py
# 3. Il apparaît dans le dropdown du dashboard
# Rien d'autre à changer.
```

---

## Structure du projet

```
3d-factory/
├── README.md
├── ARCHITECTURE.md
├── .env.example
├── .gitignore
│
├── backend/
│   ├── main.py              ← FastAPI + serve frontend static
│   ├── config.py            ← Settings depuis .env
│   ├── auth.py              ← Basic Auth middleware
│   ├── database.py          ← SQLite init + session
│   ├── models.py            ← SQLAlchemy models
│   ├── tasks.py             ← BackgroundTasks : pipeline async
│   │
│   ├── routers/
│   │   ├── pipeline.py      ← POST /api/pipeline/run, GET /api/pipeline/status/{id}
│   │   ├── models3d.py      ← GET /api/models, PUT /api/models/{id}/validate, etc.
│   │   ├── exports.py       ← POST /api/exports/generate, GET /api/exports/{id}/zip
│   │   ├── services.py      ← GET /api/engines, GET /api/image-engines, GET /api/templates, GET/PUT /api/settings
│   │   └── stats.py         ← GET /api/stats
│   │
│   ├── services/
│   │   ├── prompt_optimizer.py  ← Claude API : texte/photo → prompt 3D optimisé
│   │   ├── mesh_repair.py       ← trimesh + pymeshfix → .stl + métriques brutes
│   │   ├── quality_scorer.py    ← Claude API : données brutes mesh → score /10
│   │   ├── screenshot.py        ← pyrender : .glb → 4 PNG (pour image gen)
│   │   ├── seo_gen.py           ← Claude API : listing + paramètres impression
│   │   └── packager.py          ← Assemble ZIP
│   │
│   ├── engines/                 ← Moteurs 3D pluggables
│   │   ├── __init__.py          ← Registry des moteurs dispos
│   │   ├── base.py              ← Interface Engine3D + GenerationResult
│   │   ├── meshy.py             ← Meshy API (mode preview, géo only, 5 crédits)
│   │   └── tripo.py             ← Tripo API
│   │
│   ├── image_engines/           ← Moteurs image pluggables
│   │   ├── __init__.py          ← Registry
│   │   ├── base.py              ← Interface ImageEngine
│   │   └── stability.py         ← Stability AI (text-to-image recommandé)
│   │
│   ├── templates/               ← Templates marketplace pluggables
│   │   ├── __init__.py          ← Registry
│   │   ├── base.py              ← Interface MarketplaceTemplate
│   │   └── cults3d.py           ← Règles + format Cults3D
│   │
│   └── data/                    ← Fichiers générés (gitignored)
│       ├── db.sqlite
│       ├── backups/             ← Backups SQLite (7 jours glissants)
│       ├── models/              ← .glb + .stl par modèle
│       ├── screenshots/         ← PNGs pour image gen
│       ├── photos/              ← Photos lifestyle
│       └── exports/             ← ZIPs finaux
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── CreatePage.jsx      ← Input + sélection services + pipeline tracker
│   │   │   ├── ModelsPage.jsx      ← Grille modèles + viewer + validation + export
│   │   │   └── SettingsPage.jsx    ← Services dispos, budget, templates par défaut
│   │   └── components/
│   │       ├── InputForm.jsx       ← Zone texte + drop photo + bouton Go
│   │       ├── EngineSelector.jsx  ← Dropdowns moteur 3D + moteur image
│   │       ├── PipelineTracker.jsx ← Barre progression 7 étapes en temps réel
│   │       ├── ModelViewer.jsx     ← Three.js viewer .glb (rotate, zoom)
│   │       ├── ModelActions.jsx    ← Boutons : approuver, regénérer, remesh, rejeter
│   │       ├── ScoreCard.jsx       ← Score /10 + métriques mesh brutes
│   │       ├── PrintParams.jsx     ← Paramètres impression recommandés
│   │       ├── ModelCard.jsx       ← Thumbnail + score + status dans la grille
│   │       ├── ExportPanel.jsx     ← Choix template marketplace + download ZIP + copier listing
│   │       └── CostTracker.jsx     ← Budget API temps réel + alerte dépassement
│   └── package.json
│
└── scripts/
    ├── setup_vps.sh
    ├── deploy.sh
    └── backup.sh
```

---

## Data Models (SQLite)

### models
| Colonne | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto |
| input_type | TEXT | "text" ou "image" |
| input_text | TEXT | Texte saisi par l'utilisateur |
| input_image_path | TEXT | Chemin photo uploadée (si image) |
| optimized_prompt | TEXT | Prompt optimisé par Claude |
| engine | TEXT | "meshy", "tripo", etc. |
| engine_task_id | TEXT | ID task côté API (pour remesh/regénérer) |
| glb_path | TEXT | Chemin .glb |
| stl_path | TEXT | Chemin .stl (post-repair) |
| mesh_metrics | JSON | Données brutes mesh (voir détail ci-dessous) |
| repair_log | TEXT | Log du repair |
| qc_score | REAL | Score printabilité /10 (informatif, pas de rejet auto) |
| qc_details | JSON | Détails par critère |
| validation | TEXT | "pending", "approved", "rejected" |
| rejection_reason | TEXT | Optionnel, stocké pour apprentissage |
| screenshot_paths | JSON | PNGs pour image gen |
| photo_paths | JSON | Photos lifestyle |
| image_engine | TEXT | "stability", etc. |
| cost_credits | INTEGER | Crédits API 3D consommés |
| cost_eur_estimate | REAL | Coût estimé total EUR |
| pipeline_status | TEXT | "prompt", "generating", "repairing", "scoring", "pending", "photos", "packing", "done", "failed" |
| pipeline_error | TEXT | Message d'erreur si failed |
| created_at | DATETIME | Timestamp |

#### mesh_metrics (JSON) — données envoyées à Claude pour le scoring
```json
{
  "is_manifold": true,
  "is_watertight": true,
  "non_manifold_edges": 0,
  "face_count": 12400,
  "vertex_count": 6200,
  "volume_cm3": 45.2,
  "surface_area_cm2": 180.5,
  "min_wall_thickness_mm": 1.8,
  "has_degenerate_faces": false,
  "degenerate_face_count": 0,
  "max_overhang_angle_deg": 52,
  "has_floating_parts": false,
  "connected_components": 1,
  "bounding_box_mm": [80.0, 80.0, 120.0]
}
```

### exports
| Colonne | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto |
| model_id | INTEGER FK | Lien vers le modèle |
| template | TEXT | "cults3d", "printables", etc. |
| title | TEXT | Titre SEO |
| description | TEXT | Description SEO |
| tags | JSON | Tags marketplace |
| price_suggested | REAL | Prix suggéré (EUR) |
| print_params | JSON | Paramètres impression (voir détail ci-dessous) |
| zip_path | TEXT | Chemin ZIP |
| created_at | DATETIME | Timestamp |

#### print_params (JSON) — généré par Claude à partir de mesh_metrics
```json
{
  "layer_height_mm": 0.2,
  "infill_percent": 20,
  "supports_needed": false,
  "support_notes": "Aucun surplomb > 55°, pas de supports nécessaires",
  "nozzle_diameter_mm": 0.4,
  "material_recommended": "PLA",
  "estimated_print_time_h": 4.5,
  "estimated_material_g": 35,
  "orientation_tip": "Imprimer debout, base plate vers le bas",
  "difficulty": "facile"
}
```

### settings
| Colonne | Type | Description |
|---|---|---|
| key | TEXT PK | Nom du setting |
| value | TEXT | Valeur (JSON si complexe) |

Settings par défaut : `default_engine` = "meshy", `default_image_engine` = "stability", `default_template` = "cults3d", `max_daily_budget_eur` = "2.00"

---

## API Endpoints

### Pipeline
- `POST /api/pipeline/run` → lance le pipeline complet en BackgroundTask
  - Body : `{ "input_text": "...", "input_image": base64 | null, "engine": "meshy", "image_engine": "stability" }`
  - Retourne : `{ "model_id": 42 }`
- `GET /api/pipeline/status/{model_id}` → statut + étape + progression

### Models
- `GET /api/models?sort=score_desc&validation=pending` → liste avec filtres et tri
- `GET /api/models/{id}` → détail complet
- `GET /api/models/{id}/glb` → fichier .glb pour Three.js viewer
- `PUT /api/models/{id}/validate` → `{ "action": "approve" | "reject", "reason": "..." }`
- `POST /api/models/{id}/regenerate` → `{ "prompt_override": "..." | null }`
- `POST /api/models/{id}/remesh` → `{ "target_polycount": 30000 }`

### Exports
- `POST /api/exports/generate` → `{ "model_id": 42, "template": "cults3d" }`
  - Génère photos lifestyle + SEO + print params + ZIP en BackgroundTask
- `GET /api/exports/{id}/zip` → télécharger
- `GET /api/exports/{id}/listing` → texte brut (copier-coller)
- `POST /api/exports/{model_id}/photos/regenerate` → relancer les photos

### Services
- `GET /api/engines` → `[{ "name": "meshy", "supports_image": true }, ...]`
- `GET /api/image-engines` → `[{ "name": "stability" }, ...]`
- `GET /api/templates` → `[{ "name": "cults3d", "max_tags": 20 }, ...]`

### Stats
- `GET /api/stats` → coûts jour/mois, nb modèles, taux approbation, score moyen

### Settings
- `GET /api/settings`
- `PUT /api/settings` → `{ "default_engine": "tripo" }`

---

## Pipeline détaillé (7 étapes)

### 1. PROMPT — Optimisation (auto, ~5s, ~$0.003)
- Input : texte libre ou photo
- prompt_optimizer.py envoie à Claude API
- Si texte : Claude reformule en prompt 3D optimisé pour le moteur choisi
  - Orienté imprimabilité : formes solides, épaisseur min 1.5mm, pas de surplombs extrêmes, pas de parties flottantes
- Si photo : Claude Vision analyse l'image et génère un prompt 3D descriptif
- Le prompt optimisé est stocké dans le modèle (visible dans le dashboard pour édition avant regénération)

### 2. FORGE — Génération 3D (auto, 30s-2min, ~$0.10)
- Envoie le prompt optimisé au moteur choisi (Meshy/Tripo)
- Mode preview / géométrie uniquement (pas de texture)
- Meshy : 5 crédits (au lieu de 20 avec texture)
- Poll le résultat, télécharge le .glb
- Stocke dans data/models/

### 3. REPAIR — Mesh check + fix (auto, ~5s, $0)
- mesh_repair.py charge le .glb avec trimesh
- Calcule toutes les métriques brutes (mesh_metrics JSON)
- Vérifie manifold, watertight, faces dégénérées, composants connectés
- Répare auto si possible (pymeshfix)
- Exporte en .stl
- Si le mesh est totalement irrécupérable → pipeline_status = "failed" avec message explicite

### 4. SCORE — Notation printabilité (auto, ~5s, ~$0.005)
- quality_scorer.py envoie les mesh_metrics brutes à Claude API (texte, pas vision)
- Claude évalue sur 10 critères et donne un score /10 :
  - Manifold + watertight
  - Épaisseur minimale des parois (>1.5mm = bien)
  - Angle de surplomb max (<55° = pas de supports)
  - Pas de parties flottantes
  - Volume et proportions cohérents
  - Nombre de faces raisonnable pour la taille
- Le score est informatif, PAS de rejet automatique
- Sert à trier dans le dashboard : les meilleurs en haut

### 5. VALIDATION — Humaine (dans le dashboard)
- Le modèle passe en "pending" dans la ModelsPage
- L'utilisateur voit :
  - Viewer Three.js interactif (rotation, zoom)
  - ScoreCard : score /10 + toutes les métriques mesh
  - PrintParams preview : ce que Claude recommande comme paramètres impression
  - Le prompt optimisé utilisé
- Actions disponibles :
  - ✅ **Approuver** → continue vers photos + export
  - 🔄 **Regénérer** → relance étape 2 (même prompt ou modifié)
  - 🔧 **Remesh** → envoie à l'API remesh du moteur (ajuste poly count)
  - ❌ **Rejeter** → archivé avec raison

### 6. STUDIO — Photos lifestyle (auto, ~20s, ~$0.09)
- Déclenché après approbation (limité par sémaphore : max 2 pipelines simultanés)
- screenshot.py génère 4 screenshots du .glb via pyrender (OSMesa, pas de GPU)
  - ⚠️ Variable d'environnement `PYOPENGL_PLATFORM=osmesa` obligatoire sur le VPS
- Claude génère un prompt lifestyle adapté au type d'objet
- API image (text-to-image recommandé, plus fiable que img2img sur modèle sans texture)
- Génère 3 photos lifestyle (Stable Image Core, ~$0.03/photo)
- Stocke dans data/photos/

### 7. PACK — Export (auto, ~5s, ~$0.005)
- seo_gen.py génère via Claude :
  - Titre accrocheur optimisé SEO marketplace
  - Description avec bénéfices + dimensions + originalité
  - Tags (15-20 pertinents)
  - Prix suggéré (basé sur type d'objet + complexité)
  - Paramètres d'impression recommandés (print_params JSON) basés sur mesh_metrics
- packager.py assemble le ZIP selon le template marketplace choisi :
  - `model.stl`
  - `photo_1.png` à `photo_3.png`
  - `listing.txt` (titre + description + tags + prix + paramètres impression)
- ZIP téléchargeable + listing copiable en un clic

---

## Coûts par modèle

| Étape | Coût |
|---|---|
| Prompt (Claude API) | ~$0.003 |
| Génération 3D preview (Meshy 5 crédits) | ~$0.10 |
| Scoring (Claude API) | ~$0.005 |
| Photos lifestyle (3× Stability Core) | ~$0.09 |
| SEO + print params (Claude API) | ~$0.005 |
| **Total par modèle** | **~$0.20** |

Coût fixe VPS : 4,35€/mois
Break-even : 2-3 ventes/mois à 3€

---

## Frontend — 3 pages

### CreatePage — "la télécommande"
- **InputForm** : zone texte (placeholder: "pot de plante géométrique, figurine dragon, support téléphone...") + zone drop photo + bouton "Go"
- **EngineSelector** : dropdown moteur 3D + dropdown moteur image (pré-remplis avec les défauts de Settings)
- **PipelineTracker** : une fois "Go" cliqué, affiche la progression en 7 étapes en temps réel (polling /pipeline/status)
- **CostTracker** : budget du jour en bas de page

### ModelsPage — "l'atelier"
- **Grille** de tous les modèles, triable par score, date, status
- **Filtres** : pending / approved / rejected / all
- **Au clic sur un modèle** :
  - **ModelViewer** : Three.js, rotation + zoom
  - **ScoreCard** : score /10, manifold ✅, watertight ✅, épaisseur 1.8mm ✅, surplomb 52° ✅, faces 12.4k
  - **PrintParams** : couche 0.2mm, infill 20%, supports non, PLA, ~4h30
  - **ModelActions** : approuver, regénérer (avec champ prompt modifiable), remesh, rejeter
  - **ExportPanel** (si approuvé) : dropdown template marketplace, bouton "Générer export", download ZIP, copier listing

### SettingsPage — "la config"
- Moteur 3D par défaut (dropdown)
- Moteur image par défaut (dropdown)
- Template marketplace par défaut (dropdown)
- Budget max quotidien (EUR)
- Status des clés API (Meshy ✅ connecté, Tripo ❌ pas configuré, etc.)

---

## Config (.env)

```env
# Auth (obligatoire)
APP_USER=admin
APP_PASS=motdepasse-solide

# APIs
ANTHROPIC_API_KEY=sk-ant-...
MESHY_API_KEY=...
TRIPO_API_KEY=...                    # Optionnel si pas utilisé
STABILITY_API_KEY=...

# Défaults (modifiables aussi via SettingsPage)
DEFAULT_ENGINE=meshy
DEFAULT_IMAGE_ENGINE=stability
DEFAULT_TEMPLATE=cults3d
MAX_DAILY_BUDGET_EUR=2.00

# Server
HOST=0.0.0.0
PORT=8000
DATA_DIR=./data
```

---

## Dépendances

### Backend (requirements.txt)
```
fastapi
uvicorn[standard]
sqlalchemy
httpx
anthropic
trimesh
pymeshfix
pyrender
Pillow
numpy
python-multipart
apscheduler
```

### Frontend (package.json)
```
react
react-dom
react-router-dom
three
@react-three/fiber
@react-three/drei
vite
@vitejs/plugin-react
```

---

## Infra VPS

### Serveur
- Hetzner CX22 : 2 vCPU, 4 Go RAM, 40 Go SSD — 4,35€/mois
- OS : Ubuntu 24.04
- Pas de Blender, pas de GPU nécessaire

### scripts/setup_vps.sh
```bash
#!/bin/bash
set -e

apt update && apt upgrade -y
apt install -y python3-pip python3-venv python3-dev nodejs npm git curl

# Caddy — reverse proxy HTTPS auto (obligatoire pour auth sécurisée)
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy

# Deps pyrender (rendu screenshots sans GPU)
apt install -y libosmesa6-dev freeglut3-dev

# Variable d'environnement obligatoire pour pyrender headless
echo 'export PYOPENGL_PLATFORM=osmesa' >> /root/.bashrc

# Caddy config — changer le domaine
cat > /etc/caddy/Caddyfile << 'EOF'
factory.mondomaine.com {
    reverse_proxy localhost:8000
}
EOF
systemctl restart caddy

# Backup cron
echo "0 3 * * * /root/3d-factory/scripts/backup.sh" | crontab -

echo "✅ VPS prêt"
```

### scripts/deploy.sh
```bash
#!/bin/bash
set -e
cd /root/3d-factory

git pull origin main

cd frontend && npm install && npm run build && cd ..

cd backend
source venv/bin/activate 2>/dev/null || (python3 -m venv venv && source venv/bin/activate)
pip install -r requirements.txt

pkill -f "uvicorn main:app" || true
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/3d-factory.log 2>&1 &

echo "✅ Deployed → https://factory.mondomaine.com"
```

### scripts/backup.sh
```bash
#!/bin/bash
BACKUP_DIR="/root/3d-factory/backend/data/backups"
DB_PATH="/root/3d-factory/backend/data/db.sqlite"
mkdir -p "$BACKUP_DIR"
cp "$DB_PATH" "$BACKUP_DIR/db_$(date +%Y%m%d_%H%M%S).sqlite"
find "$BACKUP_DIR" -name "*.sqlite" -mtime +7 -delete
```

---

## Garde-fous

### Budget
- MAX_DAILY_BUDGET_EUR configurable (.env + SettingsPage)
- Pipeline refuse de lancer si budget du jour dépassé
- CostTracker dans le dashboard : dépense temps réel + alerte visuelle

### Scraping protection
- Rate limiting sur les appels API externes
- Retry avec backoff exponentiel
- Timeout configurable

### Données
- Backup SQLite auto à 3h, 7 jours de rétention
- .env jamais commité
- VPS : ports 443 (HTTPS) + 22 (SSH) uniquement

---

## Ordre d'implémentation (pour Claude Code)

### Phase 1 — Fondations
1. Init repo, structure dossiers, .env.example, .gitignore
2. FastAPI app + auth middleware + health check
3. SQLite init + models SQLAlchemy (3 tables)
4. backup.sh + cron
5. Frontend : squelette React + routing 3 pages + build static servi par FastAPI
6. setup_vps.sh + deploy.sh

### Phase 2 — Pipeline core
7. engines/base.py + engines/meshy.py (mode preview, géo only)
8. services/prompt_optimizer.py (Claude API)
9. services/mesh_repair.py (trimesh + pymeshfix → .stl + mesh_metrics)
10. services/quality_scorer.py (Claude API, données brutes → score /10)
11. tasks.py : pipeline orchestrator (BackgroundTasks)
12. routers/pipeline.py (run + status)

### Phase 3 — Interface validation
13. Composant InputForm.jsx + EngineSelector.jsx
14. Composant PipelineTracker.jsx (polling status)
15. Composant ModelViewer.jsx (Three.js, @react-three/fiber)
16. Composant ScoreCard.jsx + ModelActions.jsx
17. Composant ModelCard.jsx (grille)
18. Pages : CreatePage.jsx + ModelsPage.jsx
19. routers/models3d.py (GET, validate, regenerate, remesh)

### Phase 4 — Export
20. services/screenshot.py (pyrender → PNGs)
21. image_engines/base.py + image_engines/stability.py
22. services/seo_gen.py (Claude API → titre, desc, tags, prix, print_params)
23. services/packager.py (ZIP)
24. templates/base.py + templates/cults3d.py
25. Composant ExportPanel.jsx + PrintParams.jsx
26. routers/exports.py

### Phase 5 — Polish
27. SettingsPage.jsx + routers/services.py + routers/stats.py
28. CostTracker.jsx + budget guard dans le pipeline
29. engines/tripo.py (deuxième moteur 3D)
30. Error handling, logs, edge cases
31. Tests : un pytest par service

### Phase 6 — Bonus (pour plus tard)
32. **Module INTEL** : page dédiée scraping tendances (Cults3D, Thingiverse, Printables, Google Trends)
    - Scraper par marketplace (bestsellers, catégories, prix, notes, downloads)
    - Dashboard tendances : graphiques, top catégories, niches sous-exploitées
    - Bouton "Créer un modèle basé sur cette tendance" → envoie vers CreatePage
    - Indépendant du pipeline principal, se branche sans toucher au reste
33. Templates marketplace supplémentaires (Printables, Thangs, MyMiniFactory)
34. Moteurs image supplémentaires (Replicate, GPT image, etc.)
35. Feed-back loop : analyser les rejets pour améliorer les prompts auto
36. Batch processing : lancer N modèles d'un coup avec budget cap
37. Notifications (email ou Telegram quand un modèle est prêt)
38. Upload semi-auto Playwright (optionnel, fragile)

---

## Notes pour Claude Code

- Commencer par Phase 1+2, tester le flow input → .stl + score avant l'interface
- Chaque service est indépendant : un fichier, une responsabilité, testable seul avec pytest
- Le pipeline tourne en BackgroundTask FastAPI (pas de Celery)
- Le frontend poll /pipeline/status toutes les 3s (pas de WebSocket)
- pyrender pour les screenshots : léger, pas de GPU, fonctionne sur VPS avec OSMesa
- Three.js viewer : composant React, charge .glb via GET /api/models/{id}/glb
- Le score QC est informatif : il sert à trier, JAMAIS à rejeter automatiquement
- Les prompts 3D sont orientés géométrie imprimable : pas de texture, formes solides
- Le système de registries (engines, image_engines, templates) charge automatiquement tous les fichiers du dossier
- Pour ajouter un service : un fichier + l'enregistrer → il apparaît dans le dropdown
- SQLite backup à 3h, 7 jours de rétention
- Tous les appels API longs sont dans des BackgroundTasks
- Le budget tracker compte crédits Meshy + tokens Claude + appels image gen
- Pour tester en local avant push VPS : mêmes commandes, tout identique
- .gitignore : data/, .env, node_modules/, frontend/dist/, __pycache__/
- Concurrency : sémaphore asyncio max 2 pipelines simultanés (évite de spammer les APIs)
- Cleanup : les fichiers des modèles rejetés sont supprimés après 7 jours (APScheduler)
- Les APIs externes évoluent : vérifier la doc officielle Meshy/Tripo/Stability au moment de l'implémentation

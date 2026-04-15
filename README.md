# 3D Factory

Usine de contenu 3D full-stack : un pipeline automatisé qui transforme un texte ou une photo en modèle STL imprimable, le valide, le score via Claude, génère des photos lifestyle + métadonnées SEO, puis emballe le tout en ZIP prêt à publier sur une marketplace (Cults3D, Printables, Thangs…).

## Fonctionnalités clés

- **Pipeline automatisé** : texte/photo → prompt optimisé → modèle 3D → STL réparé → validation humaine → ZIP marketplace
- **Moteurs 3D enfichables** : Meshy, Tripo (ajout facile d'autres engines)
- **Scoring qualité + SEO par Claude** (titre, description, tags, prix, paramètres d'impression)
- **Validation humaine** via dashboard React avec viewer Three.js
- **Suivi budget API en temps réel** (plafond journalier configurable)
- **Auth Basic** sur toutes les routes sauf `/api/health`
- **Sauvegardes SQLite quotidiennes** (rétention 7 jours)

## Stack technique

- **Backend** : Python 3 · FastAPI · Uvicorn · SQLAlchemy (SQLite) · trimesh · pymeshfix · pyrender · APScheduler
- **Frontend** : React 18 · Vite · React Router · Three.js (`@react-three/fiber`, `@react-three/drei`)
- **IA & APIs externes** : Anthropic Claude · Meshy · Tripo · Stability AI
- **Déploiement** : Caddy (HTTPS) + systemd sur VPS Ubuntu

## Structure du dépôt

```
3D-Factory/
├── backend/              Serveur FastAPI
│   ├── main.py           Point d'entrée (uvicorn main:app)
│   ├── routers/          Endpoints API (/pipeline, /models, /exports, /stats…)
│   ├── services/         Logique métier (prompt, mesh, scoring, SEO, packaging)
│   ├── engines/          Clients 3D (Meshy, Tripo)
│   ├── image_engines/    Clients image (Stability)
│   ├── templates/        Templates marketplace (Cults3D…)
│   ├── data/             Fichiers générés (gitignoré)
│   └── requirements.txt
├── frontend/             Application React + Vite
│   ├── src/              Pages, composants, viewer 3D
│   └── package.json
├── scripts/              setup_vps.sh · deploy.sh · backup.sh
├── ARCHITECTURE_FINALE.md  Architecture détaillée
└── SPECS_FINALE.md         Spécifications techniques
```

## Prérequis

- **Python ≥ 3.10**
- **Node.js ≥ 18** + npm
- **Clés API** :
  - `ANTHROPIC_API_KEY` (obligatoire — prompt, scoring, SEO)
  - `MESHY_API_KEY` (obligatoire pour le moteur 3D par défaut)
  - `STABILITY_API_KEY` (obligatoire pour les photos lifestyle)
  - `TRIPO_API_KEY` (optionnel, moteur 3D alternatif)
- **Libs système pour `pyrender` (rendu OpenGL headless)** — sur Ubuntu/Debian :
  ```bash
  sudo apt install -y libgl1 libegl1 libglib2.0-0
  ```

## Installation (développement local)

```bash
# 1. Cloner le dépôt
git clone <url-du-repo>
cd 3D-Factory

# 2. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec tes clés API et identifiants

# 3. Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# 4. Frontend
cd frontend
npm install
cd ..
```

### Variables d'environnement (`.env`)

| Variable | Description |
|---|---|
| `APP_USER` / `APP_PASS` | Identifiants Basic Auth (obligatoire) |
| `ANTHROPIC_API_KEY` | Clé Claude API (obligatoire) |
| `MESHY_API_KEY` | Clé Meshy (moteur 3D par défaut) |
| `STABILITY_API_KEY` | Clé Stability AI (photos lifestyle) |
| `TRIPO_API_KEY` | Clé Tripo (optionnel) |
| `CLAUDE_MODEL` | Modèle Claude (défaut : `claude-sonnet-4-5`) |
| `DEFAULT_ENGINE` | Moteur 3D par défaut (`meshy` / `tripo`) |
| `DEFAULT_IMAGE_ENGINE` | Moteur image par défaut (`stability`) |
| `DEFAULT_TEMPLATE` | Template marketplace par défaut (`cults3d`) |
| `MAX_DAILY_BUDGET_EUR` | Plafond quotidien d'API en € (défaut : `2.00`) |
| `HOST` / `PORT` | Bind du serveur (défaut : `0.0.0.0:8000`) |
| `DATA_DIR` | Dossier de données (défaut : `./data`) |

## Lancement en développement

Deux terminaux :

```bash
# Terminal 1 — backend (hot reload)
cd backend
source venv/bin/activate
uvicorn main:app --reload
# → http://localhost:8000

# Terminal 2 — frontend (Vite dev server)
cd frontend
npm run dev
# → http://localhost:5173 (les appels /api sont proxifiés vers :8000)
```

Ouvre **http://localhost:5173**, connecte-toi avec `APP_USER` / `APP_PASS`.

La base SQLite est créée automatiquement au premier démarrage (`backend/data/db.sqlite`).

## Lancement en production (build monolithique)

Le frontend est servi en statique par FastAPI, donc un seul port à exposer.

```bash
# 1. Build du frontend
cd frontend
npm run build          # génère frontend/dist/
cd ..

# 2. Démarrage du backend (sert l'API + la SPA)
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Tout est accessible sur **http://localhost:8000** : `/api/*` pour l'API et `/` pour la SPA.

## Déploiement VPS (Ubuntu)

Les scripts dans `scripts/` automatisent le déploiement sur un VPS (ex. Hetzner CX22) avec Caddy en reverse proxy HTTPS.

```bash
# Provisioning initial (une seule fois)
bash scripts/setup_vps.sh

# Déploiement / mise à jour (git pull, build, restart)
bash scripts/deploy.sh

# Sauvegarde SQLite manuelle (cron quotidien installé par setup_vps.sh)
bash scripts/backup.sh
```

## Tests

```bash
cd backend
source venv/bin/activate
pytest tests/
```

## Endpoints utiles

- `GET /api/health` — healthcheck public (sans auth, pour uptime monitoring)
- `POST /api/pipeline/run` — lance une génération
- `GET /api/pipeline/status/{id}` — suit l'avancement
- `GET /api/models` — liste les modèles générés
- `GET /api/stats` — budget & coûts API
- Documentation interactive : **http://localhost:8000/docs**

## Données générées

Tout est stocké sous `backend/data/` (gitignoré) :

- `db.sqlite` — base de données
- `models/{id}/` — fichiers GLB + STL
- `screenshots/{id}/` — 4 vues PNG
- `photos/{id}/` — photos lifestyle (Stability)
- `exports/{id}/` — ZIPs marketplace
- `backups/` — snapshots SQLite sur 7 jours

## Pour aller plus loin

- [`ARCHITECTURE_FINALE.md`](ARCHITECTURE_FINALE.md) — architecture complète, flux de données, choix techniques
- [`SPECS_FINALE.md`](SPECS_FINALE.md) — spécifications techniques détaillées (API, schémas, contrats)

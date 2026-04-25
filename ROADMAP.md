# 3D Print Factory — Roadmap d'implémentation (v3, 2026-04-25)

Ordre = priorité d'exécution. Items `[x]` = fait, `[~]` = partiel, `[ ]` = à faire. Chaque phase se termine quand ses items sont verts.

**État global au 2026-04-25** : pipeline (repair, viewer R3F, endpoints thumb/prompts/costs/exports) en place. **Phase 1.1 (repair) bouclée**, G2 résolu (code Printed retiré). Manques restants : décision Meshy 2-stage (1.2), profils catégoriels (1.4), traçabilité prompts (1.5).

**Changements v3** : remontée du scorer par profil (#7) et des recettes (#10) en Phase 1 car ce sont des prérequis cachés de la biblio prompts (#2), de regen-smart (#4) et du batch (#5). Ajout d'une section garde-fous transverses.

---

## 🔔 Décision 1.2 prise (2026-04-25) : preview-only par défaut + 2-stage en opt-in

**Conclusion** : on garde **preview-only en défaut** (pas cher, comportement actuel) et on ajoute un **opt-in 2-stage** par génération quand on veut la texture.

Implémentation prévue (Phase 1.7) :
- Setting global `meshy_pipeline_mode` (default `"preview"`) dans la table `settings`
- Override par génération : champ `texture: bool` (default false) dans le payload `POST /api/pipeline/run`
- Si `texture=true` → pipeline preview → refine (texture_prompt + `enable_pbr: true` + `ai_model: "latest"`) — coût ×2
- UI : checkbox "Générer avec texture (×2 coût)" dans InputForm + indicateur dans `/api/costs/hints`
- Recettes (1.8) peuvent imposer `texture: true` pour profils Showcase/Marketplace, false pour Prototype/Fonctionnel

Pourquoi ce choix : la majorité des itérations de design (figurines, prototypes, validation rapide) n'ont pas besoin de texture. Garder preview-only en défaut évite de cramer le budget Meshy. Quand on aura un modèle finaliste pour vendre/poster, on pourra relancer en mode texture sur ce modèle précis.

---

## 🛡 Garde-fous transverses (à intégrer en cours de route)

À traiter dans la phase indiquée — ne pas reporter à la fin :

- **G1 — Drift `settings` overrides ↔ biblio `prompts`** (Phase 1.5) : décider si on déprécie les overrides quand la biblio arrive (migration des overrides → presets nommés) ou si on documente clairement leurs rôles distincts.
- ✅ **G2 — Schéma Printed dormant** (résolu 2026-04-25) : code Printed retiré de `models.py` + `database.py` + tables droppées du SQLite (4 demo users, 3 demo requests purgés). bcrypt + PyJWT retirés de requirements.txt. On reste legacy `models`/`exports`.
- **G3 — Backfill `category`** (Phase 1.4) : modèles existants n'auront pas de catégorie. Choix : "Unknown" par défaut, OU appel Claude rétroactif batch unique au déploiement.
- **G4 — Storage explosion** (Phase 1.9 + Phase 3.13) : color-variants × batch fait grossir vite le disque VPS. Définir politique de purge (ex : variants > 30j non utilisés) ou offload S3-compatible.
- **G5 — RAM pyrender + concurrence** (Phase 1.9) : repair + thumb pyrender pèsent lourd, VPS 4 Go RAM. Worker batch séquentiel obligatoire (déjà prévu), benchmarker pic RAM avant prod.
- **G6 — Tests d'intégration minimaux** : couverture endpoints critiques (pipeline, repair, batch) — pas exhaustif mais suffisant pour ne pas péter en silence sur les migrations DB.
- **G7 — leva mobile-hostile** (Phase 2.10) : panneau dev-tools flottant, inutilisable sur tablette. Si l'app doit servir au partage mobile, prévoir une UI alternative pour les contrôles studio.

---

## Phase 1 — Fondations + traçabilité

### 1.1. Repair auto ✅ fait (2026-04-25)
- [x] Deps `trimesh`, `pymeshfix`, `numpy` dans `backend/requirements.txt`
- [x] Module `backend/services/mesh_repair.py` refactoré : `normalize` + `fill_holes` + `hard_repair` exposés indépendamment, `auto_fix` orchestre
- [x] `should_remesh: true` activé dans `backend/engines/meshy.py`
- [x] Intégration pipeline post-Meshy (avant scoring/thumb), via `_run_repair_and_score` (mode passé en paramètre)
- [x] Endpoint `POST /api/models/{id}/repair` avec `{mode: "auto"|"normalize"|"fill_holes"|"hard"}` — re-rejoue REPAIR + SCORE sans appel API externe
- [x] UI : bouton 🩹 Auto-Fix (action directe) + ⚙ Repair… (panneau avec dropdown modes)
- [x] **Bug latent corrigé** : pymeshfix ≥ 0.18 utilise `points`/`faces` (pas `v`/`f`). L'ancien code échouait silencieusement sur tous les meshes non-watertight.
- [x] Tests unitaires étendus : `test_normalize_mode_only_normalizes`, `test_hard_mode_runs_pymeshfix`, `test_unknown_mode_raises` (8/8 OK)

### 1.2. Décision Meshy 2-stage ✅ (2026-04-25)
Tranché : preview-only par défaut, 2-stage en opt-in par génération. Voir bloc en haut.

### 1.3. Dé-jargoniser l'optimizer ✅ (2026-04-25)
- [x] Briques `prompt_optimizer_text` / `prompt_optimizer_image` réécrites : zéro mention de manifold/watertight/FDM/SLA/1.5mm/surplombs > 60°/thick walls/self-supporting. Focus sur SILHOUETTE et STRUCTURE.
- [x] **`quality_scorer` conservé tel quel** (jargon voulu, scorer expert).
- [x] Instruction système des défauts impose 200-300 caractères max.
- [ ] *Pas appliqué :* `MAX_PROMPT_CHARS=600` / `MAX_TOKENS_REPLY=400` inchangés car l'utilisateur a un override custom (3699 chars de système, ciblant 600 chars de sortie). Lower les limites cassait son override. Reset l'override pour profiter du nouveau défaut.

### 1.4. Scorer par profil catégoriel ✅ (2026-04-25)
- [x] Détection auto catégorie dans l'optimizer : briques `prompt_optimizer_*` renvoient JSON `{"prompt", "category"}`. `prompt_optimizer.py` parse + fallback texte brut (override legacy → category=None)
- [x] `backend/services/scoring_profiles.py` : `PROFILE_WEIGHTS` (Figurine/Fonctionnel/Déco) + `DEFAULT_WEIGHTS` + `compute_weighted_score()`
- [x] `quality_scorer.score_mesh(metrics, desc, category)` calcule le score global via `scoring_profiles.compute_weighted_score()` ; fallback sur le `score` de Claude si pas de critères exploitables
- [x] Migration DB : `ALTER TABLE models ADD COLUMN category TEXT` + index. G3 = NULL pour les modèles antérieurs (pas de backfill rétroactif Claude — trop cher pour valeur tiède)
- [x] UI : badge `🗿 Figurine` / `🔩 Fonctionnel` / `🪴 Déco` sur ScoreCard avec tooltip qui explique les pondérations
- [x] Tests : 7 nouveaux tests scoring_profiles (15 total OK)
- [ ] **Side-effect** : l'override custom de l'utilisateur sur `prompt_optimizer_*` produit du texte brut (pas du JSON), donc category=None. Reset l'override pour profiter de la détection automatique.

### 1.5. Bibliothèque de prompts versionnée ✅ (2026-04-25)
**Option A retenue (clean migration)** : la table `prompts` est maintenant la source de vérité, les overrides Settings ont été migrés en presets "User custom".

- [x] Table `prompts` : `id, brick_id, name, content, category, tags, notes, is_default, is_active, usage_count, avg_score, created_at, updated_at`
- [x] Table `generation_prompts` : `(model_id, brick_id) PK + prompt_id FK` (traçabilité)
- [x] Index partiel SQLite `ux_prompts_active_per_brick` (1 seul actif par brique)
- [x] Migration `database._seed_prompt_library_and_migrate_overrides()` : crée Default pour chaque brique, migre les `prompt_override_*` existants en "User custom (migrated)" actifs, drop les rows settings
- [x] `app_settings.get_effective_prompt(brick_id)` lit depuis `Prompt.is_active` (fallback registry default si biblio vide)
- [x] CRUD `/api/prompts/library` + activation : `GET ?brick_id=X&category=Y`, `POST`, `PUT /{id}`, `DELETE /{id}` (refusé si is_default), `POST /{id}/activate`
- [x] `/api/prompts` legacy conservé : PUT brick = upsert User custom + activate, DELETE brick = réactive Default (User custom conservé en biblio)
- [x] Hook traçabilité dans `tasks.py` : `track_prompt_use(model_id, brick_id)` après optimizer + scorer, `update_prompt_avg_score_for_model()` après scoring (moyenne mobile)
- [x] UI Settings : dropdown des presets disponibles avec usage_count + avg_score, bouton "＋ Nouveau preset" qui crée et active, suppression via ✕ (Default protégé)
- [ ] *Pas fait :* seed des 5-10 presets système par brique × catégorie (Generic, Figurines, Déco, Mécanique, Low-poly). Pas critique pour MVP — l'utilisateur peut créer ses presets au fil de l'eau et la moyenne mobile fera émerger les meilleurs.

### 1.6. Régénération intelligente ✅ (2026-04-25)
- [x] Nouvelle brique `regen_smart` dans `prompt_registry.py` (7e brique) avec few-shot par profil (Figurine/Fonctionnel/Déco) + règles d'ajustement par défaut bas
- [x] Service `services/regen_smart.py` : un seul appel Claude (prompt original + category + score + criteria + summary) → JSON `{prompt, rationale}`
- [x] Endpoint `POST /api/models/{id}/regen-smart-suggest` (pure-read, pas de side-effect — l'UI orchestre la confirmation via le flow regenerate existant)
- [x] UI ModelActions : bouton 🧠 Regen smart (désactivé tant que pas de qc_score), pré-remplit le panneau Regénérer avec la suggestion et affiche la rationale
- [x] Désign retenu : pas de bouton "auto-confirm" — l'utilisateur revoit le prompt avant de relancer, évite les regen surprises

### 1.7. Split prompt silhouette/texture (opt-in 2-stage) — ⏸ DÉCALÉ
**Décalé 2026-04-25** : pas de besoin texture immédiat. À réactiver quand on attaque Phase 3 (vidéo TikTok, showcase marketplace) et qu'on veut des rendus PBR. Détails du plan conservés ci-dessous.

- [ ] Setting global `meshy_pipeline_mode` (default `"preview"`) — utilisable comme fallback si l'API ne reçoit pas d'override
- [ ] Champ `texture: bool` dans `POST /api/pipeline/run` (default false)
- [ ] Persister `texture_requested` + `preview_task_id` + `refine_task_id` séparément sur `models`
- [ ] Nouvelle brique `prompt_texture` dans `prompt_registry.py` (matériaux/couleurs uniquement, 200-300 chars)
- [ ] Refactor `backend/engines/meshy.py` : ajouter chemin 2-stage = `create_task(prompt)` preview → `refine_task(preview_id, texture_prompt, enable_pbr=True, ai_model="latest")` quand texture=true
- [ ] Pipeline tracker : insérer étape "TEXTURE" entre FORGE et REPAIR uniquement quand texture=true
- [ ] `/api/costs/hints` : retourne `meshy_eur` simple en mode preview, `meshy_eur * 2` quand texture=true (param query)
- [ ] UI InputForm : checkbox "Générer avec texture (×2 coût)" + tooltip explicatif
- [ ] Recettes (1.8) peuvent imposer `texture: true` (Showcase/Marketplace) ou false (Prototype/Fonctionnel)

### 1.8. Recettes minimales ✅ (2026-04-25)
**Scope v1 réduit** : pas de FK prompts/textures (1.7 décalée), pas de meshy_settings JSON. La recette capture juste engine + image_engine + category + notes. Suffisant pour le prérequis UX du batch (1.9).

- [x] Table `recipes` : `id, name UNIQUE, engine, image_engine, category, notes, usage_count, created_at, updated_at`
- [x] CRUD `/api/recipes` (GET / POST / PUT / DELETE / POST /{id}/use pour incrémenter usage_count)
- [x] Validation des engines via `engines.get_engine` + `image_engines.get_image_engine`
- [x] UI InputForm : dropdown "Recette" en haut (caché si liste vide), sélection pré-remplit engine + stocke image_engine pour le payload
- [x] Bouton 💾 Recette dans ModelActions : capture engine/image_engine/category courants en preset nommé
- [x] *Pas de seed* automatique — l'utilisateur crée à partir d'un modèle réussi via 💾 Recette. Les recettes émergent par usage réel.
- [ ] *Phase 2.13 ajoutera* : optimizer_prompt_id, texture_prompt_id, repair_flags, viewer_preset_id, slicer_preset_id, listing_template

### 1.9. Mode batch ✅ (2026-04-25)
**Garde-fous appliqués** : G5 (worker séquentiel via PIPELINE_SEMAPHORE + boucle await), budget cap. G4 (storage purge) à traiter quand on aura color-variants Phase 3.16.

- [x] Tables `batch_jobs` (id, recipe_id, status, total, done, failed, max_budget_eur, spent_eur, cancel_requested, error, timestamps) + `batch_items` (id, batch_id, position, prompt, status, model_id, error, timestamps)
- [x] Statuts `BatchJob` : pending / running / done / cancelled / budget_exceeded / failed
- [x] Statuts `BatchItem` : pending / running / done / failed / skipped
- [x] Endpoints : `POST /api/batch`, `GET /api/batch`, `GET /api/batch/{id}`, `POST /api/batch/{id}/cancel`
- [x] Limite 200 items/batch, 5000 chars/prompt
- [x] Worker `tasks.run_batch(batch_id)` : boucle séquentielle avec await sur run_pipeline_guarded, check cancel + budget avant chaque item, marque les restants `skipped` à l'arrêt
- [x] `_batch_spent_eur` agrège les coûts via JOIN batch_items → models.cost_eur_estimate
- [x] UI nouvelle page `/batch` : formulaire (recette + textarea prompts + budget) + liste batches (polling 3s) + détail items expandable
- [ ] Pas fait : upload CSV (textarea suffit pour MVP), notification post-batch (bandeau OK suffit visible via polling)

---

## Phase 2 — UX et différenciation

### 2.10. Studio viewer modulable (R3F → Studio) ✅ (2026-04-25, scope v1)
`ModelViewer.jsx` utilise R3F + drei + leva. Persistence presets reportée à 2.13.

**Garde-fou G7 appliqué** : panneau leva masqué sur mobile via `@media (max-width: 768px) { #leva__root { display: none !important } }` (CSS index.css).

- [x] Migration R3F + `drei`
- [x] Panneau contrôles `leva` (collapsed par défaut, drag-friendly)
- [x] Contrôles : lights (presets Studio 3-points / Softbox / Dramatic / Flat), HDRI (8 presets drei), matériau (Original / Porcelaine mat / PLA / ABS / Résine / Métal brossé), fond (HDRI on/off + couleur unie), avancé (ombre portée ContactShadows, exposure, auto-rotate)
- [x] Tone mapping ACES + sRGB output
- [ ] *Pas fait :* Toggle qualité global Éco/Normal/Max (pas critique pour MVP, à revoir si perf devient un problème)
- [ ] *Pas fait :* Cache HDRI côté client + lazy-load (drei gère le caching, ok pour 8 presets)
- [ ] *Décalé 2.13 :* Table `viewer_presets` + seeds + sauvegarde/chargement preset (recettes complètes étendront recipes avec `viewer_preset_id`)

### 2.10b. Historique des actions modèle (timeline UX) ✅ (2026-04-25)
- [x] Table `model_events` append-only : `id, model_id FK CASCADE, event_type, details_json (JSON nullable), created_at` (+ index `model_id`, `created_at`)
- [x] Event types : `created`, `optimized`, `generated`, `repaired` (mode + before/after watertight + face_count), `scored` (score + previous_score + delta), `regenerated`, `remeshed`, `repair_only`
- [x] Service `services/model_events.py` avec `log_event(model_id, type, details)` best-effort (try/except large, types invalides droppés en warning)
- [x] Hooks dans `tasks.py` (optimized après optimizer, generated après FORGE et FORGE remesh, repaired et scored dans `_run_repair_and_score`) + dans routers (`pipeline.py` créé, `models3d.py` regenerated/remeshed/repair_only) + dans `tasks.run_batch` (created)
- [x] Endpoint `GET /api/models/{id}/events` (read-only, ordre ASC chronologique, 404 si modèle inconnu, [] si modèle sans event)
- [x] UI `ModelTimeline.jsx` : timeline verticale compacte dans le panneau modèle, icône par event_type + label court + timestamp relatif via `Intl.RelativeTimeFormat('fr')` + chip details (mode repair, score+delta, target polycount…). Refresh auto via `refreshKey={pipeline_status}-{qc_score}`.
- [x] Pas de pagination (volume négligeable)
- [x] **Pas de backfill** des modèles existants — historique démarre au déploiement
- [x] Test `test_model_events.py` : 3/3 OK (ordre chronologique ASC, modèle vide → [], 404 modèle inconnu)

### 2.11. Banque d'images + image-to-3D ciblé
Meshy `image-to-3d` est **déjà supporté**. Il manque la couche assets.

- [ ] Table `assets` : `id, path, category, tags, source (upload/url/generated), created_at`
- [ ] Page "Assets" : upload, classement par catégorie, tags
- [ ] Endpoint Create : option texte pur / sélection depuis pool / upload direct
- [ ] Use case "cohérence collection" : bouton "Utiliser cette image comme ref pour N générations"

### 2.12. Scorer visuel + tagging auto (fusionné en un appel)
- [ ] Un seul appel Claude Haiku vision après génération du thumb
- [ ] **Note** : thumb 256×256 trop petit pour analyse fine — soit monter résolution thumb, soit générer un screenshot HD à la volée pour le scoring
- [ ] Output JSON : `{visual_score: 0-10, tags: [...]}`
- [ ] Enrichir `score_details` avec la composante visuelle
- [ ] Persister `tags` sur `models` (colonne JSON), indexer pour recherche

### 2.13. Recettes complètes (enrichissement de 1.8)
- [ ] Étendre `recipes` : `viewer_preset_id`, `slicer_preset_id`, `listing_template (JSON)`
- [ ] UI "Recettes" : édition complète, duplication
- [ ] Lier recette → preset viewer auto-appliqué quand on ouvre un modèle

---

## Phase 3 — Production et distribution

### 3.14. Pipeline vidéo TikTok auto
**Risque sous-estimé** : OAuth multi-plateforme via Postiz = 2-3 jours minimum, change tous les 6 mois.

- [ ] Capture turntable : Puppeteer/Playwright headless sur le viewer R3F, sortie MP4
- [ ] Intégration Kling ou Seedance pour intro/outro (contextualisée par bible d'univers, voir 3.17)
- [ ] Compositing FFmpeg : intro + turntable + outro + texte + musique
- [ ] Banque musicale embarquée (tracks libres) + option Suno API
- [ ] Caption + hashtags + CTA via Claude (brique dédiée)
- [ ] Publication via Postiz (self-host ou API) : TikTok / Instagram / YouTube Shorts — **prévoir 2-3j d'OAuth**
- [ ] UI "À publier" : preview, caption/hashtags éditables, swap musique, Publier maintenant / Planifier
- [ ] Toggle global "Autopilot ON/OFF"
- [ ] Scraping stats 48h après post → table `video_stats`

### 3.15. Bouton Twist
- [ ] Brique prompt `twist_generator` : input prompt original → output 3 variantes avec twist cohérent
- [ ] Table `twist_library` : type, description, tags, success_rate
- [ ] Seed : époques, styles artistiques, matériaux improbables, ambiances
- [ ] Feedback : les twists qui scorent 7+ remontent dans la lib

### 3.16. Variantes de couleur (rendu local multi-matériaux)
**Garde-fou G4** : applique politique de purge.

- [ ] Endpoint `POST /api/models/{id}/color-variants` : génère N renders avec matériaux différents
- [ ] Claude suggère 10 colorschemes cohérents (brique dédiée)
- [ ] Bonus : composite background (bureau, en main, à côté d'un mug)
- [ ] Export pack listing : 1 STL + N images PNG prêtes pour Cults
- [ ] **Politique de purge** : variants > 30j non utilisés → suppression auto

### 3.17. Slicer intégré + IA + bible d'univers
**Risque** : OrcaSlicer/PrusaSlicer CLI dans Docker = build lourd + deps Qt. Prototyper le Dockerfile en isolé avant de promettre.

- [ ] Installer OrcaSlicer ou PrusaSlicer CLI sur le VPS (Dockerfile dédié à benchmarker en isolé d'abord)
- [ ] Dropdowns : imprimante (8 presets + Autre), filament (PLA/PETG/TPU), usage (Déco/Fonctionnel/Prototype)
- [ ] Claude reçoit métadonnées modèle + selects → JSON `{params: {...}, justifications: {...}}`
- [ ] Appel CLI slicer avec les params → G-code
- [ ] UI : afficher temps/poids/couches, télécharger G-code, bouton "Ajuster manuellement"
- [ ] Bible d'univers : doc `universe_bible.md` + table `universe_entities` (lieux, factions, lore) → alimente captions + intros vidéo

---

## Phase 4 — Architecture vivante (plus tard)

### 4.18. Analytics + agent conversationnel
- [ ] Dashboard : générations/jour, score moyen par profil/prompt, taux ratés, CA estimé
- [ ] Agent Claude avec tools DB (read-only) pour répondre aux questions métier

### 4.19. Intégration imprimante directe
- [ ] Connecteurs OctoPrint / Moonraker / Bambu Cloud
- [ ] Bouton "Imprimer à distance" depuis la page modèle

### 4.20. Plateforme de vente
- [ ] Site perso avec paiement direct (Stripe)
- [ ] Commission interne 15-20% vs 30% Cults
- [ ] Migration progressive du catalogue

---

## Archivé (à réactiver si besoin)
- Backup/export auto
- Comparateur de modèles
- Collections en feature dédiée (convention d'usage de la biblio de prompts suffit)
- Auto-variantes via bouton "dupliquer avec variation"

## Réserve stratégique (si la vision évolue)
- Living models (QR + Claude persona dans le lore)
- GitHub des objets 3D (remix + royalties)
- Proactif calendrier/mails
- Caisse à souvenirs (BtoB événementiel)
- Modèle auto-réparateur (V2.0 gratuite aux anciens acheteurs)
- Firmware imprimante custom (Klipper)

---

## Principes directeurs (à relire avant chaque feature)
- Meshy = créatif / CadQuery+Claude = fonctionnel (routing auto par catégorie)
- Post-processing obligatoire, génération seule ne suffit jamais
- Prompts courts/denses (200-300 chars) **côté optimizer uniquement** — le scorer garde son jargon technique
- Profils spécialisés partout plutôt que générique mou
- Compound effect : chaque feature prépare la suivante
- Automatisation max + intervention légère optionnelle, jamais de tâche longue humaine obligatoire

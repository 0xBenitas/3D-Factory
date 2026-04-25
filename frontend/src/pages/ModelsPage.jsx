import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import usePolling from '../hooks/usePolling.js'
import ErrorBoundary from '../components/ErrorBoundary.jsx'
import ExportPanel from '../components/ExportPanel.jsx'
import ModelActions from '../components/ModelActions.jsx'
import ModelCard from '../components/ModelCard.jsx'
import ModelTimeline from '../components/ModelTimeline.jsx'
import ModelViewer from '../components/ModelViewer.jsx'
import ScoreCard from '../components/ScoreCard.jsx'
import { getGlbUrl, getInputImageUrl, getModel, listModels } from '../api.js'

const FILTERS = [
  { key: 'all',      label: 'Tous' },
  { key: 'pending',  label: 'En attente' },
  { key: 'approved', label: 'Approuvés' },
  { key: 'rejected', label: 'Rejetés' },
]

const SORTS = [
  { key: 'date_desc',  label: 'Récents d\'abord' },
  { key: 'score_desc', label: 'Meilleur score' },
  { key: 'score_asc',  label: 'Pire score' },
  { key: 'date_asc',   label: 'Anciens d\'abord' },
]

// Statuts pipeline qui doivent être auto-rafraîchis (un modèle en cours
// de génération OU d'export depuis la grille).
const RUNNING_STATUSES = new Set([
  'prompt', 'generating', 'repairing', 'scoring', 'photos', 'packing',
])

export default function ModelsPage() {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('date_desc')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailError, setDetailError] = useState(null)

  // Tracke les fetch en vol pour pouvoir les abort sur unmount / changement
  // de paramètres : sans ça, une navigation pendant un fetch lent produit
  // des setState sur composant démonté (warnings React + UI incohérente).
  const inflightRef = useRef(new Set())

  const reloadList = useCallback(async () => {
    const abort = new AbortController()
    inflightRef.current.add(abort)
    try {
      const list = await listModels({ validation: filter, sort, signal: abort.signal })
      setModels(list)
      setError(null)
    } catch (exc) {
      if (exc?.name === 'AbortError') return
      setError(exc.detail || exc.message)
    } finally {
      inflightRef.current.delete(abort)
      setLoading(false)
    }
  }, [filter, sort])

  const reloadDetail = useCallback(async () => {
    if (selectedId == null) return
    const abort = new AbortController()
    inflightRef.current.add(abort)
    try {
      const d = await getModel(selectedId, { signal: abort.signal })
      setDetail(d)
      setDetailError(null)
    } catch (exc) {
      if (exc?.name === 'AbortError') return
      setDetailError(exc.detail || exc.message)
      setDetail(null)
    } finally {
      inflightRef.current.delete(abort)
    }
  }, [selectedId])

  // Au unmount ou quand on change de filtre/tri/selectedId, on abort toutes
  // les requêtes encore en vol — les anciennes deviennent inutiles dès qu'un
  // nouveau fetch part.
  useEffect(() => {
    return () => {
      for (const a of inflightRef.current) a.abort()
      inflightRef.current.clear()
    }
  }, [])

  useEffect(() => {
    reloadList()
  }, [reloadList])

  useEffect(() => {
    reloadDetail()
  }, [reloadDetail])

  // Filtre client-side sur le texte d'entrée utilisateur. Le backend ne
  // retourne pas `optimized_prompt` dans la liste (seulement dans le détail),
  // donc la recherche porte sur input_text. Cas-insensible, trim des
  // espaces, no-op si recherche vide.
  const filteredModels = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return models
    return models.filter((m) => {
      const hay = [
        m.input_text || '',
        m.engine || '',
        String(m.id),
      ].join(' ').toLowerCase()
      return hay.includes(q)
    })
  }, [models, search])

  // Auto-poll : si un modèle tourne actuellement (dans la liste ou le
  // détail), on recharge toutes les 3s. Sinon on s'arrête.
  const anyRunning = useMemo(
    () =>
      models.some((m) => RUNNING_STATUSES.has(m.pipeline_status)) ||
      (detail && RUNNING_STATUSES.has(detail.pipeline_status)),
    [models, detail],
  )

  const pollBoth = useCallback(() => {
    reloadList()
    reloadDetail()
  }, [reloadList, reloadDetail])
  usePolling(pollBoth, 3000, { enabled: anyRunning })

  const handleActionDone = async () => {
    // Appelé après approve/regen/remesh/reject.
    await Promise.all([reloadList(), reloadDetail()])
  }

  // Keyboard shortcuts : j/k pour naviguer, a approuver, r rejeter,
  // e regen, / pour focus la recherche, ? pour afficher l'aide.
  // Désactivés si un input/textarea a le focus (sauf "/" qui y échappe).
  const [shortcutsHelp, setShortcutsHelp] = useState(false)
  const searchRef = useRef(null)

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target?.tagName || '').toLowerCase()
      const inField = tag === 'input' || tag === 'textarea' || e.target?.isContentEditable
      // "/" ouvre la recherche quelle que soit la position (sauf si déjà dans un input).
      if (e.key === '/' && !inField) {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      if (e.key === 'Escape') {
        if (shortcutsHelp) setShortcutsHelp(false)
        if (tag === 'input' || tag === 'textarea') e.target.blur()
        return
      }
      if (inField) return  // tous les autres shortcuts s'arrêtent ici

      // Navigation dans la liste filtrée (triée côté backend).
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault()
        if (filteredModels.length === 0) return
        const idx = filteredModels.findIndex((m) => m.id === selectedId)
        const next = e.key === 'j'
          ? Math.min(idx + 1, filteredModels.length - 1)
          : Math.max(idx - 1, 0)
        const target = idx === -1
          ? filteredModels[0]
          : filteredModels[next] || filteredModels[idx]
        if (target) setSelectedId(target.id)
        return
      }
      if (e.key === '?') {
        e.preventDefault()
        setShortcutsHelp((v) => !v)
        return
      }
      // Actions sur le modèle sélectionné.
      if (!detail) return
      if (e.key === 'a') {
        e.preventDefault()
        document.querySelector('.model-actions .btn--success')?.click()
      } else if (e.key === 'r') {
        // Toggle le panneau de rejet (évite les rejets non-confirmés).
        e.preventDefault()
        const rejectBtn = document.querySelector('.model-actions__buttons .btn--danger')
        rejectBtn?.click()
      } else if (e.key === 'e') {
        e.preventDefault()
        const regenBtn = document.querySelectorAll('.model-actions__buttons .btn')[1]
        regenBtn?.click()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [filteredModels, selectedId, detail, shortcutsHelp])

  return (
    <section className="page models-page">
      <div className="page__header">
        <h2>Models</h2>
        <div className="models-page__filters">
          <div className="filter-group">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                className={`btn btn--chip ${filter === f.key ? 'btn--active' : ''}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            aria-label="Trier les modèles"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <input
            ref={searchRef}
            type="search"
            className="models-page__search"
            placeholder="Rechercher… (ou /)"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Rechercher dans les modèles"
          />
          <button
            type="button"
            className="btn btn--chip"
            onClick={() => setShortcutsHelp((v) => !v)}
            aria-label="Aide raccourcis clavier"
            title="Raccourcis clavier (?)"
          >
            ⌨
          </button>
        </div>
      </div>

      {shortcutsHelp && (
        <div className="shortcuts-help">
          <strong>Raccourcis clavier</strong>
          <div className="shortcuts-help__grid">
            <span><kbd>j</kbd> / <kbd>k</kbd></span><span>Naviguer dans la liste</span>
            <span><kbd>/</kbd></span>            <span>Focus recherche</span>
            <span><kbd>a</kbd></span>            <span>Approuver le modèle sélectionné</span>
            <span><kbd>e</kbd></span>            <span>Ouvrir le panneau Regénérer</span>
            <span><kbd>r</kbd></span>            <span>Ouvrir le panneau Rejeter</span>
            <span><kbd>Esc</kbd></span>          <span>Quitter la recherche / fermer l'aide</span>
            <span><kbd>?</kbd></span>            <span>Afficher / masquer cette aide</span>
          </div>
        </div>
      )}

      {error && <div className="error">Erreur : {error}</div>}

      <div className="models-page__layout">
        <div className="models-page__grid">
          {loading && (
            <>
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={`sk-${i}`} className="skeleton skeleton--card" />
              ))}
            </>
          )}
          {!loading && models.length === 0 && (
            <div className="muted">Aucun modèle — va en faire un dans Create.</div>
          )}
          {!loading && models.length > 0 && filteredModels.length === 0 && (
            <div className="muted">Aucun résultat pour « {search.trim()} ».</div>
          )}
          {!loading && filteredModels.map((m) => (
            <ModelCard
              key={m.id}
              model={m}
              selected={m.id === selectedId}
              onClick={() => setSelectedId(m.id)}
            />
          ))}
        </div>

        <div className="models-page__detail">
          {selectedId == null && (
            <div className="muted">Sélectionne un modèle à gauche.</div>
          )}
          {selectedId != null && detailError && (
            <div className="error">Erreur détail : {detailError}</div>
          )}
          {detail && (
            <div className="detail">
              <div className="detail__header">
                <h3>
                  Modèle #{detail.id}
                  <span className={`chip chip--${detail.validation}`}>
                    {detail.validation}
                  </span>
                </h3>
                <code className="detail__status">{detail.pipeline_status}</code>
              </div>

              {detail.glb_path ? (
                <ErrorBoundary
                  fallback={(err, reset) => (
                    <div className="model-viewer model-viewer--empty" style={{ height: 400 }}>
                      <div className="muted" style={{ textAlign: 'center' }}>
                        Impossible d'afficher le modèle
                        <div style={{ fontSize: '0.8rem', marginTop: '0.4rem' }}>
                          {String(err?.message || err)}
                        </div>
                        <button
                          type="button"
                          className="btn"
                          style={{ marginTop: '0.6rem' }}
                          onClick={reset}
                        >
                          Réessayer
                        </button>
                      </div>
                    </div>
                  )}
                >
                  <ModelViewer glbUrl={getGlbUrl(detail.id)} />
                </ErrorBoundary>
              ) : (
                <div className="model-viewer model-viewer--empty">
                  <span className="muted">
                    {detail.pipeline_status === 'failed'
                      ? 'Génération échouée'
                      : 'GLB pas encore généré'}
                  </span>
                </div>
              )}

              {detail.pipeline_error && (
                <div className="error detail__error">
                  <strong>Erreur pipeline :</strong> {detail.pipeline_error}
                </div>
              )}

              {detail.input_type === 'image' && detail.input_image_path && (
                <div className="detail__input-image">
                  <strong>Photo source :</strong>
                  <img
                    src={getInputImageUrl(detail.id)}
                    alt={`Input photo du modèle #${detail.id}`}
                    className="detail__input-image-img"
                  />
                </div>
              )}

              {(detail.optimized_prompt || detail.input_text) && (
                <div className="detail__prompt">
                  <strong>
                    {detail.optimized_prompt ? 'Prompt optimisé' : 'Input'} :
                  </strong>
                  <blockquote>
                    {detail.optimized_prompt || detail.input_text}
                  </blockquote>
                </div>
              )}

              {detail.mesh_metrics && (
                <ScoreCard
                  score={detail.qc_score}
                  meshMetrics={detail.mesh_metrics}
                  qcDetails={detail.qc_details}
                  category={detail.category}
                />
              )}

              <ModelTimeline
                modelId={detail.id}
                refreshKey={`${detail.pipeline_status}-${detail.qc_score ?? 'x'}`}
              />

              <ModelActions model={detail} onChanged={handleActionDone} />

              {detail.validation === 'approved' && (
                <ExportPanel model={detail} onChanged={handleActionDone} />
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import ModelActions from '../components/ModelActions.jsx'
import ModelCard from '../components/ModelCard.jsx'
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
// de génération depuis la grille).
const RUNNING_STATUSES = new Set(['prompt', 'generating', 'repairing', 'scoring'])

export default function ModelsPage() {
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('date_desc')
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailError, setDetailError] = useState(null)

  const reloadList = useCallback(async () => {
    try {
      const list = await listModels({ validation: filter, sort })
      setModels(list)
      setError(null)
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setLoading(false)
    }
  }, [filter, sort])

  const reloadDetail = useCallback(async () => {
    if (selectedId == null) return
    try {
      const d = await getModel(selectedId)
      setDetail(d)
      setDetailError(null)
    } catch (exc) {
      setDetailError(exc.detail || exc.message)
      setDetail(null)
    }
  }, [selectedId])

  useEffect(() => {
    reloadList()
  }, [reloadList])

  useEffect(() => {
    reloadDetail()
  }, [reloadDetail])

  // Auto-poll : si un modèle tourne actuellement (dans la liste ou le
  // détail), on recharge toutes les 3s. Sinon on s'arrête.
  const anyRunning = useMemo(
    () =>
      models.some((m) => RUNNING_STATUSES.has(m.pipeline_status)) ||
      (detail && RUNNING_STATUSES.has(detail.pipeline_status)),
    [models, detail],
  )

  useEffect(() => {
    if (!anyRunning) return
    const t = setInterval(() => {
      reloadList()
      reloadDetail()
    }, 3000)
    return () => clearInterval(t)
  }, [anyRunning, reloadList, reloadDetail])

  const handleActionDone = async () => {
    // Appelé après approve/regen/remesh/reject.
    await Promise.all([reloadList(), reloadDetail()])
  }

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
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error">Erreur : {error}</div>}

      <div className="models-page__layout">
        <div className="models-page__grid">
          {loading && <div className="muted">Chargement…</div>}
          {!loading && models.length === 0 && (
            <div className="muted">Aucun modèle — va en faire un dans Create.</div>
          )}
          {models.map((m) => (
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
                <ModelViewer glbUrl={getGlbUrl(detail.id)} />
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
                />
              )}

              <ModelActions model={detail} onChanged={handleActionDone} />

              {/* Phase 4 : ExportPanel arrive ici */}
              {detail.validation === 'approved' && (
                <div className="detail__phase4-placeholder muted">
                  Export (photos lifestyle + ZIP) — arrive en Phase 4.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

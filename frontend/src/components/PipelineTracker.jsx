import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { cancelPipeline, getPipelineStatus } from '../api.js'

// Phase génération uniquement (étapes 1-5). Les étapes "photos" et
// "packing" sont déclenchées depuis /models via ExportPanel après
// approbation humaine — les afficher ici serait trompeur car elles ne
// se lancent pas automatiquement (cf. UX review).
const STEPS = [
  { key: 'prompt',     label: 'Prompt' },
  { key: 'generating', label: 'Génération 3D' },
  { key: 'repairing',  label: 'Repair' },
  { key: 'scoring',    label: 'Score' },
  { key: 'pending',    label: 'Validation', awaitUser: true },
]

const TERMINAL_STATUSES = new Set(['pending', 'done', 'failed', 'cancelled'])

function stepState(currentStatus, stepKey) {
  if (currentStatus === 'failed' || currentStatus === 'cancelled') {
    const thisIdx = STEPS.findIndex((s) => s.key === stepKey)
    return thisIdx === 0 ? (currentStatus === 'cancelled' ? 'cancelled' : 'error') : 'idle'
  }
  if (['done', 'photos', 'packing'].includes(currentStatus)) {
    return 'done'
  }
  const currentIdx = STEPS.findIndex((s) => s.key === currentStatus)
  const thisIdx = STEPS.findIndex((s) => s.key === stepKey)
  if (currentIdx === -1 || thisIdx === -1) return 'idle'
  if (thisIdx < currentIdx) return 'done'
  if (thisIdx === currentIdx) {
    return STEPS[thisIdx].awaitUser ? 'await_user' : 'active'
  }
  return 'idle'
}

function StepIcon({ state }) {
  if (state === 'done')       return <span className="step__icon step__icon--done">✓</span>
  if (state === 'active')     return <span className="step__icon step__icon--active" aria-label="En cours" />
  if (state === 'await_user') return <span className="step__icon step__icon--await">→</span>
  if (state === 'error')      return <span className="step__icon step__icon--error">✕</span>
  if (state === 'cancelled')  return <span className="step__icon step__icon--error">⏹</span>
  return <span className="step__icon step__icon--idle">○</span>
}

function formatMMSS(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export default function PipelineTracker({ modelId }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [cancelling, setCancelling] = useState(false)
  const startRef = useRef(Date.now())

  // Historique des durées par étape (clé = stage key, valeur = secondes).
  // Mesuré côté client : on note l'instant où on voit un nouveau stage et on
  // calcule la diff quand le stage change. Approximatif (delta de poll 3s)
  // mais suffisant pour un repère visuel.
  const stageDurations = useRef({})
  const currentStage = useRef(null)
  const currentStageStart = useRef(Date.now())

  const trackStage = (stage) => {
    if (stage === currentStage.current) return
    if (currentStage.current && !TERMINAL_STATUSES.has(currentStage.current)) {
      const d = (Date.now() - currentStageStart.current) / 1000
      stageDurations.current[currentStage.current] = d
    }
    currentStage.current = stage
    currentStageStart.current = Date.now()
  }

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const s = await getPipelineStatus(modelId)
        if (cancelled) return
        trackStage(s.pipeline_status)
        setStatus(s)
        if (TERMINAL_STATUSES.has(s.pipeline_status)) return
        setTimeout(poll, 3000)
      } catch (exc) {
        if (!cancelled) setError(exc.detail || exc.message)
      }
    }
    poll()

    const tick = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)

    return () => {
      cancelled = true
      clearInterval(tick)
    }
  }, [modelId])

  const handleCancel = async () => {
    if (!confirm(
      "Annuler le pipeline ?\n\n" +
      "Les crédits API déjà engagés (Meshy, Claude…) ne sont PAS remboursés. " +
      "L'annulation évite seulement la suite des étapes."
    )) return
    setCancelling(true)
    try {
      await cancelPipeline(modelId)
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setCancelling(false)
    }
  }

  if (error) return <div className="error">Erreur polling : {error}</div>
  if (!status) return <div className="muted">Chargement…</div>

  const isTerminal = TERMINAL_STATUSES.has(status.pipeline_status)
  const canCancel = !isTerminal && !status.cancel_requested

  // Durée de l'étape active (en direct). Les étapes précédentes ont une durée
  // figée dans stageDurations.current.
  const activeDuration = !isTerminal && currentStage.current
    ? (Date.now() - currentStageStart.current) / 1000
    : 0

  return (
    <div className="pipeline-tracker">
      <div className="pipeline-tracker__header">
        <h3>Pipeline #{modelId}</h3>
        <div className="pipeline-tracker__header-meta">
          <CostChip credits={status.cost_credits} eur={status.cost_eur_estimate} />
          {canCancel && (
            <button
              className="btn btn--danger"
              onClick={handleCancel}
              disabled={cancelling}
              title="Arrête le pipeline (crédits engagés non remboursés)"
            >
              {cancelling ? 'Annulation…' : '✕ Annuler'}
            </button>
          )}
        </div>
      </div>

      <ol className="pipeline-tracker__steps">
        {STEPS.map((s) => {
          const state = stepState(status.pipeline_status, s.key)
          const duration = state === 'active'
            ? activeDuration
            : stageDurations.current[s.key]
          const showProgressBar =
            state === 'active'
            && s.key === 'generating'
            && typeof status.pipeline_progress === 'number'
          return (
            <li key={s.key} className={`step step--${state}`}>
              <div className="step__row">
                <StepIcon state={state} />
                <span className="step__label">{s.label}</span>
                {duration !== undefined && (
                  <span className="step__duration muted">{formatMMSS(duration)}</span>
                )}
              </div>
              {showProgressBar && (
                <div className="step__progress">
                  <div className="step__progress-bar" style={{ width: `${status.pipeline_progress}%` }} />
                  <span className="step__progress-label">{status.pipeline_progress}%</span>
                </div>
              )}
            </li>
          )
        })}
      </ol>

      <dl className="pipeline-tracker__meta">
        <dt>Statut</dt>
        <dd>
          <code>{status.pipeline_status}</code>
          {!isTerminal && <span className="muted"> — {formatMMSS(elapsed)} total</span>}
          {status.cancel_requested && !isTerminal && (
            <span className="muted"> — annulation demandée, arrêt imminent…</span>
          )}
        </dd>

        {status.optimized_prompt && (
          <>
            <dt>Prompt optimisé</dt>
            <dd className="pipeline-tracker__prompt">{status.optimized_prompt}</dd>
          </>
        )}

        {status.qc_score !== null && status.qc_score !== undefined && (
          <>
            <dt>Score</dt>
            <dd>{status.qc_score.toFixed(1)} / 10</dd>
          </>
        )}

        {status.pipeline_error && (
          <>
            <dt>Erreur</dt>
            <dd className="error pipeline-tracker__prompt">{status.pipeline_error}</dd>
          </>
        )}
      </dl>

      {status.pipeline_status === 'pending' && (
        <div className="pipeline-tracker__cta">
          <Link to="/models" className="btn btn--primary">
            Valider dans l'atelier →
          </Link>
        </div>
      )}
      {status.pipeline_status === 'failed' && (
        <div className="pipeline-tracker__cta">
          <Link to="/models" className="btn">Voir dans l'atelier</Link>
        </div>
      )}
      {status.pipeline_status === 'cancelled' && (
        <div className="pipeline-tracker__cta muted">
          Pipeline annulé.
        </div>
      )}
    </div>
  )
}

function CostChip({ credits, eur }) {
  if (!credits && !eur) return null
  const eurStr = typeof eur === 'number' ? eur.toFixed(2) : '0.00'
  return (
    <span className="cost-chip" title="Coût cumulé pour ce pipeline">
      💶 {eurStr}€ · {credits || 0} créd.
    </span>
  )
}

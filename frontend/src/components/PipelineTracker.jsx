import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPipelineStatus } from '../api.js'

// Ordre canonique des étapes du pipeline (cf. SPECS §4.2).
const STEPS = [
  { key: 'prompt',     label: 'Prompt' },
  { key: 'generating', label: 'Génération 3D' },
  { key: 'repairing',  label: 'Repair' },
  { key: 'scoring',    label: 'Score' },
  { key: 'pending',    label: 'Validation' },
  { key: 'photos',     label: 'Photos' },      // Phase 4+
  { key: 'packing',    label: 'Export' },      // Phase 4+
]

const TERMINAL_STATUSES = new Set(['pending', 'done', 'failed'])

function stepState(currentStatus, currentError, stepKey) {
  // "failed" : on renvoie ❌ pour l'étape en cours + ○ pour les suivantes.
  if (currentStatus === 'failed') {
    const failedIdx = STEPS.findIndex((s) => s.key === stepKey)
    // On ne sait pas exactement où ça a cassé ; on met ❌ sur "prompt"
    // par convention (l'erreur affichée précise l'étape).
    return failedIdx === 0 ? 'error' : 'idle'
  }
  const currentIdx = STEPS.findIndex((s) => s.key === currentStatus)
  const thisIdx = STEPS.findIndex((s) => s.key === stepKey)
  if (currentIdx === -1 || thisIdx === -1) return 'idle'
  if (thisIdx < currentIdx) return 'done'
  if (thisIdx === currentIdx) return 'active'
  return 'idle'
}

function StepIcon({ state }) {
  if (state === 'done')   return <span className="step__icon step__icon--done">✓</span>
  if (state === 'active') return <span className="step__icon step__icon--active">⏳</span>
  if (state === 'error')  return <span className="step__icon step__icon--error">✕</span>
  return <span className="step__icon step__icon--idle">○</span>
}

export default function PipelineTracker({ modelId }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(Date.now())

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const s = await getPipelineStatus(modelId)
        if (cancelled) return
        setStatus(s)
        if (TERMINAL_STATUSES.has(s.pipeline_status)) return
        setTimeout(poll, 3000)   // SPECS §4.2 : 3s
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

  if (error) return <div className="error">Erreur polling : {error}</div>
  if (!status) return <div className="muted">Chargement…</div>

  const isTerminal = TERMINAL_STATUSES.has(status.pipeline_status)
  const mmss = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`

  return (
    <div className="pipeline-tracker">
      <h3>Pipeline #{modelId}</h3>

      <ol className="pipeline-tracker__steps">
        {STEPS.map((s) => {
          const state = stepState(status.pipeline_status, status.pipeline_error, s.key)
          return (
            <li key={s.key} className={`step step--${state}`}>
              <StepIcon state={state} />
              <span className="step__label">{s.label}</span>
            </li>
          )
        })}
      </ol>

      <dl className="pipeline-tracker__meta">
        <dt>Statut</dt>
        <dd>
          <code>{status.pipeline_status}</code>
          {!isTerminal && <span className="muted"> — {mmss} écoulé</span>}
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
    </div>
  )
}

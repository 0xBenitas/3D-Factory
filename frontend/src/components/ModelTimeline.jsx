import { useEffect, useMemo, useState } from 'react'
import { listModelEvents } from '../api.js'

// Phase 2.10b — historique compact des actions sur un modèle.
// Recharge en même temps que le détail (clé = modelId + refreshKey).

const EVENT_META = {
  created:      { icon: '✨', label: 'Créé' },
  optimized:    { icon: '✏️', label: 'Prompt optimisé' },
  generated:    { icon: '🛠', label: 'Mesh généré' },
  repaired:     { icon: '🩹', label: 'Réparé' },
  scored:       { icon: '🎯', label: 'Scoré' },
  regenerated:  { icon: '🔁', label: 'Regen lancé' },
  remeshed:     { icon: '🪡', label: 'Remesh lancé' },
  repair_only:  { icon: '🛠', label: 'Repair-only lancé' },
}

// Map de unités → millisecondes pour Intl.RelativeTimeFormat. Les seuils
// sont volontairement larges pour éviter des "il y a 89 secondes".
const RELATIVE_BUCKETS = [
  { limit: 60_000,        unit: 'second', divisor: 1000 },
  { limit: 3_600_000,     unit: 'minute', divisor: 60_000 },
  { limit: 86_400_000,    unit: 'hour',   divisor: 3_600_000 },
  { limit: 604_800_000,   unit: 'day',    divisor: 86_400_000 },
  { limit: 2_592_000_000, unit: 'week',   divisor: 604_800_000 },
  { limit: Infinity,      unit: 'month',  divisor: 2_592_000_000 },
]

const RTF = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' })

function relativeTime(isoString) {
  if (!isoString) return ''
  const then = Date.parse(isoString)
  if (Number.isNaN(then)) return ''
  const diff = then - Date.now()
  const abs = Math.abs(diff)
  const bucket = RELATIVE_BUCKETS.find((b) => abs < b.limit) || RELATIVE_BUCKETS[RELATIVE_BUCKETS.length - 1]
  const value = Math.round(diff / bucket.divisor)
  return RTF.format(value, bucket.unit)
}

// Détails formatés en chip secondaire pour quelques events où ça aide
// à comprendre le contexte (mode repair, score, delta, target polycount…).
function describeEvent(event) {
  const d = event.details || {}
  switch (event.event_type) {
    case 'optimized':
      return d.category ? `cat: ${d.category}` : null
    case 'generated': {
      const parts = []
      if (d.engine) parts.push(d.engine)
      if (d.duration_s != null) parts.push(`${d.duration_s}s`)
      if (d.remesh) parts.push(`remesh→${d.target_polycount}`)
      return parts.join(' · ') || null
    }
    case 'repaired': {
      const wt = d.is_watertight ? '✓ watertight' : '✕ leaks'
      const mode = d.mode ? `mode: ${d.mode}` : ''
      return [mode, wt].filter(Boolean).join(' · ')
    }
    case 'scored': {
      if (d.score == null) return null
      const delta = d.delta != null
        ? ` (${d.delta > 0 ? '+' : ''}${d.delta})`
        : ''
      return `${d.score}/10${delta}`
    }
    case 'remeshed':
      return d.target_polycount ? `target: ${d.target_polycount}` : null
    case 'repair_only':
      return d.mode ? `mode: ${d.mode}` : null
    case 'regenerated':
      return d.has_prompt_override ? 'prompt édité' : null
    case 'created':
      return d.source === 'batch' ? `batch #${d.batch_id}` : null
    default:
      return null
  }
}

export default function ModelTimeline({ modelId, refreshKey }) {
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (modelId == null) return undefined
    const abort = new AbortController()
    setLoading(true)
    listModelEvents(modelId, { signal: abort.signal })
      .then((data) => {
        setEvents(data || [])
        setError(null)
      })
      .catch((exc) => {
        if (exc?.name === 'AbortError') return
        setError(exc.detail || exc.message)
      })
      .finally(() => setLoading(false))
    return () => abort.abort()
  }, [modelId, refreshKey])

  const items = useMemo(
    () => events.map((e) => ({
      ...e,
      meta: EVENT_META[e.event_type] || { icon: '•', label: e.event_type },
      detailText: describeEvent(e),
    })),
    [events],
  )

  if (loading && items.length === 0) {
    return <div className="model-timeline model-timeline--empty muted">Historique…</div>
  }
  if (error) {
    return <div className="model-timeline error">Erreur historique : {error}</div>
  }
  if (items.length === 0) {
    return (
      <div className="model-timeline model-timeline--empty muted">
        Aucun événement enregistré (modèle antérieur à la timeline).
      </div>
    )
  }

  return (
    <ol className="model-timeline">
      {items.map((it) => (
        <li key={it.id} className={`model-timeline__item model-timeline__item--${it.event_type}`}>
          <span className="model-timeline__icon" aria-hidden>{it.meta.icon}</span>
          <div className="model-timeline__body">
            <div className="model-timeline__row">
              <span className="model-timeline__label">{it.meta.label}</span>
              <time className="model-timeline__time" dateTime={it.created_at}>
                {relativeTime(it.created_at)}
              </time>
            </div>
            {it.detailText && (
              <span className="model-timeline__detail">{it.detailText}</span>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

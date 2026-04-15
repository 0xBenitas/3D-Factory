import { useCallback, useEffect, useState } from 'react'
import { getCredits } from '../api.js'

// Seuils "faible balance" par provider — calibrés pour que la pill passe en
// rouge quand il reste < ~2-3 générations complètes.
const LOW_THRESHOLDS = {
  meshy: 20,      // ~4 previews
  stability: 3,   // Stability facture ~3 créd / image, donc < 1 image = rouge
  tripo: 20,      // même ordre que Meshy
}
const WARN_THRESHOLDS = {
  meshy: 100,
  stability: 10,
  tripo: 100,
}

const PROVIDERS = [
  { key: 'meshy',     label: 'Meshy',     icon: '🎨' },
  { key: 'stability', label: 'Stability', icon: '🖼' },
  { key: 'tripo',     label: 'Tripo',     icon: '🔺' },
  { key: 'anthropic', label: 'Claude',    icon: '🤖' },
]

const REFRESH_INTERVAL_MS = 5 * 60 * 1000   // aligné sur le cache backend

function levelFor(key, credits) {
  if (credits === null || credits === undefined) return 'unknown'
  if (key in LOW_THRESHOLDS && credits < LOW_THRESHOLDS[key]) return 'low'
  if (key in WARN_THRESHOLDS && credits < WARN_THRESHOLDS[key]) return 'warn'
  return 'ok'
}

function formatRelative(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  const diff = Math.floor((Date.now() - then) / 1000)
  if (diff < 5) return 'à l\'instant'
  if (diff < 60) return `il y a ${diff}s`
  if (diff < 3600) return `il y a ${Math.floor(diff / 60)}min`
  return `il y a ${Math.floor(diff / 3600)}h`
}

export default function CreditsBar() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true)
    setError(null)
    try {
      const res = await getCredits({ refresh })
      setData(res)
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load(false)
    const t = setInterval(() => load(false), REFRESH_INTERVAL_MS)
    return () => clearInterval(t)
  }, [load])

  if (loading && !data) {
    return <div className="credits-bar credits-bar--loading muted">Chargement des soldes…</div>
  }
  if (error && !data) {
    return <div className="credits-bar credits-bar--error">Crédits : {error}</div>
  }
  if (!data) return null

  return (
    <div className="credits-bar">
      {PROVIDERS.map((p) => (
        <ProviderPill key={p.key} provider={p} data={data[p.key]} />
      ))}
      <button
        className="credits-bar__refresh"
        onClick={() => load(true)}
        disabled={refreshing}
        title="Forcer le rafraîchissement (ignore le cache 5 min)"
        aria-label="Rafraîchir les soldes"
      >
        {refreshing ? '…' : '↻'}
      </button>
    </div>
  )
}

function ProviderPill({ provider, data }) {
  if (!data) return null

  // Anthropic : affichage spécial (conso mensuelle locale)
  if (provider.key === 'anthropic') {
    if (!data.available) {
      return (
        <span className="credits-pill credits-pill--unknown" title={data.error || ''}>
          <span className="credits-pill__icon">{provider.icon}</span>
          <span className="credits-pill__label">{provider.label}</span>
          <span className="credits-pill__value">—</span>
        </span>
      )
    }
    const eur = data.month_cost_eur ?? 0
    return (
      <span
        className="credits-pill credits-pill--info"
        title={`Conso cumulée du mois (tous providers) — ${formatRelative(data.fetched_at)}`}
      >
        <span className="credits-pill__icon">{provider.icon}</span>
        <span className="credits-pill__label">{provider.label}</span>
        <span className="credits-pill__value">{eur.toFixed(2)}€ ce mois</span>
      </span>
    )
  }

  // Providers classiques avec balance en crédits
  if (!data.available) {
    return (
      <span
        className="credits-pill credits-pill--unknown"
        title={data.error || 'indisponible'}
      >
        <span className="credits-pill__icon">{provider.icon}</span>
        <span className="credits-pill__label">{provider.label}</span>
        <span className="credits-pill__value">— {data.error ? `(${data.error})` : ''}</span>
      </span>
    )
  }

  const credits = data.credits
  const level = levelFor(provider.key, credits)
  const display = Number.isInteger(credits) ? credits : credits.toFixed(1)

  return (
    <span
      className={`credits-pill credits-pill--${level}`}
      title={`${credits} ${data.unit} — ${formatRelative(data.fetched_at)}`}
    >
      <span className="credits-pill__icon">{provider.icon}</span>
      <span className="credits-pill__label">{provider.label}</span>
      <span className="credits-pill__value">{display} créd.</span>
    </span>
  )
}

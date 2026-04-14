import { useEffect, useMemo, useState } from 'react'
import {
  getSettings,
  getStats,
  listEngines,
  listImageEngines,
  listTemplates,
  updateSettings,
} from '../api.js'

// SPECS §4 SettingsPage : moteurs par défaut + budget quotidien + vue coûts.
// La vue clés API reste future (Phase 6) — on ne les expose jamais au frontend
// par sécurité. On affiche juste les moteurs détectés.

export default function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [stats, setStats] = useState(null)
  const [engines, setEngines] = useState([])
  const [imageEngines, setImageEngines] = useState([])
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState(null)
  const [error, setError] = useState(null)

  const reload = async () => {
    setError(null)
    try {
      const [s, st, e, ie, t] = await Promise.all([
        getSettings(),
        getStats(),
        listEngines(),
        listImageEngines(),
        listTemplates(),
      ])
      setSettings(s)
      setStats(st)
      setEngines(e)
      setImageEngines(ie)
      setTemplates(t)
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const save = async (patch) => {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateSettings(patch)
      setSettings(updated)
      setSavedAt(Date.now())
      setTimeout(() => setSavedAt(null), 1500)
      // Recharge les stats (budget affiché peut avoir changé).
      try {
        setStats(await getStats())
      } catch {
        /* non bloquant */
      }
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <section className="page"><div className="muted">Chargement…</div></section>
  if (!settings) return <section className="page"><div className="error">Impossible de charger les settings.</div></section>

  return (
    <section className="page settings-page">
      <div className="page__header">
        <h2>Settings</h2>
        <p className="muted">
          Défauts du pipeline, budget quotidien et vue d'ensemble des coûts.
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="settings-grid">
        <SelectCard
          label="Moteur 3D par défaut"
          value={settings.default_engine}
          options={engines.map((e) => ({ value: e.name, label: e.name + (e.supports_image ? ' (texte + image)' : ' (texte)') }))}
          onChange={(v) => save({ default_engine: v })}
          disabled={saving}
        />
        <SelectCard
          label="Moteur image par défaut"
          value={settings.default_image_engine}
          options={imageEngines.map((e) => ({ value: e.name, label: e.name }))}
          onChange={(v) => save({ default_image_engine: v })}
          disabled={saving}
        />
        <SelectCard
          label="Template marketplace par défaut"
          value={settings.default_template}
          options={templates.map((t) => ({ value: t.name, label: t.name }))}
          onChange={(v) => save({ default_template: v })}
          disabled={saving}
        />
        <BudgetCard
          value={settings.max_daily_budget_eur}
          onSave={(v) => save({ max_daily_budget_eur: v })}
          disabled={saving}
        />
      </div>

      {savedAt && <div className="settings-saved muted">✓ Enregistré</div>}

      {stats && <StatsOverview stats={stats} />}
    </section>
  )
}

// ---------------------------------------------------------------------- //

function SelectCard({ label, value, options, onChange, disabled }) {
  return (
    <div className="settings-card">
      <label className="settings-card__label">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || options.length === 0}
      >
        {options.length === 0 && <option value="">—</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function BudgetCard({ value, onSave, disabled }) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => {
    setDraft(String(value))
  }, [value])

  const changed = useMemo(() => {
    const n = Number(draft)
    return !Number.isNaN(n) && Math.abs(n - value) > 1e-6
  }, [draft, value])

  const handleSave = () => {
    const n = Number(draft)
    if (Number.isNaN(n) || n < 0) return
    onSave(Number(n.toFixed(2)))
  }

  return (
    <div className="settings-card">
      <label className="settings-card__label">Budget quotidien max (€)</label>
      <div className="settings-card__inline">
        <input
          type="number"
          min="0"
          step="0.5"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled}
        />
        <button
          className="btn btn--primary"
          onClick={handleSave}
          disabled={disabled || !changed}
        >
          Enregistrer
        </button>
      </div>
      <small className="muted">
        0 = garde désactivée (le pipeline ne refusera jamais une requête).
      </small>
    </div>
  )
}

function StatsOverview({ stats }) {
  const pct = stats.max_daily_budget_eur > 0
    ? Math.min(100, (stats.today_cost_eur / stats.max_daily_budget_eur) * 100)
    : 0
  const pctClass = pct >= 95 ? 'bar--bad' : pct >= 80 ? 'bar--warn' : 'bar--good'

  return (
    <div className="stats-overview">
      <h3>Activité</h3>
      <div className="stats-grid">
        <Stat label="Aujourd'hui" value={`${stats.today_cost_eur.toFixed(2)}€ / ${stats.max_daily_budget_eur.toFixed(2)}€`} extra={`${stats.today_count} modèles`} />
        <Stat label="Ce mois" value={`${stats.month_cost_eur.toFixed(2)}€`} extra={`${stats.month_count} modèles`} />
        <Stat label="Total modèles" value={stats.total_count} />
        <Stat label="Taux d'approbation" value={stats.approval_rate != null ? `${(stats.approval_rate * 100).toFixed(0)}%` : '—'} extra={`${stats.approved_count} ok / ${stats.rejected_count} rejetés`} />
        <Stat label="Score moyen" value={stats.avg_score != null ? `${stats.avg_score.toFixed(1)} / 10` : '—'} />
        <Stat label="En attente" value={stats.pending_count} />
      </div>
      <div className={`bar ${pctClass}`}>
        <div className="bar__fill" style={{ width: `${pct}%` }} />
      </div>
      {stats.budget_exceeded && (
        <div className="error">Budget dépassé — le pipeline refuse toute nouvelle requête jusqu'à demain.</div>
      )}
    </div>
  )
}

function Stat({ label, value, extra }) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {extra && <div className="stat__extra muted">{extra}</div>}
    </div>
  )
}

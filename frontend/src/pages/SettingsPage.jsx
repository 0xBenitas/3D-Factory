import { useEffect, useMemo, useState } from 'react'
import {
  getSettings,
  getStats,
  listEngines,
  listImageEngines,
  listPrompts,
  listTemplates,
  resetPrompt,
  updatePrompt,
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

      <ApiKeysSection
        apiKeys={settings.api_keys || {}}
        onSave={save}
        disabled={saving}
      />

      <PromptsSection />

      {savedAt && <div className="settings-saved muted">✓ Enregistré</div>}

      {stats && <StatsOverview stats={stats} />}
    </section>
  )
}

// ---------------------------------------------------------------------- //
// API keys

// `prefix` et `minLen` servent à un pré-check côté client : on alerte mais
// on ne bloque PAS le submit (les API peuvent changer leur format sans
// nous prévenir — mieux vaut un faux positif avertissant qu'un rejet dur
// qui empêche de saisir une clé légitime).
const API_KEY_DEFS = [
  { name: 'anthropic', label: 'Anthropic (Claude)', placeholder: 'sk-ant-...', prefix: 'sk-ant-', minLen: 20 },
  { name: 'meshy',     label: 'Meshy',              placeholder: 'msy_...',    prefix: 'msy_',    minLen: 20 },
  { name: 'tripo',     label: 'Tripo',              placeholder: 'tsk_...',    prefix: 'tsk_',    minLen: 20 },
  { name: 'stability', label: 'Stability AI',       placeholder: 'sk-...',     prefix: 'sk-',     minLen: 20 },
]

function validateApiKey(def, draft) {
  if (!draft) return null
  const errors = []
  if (def.prefix && !draft.startsWith(def.prefix)) {
    errors.push(`commence normalement par "${def.prefix}"`)
  }
  if (def.minLen && draft.length < def.minLen) {
    errors.push(`au moins ${def.minLen} caractères (actuel : ${draft.length})`)
  }
  return errors.length > 0 ? errors.join(' ; ') : null
}

function ApiKeysSection({ apiKeys, onSave, disabled }) {
  return (
    <div className="stats-overview">
      <h3>Clés API</h3>
      <p className="muted">
        Laissez vide pour ne pas modifier. Effacer le champ et enregistrer supprime la clé.
      </p>
      <div className="settings-grid">
        {API_KEY_DEFS.map((def) => (
          <ApiKeyCard
            key={def.name}
            def={def}
            status={apiKeys[def.name] || { configured: false, masked: '' }}
            onSave={(value) => onSave({ [`api_key_${def.name}`]: value })}
            disabled={disabled}
          />
        ))}
      </div>
    </div>
  )
}

function ApiKeyCard({ def, status, onSave, disabled }) {
  const [draft, setDraft] = useState('')
  const [show, setShow] = useState(false)

  const formatWarning = validateApiKey(def, draft)

  const save = () => {
    onSave(draft)
    setDraft('')
    setShow(false)
  }
  const clear = () => {
    if (!confirm(`Supprimer la clé ${def.label} ?`)) return
    onSave('')
    setDraft('')
  }

  return (
    <div className="settings-card">
      <label className="settings-card__label">{def.label}</label>
      <div className="muted" style={{ marginBottom: 4 }}>
        {status.configured ? `Configurée : ${status.masked}` : 'Non configurée'}
      </div>
      <div className="settings-card__inline">
        <input
          type={show ? 'text' : 'password'}
          placeholder={def.placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled}
          autoComplete="off"
          aria-invalid={formatWarning ? 'true' : 'false'}
        />
        <button
          type="button"
          className="btn"
          onClick={() => setShow((s) => !s)}
          disabled={disabled || !draft}
        >
          {show ? 'Masquer' : 'Afficher'}
        </button>
      </div>
      {formatWarning && (
        <small className="muted" style={{ color: 'var(--warn)', marginTop: 4 }}>
          ⚠ Format inhabituel : {formatWarning}. L'enregistrement reste possible.
        </small>
      )}
      <div className="settings-card__inline" style={{ marginTop: 6 }}>
        <button
          className="btn btn--primary"
          onClick={save}
          disabled={disabled || !draft}
        >
          Enregistrer
        </button>
        {status.configured && (
          <button className="btn" onClick={clear} disabled={disabled}>
            Supprimer
          </button>
        )}
      </div>
    </div>
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

// ---------------------------------------------------------------------- //
// Prompts système — éditeur par brique (GET/PUT/DELETE /api/prompts)

function PromptsSection() {
  const [bricks, setBricks] = useState(null)
  const [maxLength, setMaxLength] = useState(8000)
  const [openId, setOpenId] = useState(null)
  const [error, setError] = useState(null)

  const reload = async () => {
    setError(null)
    try {
      const data = await listPrompts()
      setBricks(data.bricks || [])
      setMaxLength(data.max_length || 8000)
    } catch (exc) {
      setError(exc.detail || exc.message)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const onBrickUpdate = (updated) => {
    setBricks((curr) => (curr || []).map((b) => (b.id === updated.id ? updated : b)))
  }

  if (bricks === null) {
    return (
      <div className="stats-overview">
        <h3>Prompts système</h3>
        <p className="muted">Chargement…</p>
      </div>
    )
  }

  return (
    <div className="stats-overview">
      <h3>Prompts système</h3>
      <p className="muted">
        Édite le system prompt de chaque étape Claude. Laisse vide pour restaurer le défaut.
        Les modifications sont prises en compte immédiatement, sans redémarrer.
      </p>
      {error && <div className="error">{error}</div>}
      <div className="prompts-list" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {bricks.map((b) => (
          <PromptBrickRow
            key={b.id}
            brick={b}
            maxLength={maxLength}
            open={openId === b.id}
            onToggle={() => setOpenId(openId === b.id ? null : b.id)}
            onUpdate={onBrickUpdate}
            onError={setError}
          />
        ))}
      </div>
    </div>
  )
}

function PromptBrickRow({ brick, maxLength, open, onToggle, onUpdate, onError }) {
  const [draft, setDraft] = useState(brick.override)
  const [showDefault, setShowDefault] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setDraft(brick.override)
  }, [brick.override])

  const changed = draft !== brick.override
  const over = draft.length > maxLength

  const save = async () => {
    setBusy(true)
    onError(null)
    try {
      const updated = await updatePrompt(brick.id, draft)
      onUpdate(updated)
    } catch (exc) {
      onError(exc.detail || exc.message)
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    if (!confirm(`Restaurer le prompt par défaut de "${brick.label}" ?`)) return
    setBusy(true)
    onError(null)
    try {
      const updated = await resetPrompt(brick.id)
      onUpdate(updated)
    } catch (exc) {
      onError(exc.detail || exc.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="settings-card" style={{ padding: 12 }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          all: 'unset',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          width: '100%',
        }}
      >
        <div>
          <strong>{brick.label}</strong>
          {brick.is_custom && (
            <span className="muted" style={{ marginLeft: 8, fontSize: '0.8em' }}>
              • personnalisé
            </span>
          )}
        </div>
        <span className="muted">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div style={{ marginTop: 10 }}>
          <p className="muted" style={{ marginTop: 0 }}>{brick.description}</p>

          {brick.placeholders.length > 0 && (
            <p className="muted" style={{ marginTop: 0 }}>
              <strong>Placeholders obligatoires :</strong>{' '}
              {brick.placeholders.map((p) => `{${p}}`).join(', ')}
            </p>
          )}

          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={busy}
            rows={12}
            placeholder={`Laisse vide pour utiliser le défaut (${brick.default.length} chars).`}
            style={{
              width: '100%',
              fontFamily: 'ui-monospace, monospace',
              fontSize: '0.85rem',
              padding: '0.6rem',
              boxSizing: 'border-box',
              resize: 'vertical',
            }}
          />

          <div
            className="settings-card__inline"
            style={{ marginTop: 8, justifyContent: 'space-between' }}
          >
            <small className={over ? 'error' : 'muted'}>
              {draft.length} / {maxLength} caractères{over ? ' — dépassé' : ''}
            </small>
            <div className="settings-card__inline">
              {changed && (
                <button
                  className="btn"
                  onClick={() => setDraft(brick.override)}
                  disabled={busy}
                >
                  Annuler
                </button>
              )}
              {brick.is_custom && (
                <button className="btn" onClick={reset} disabled={busy}>
                  Reset défaut
                </button>
              )}
              <button
                className="btn btn--primary"
                onClick={save}
                disabled={busy || !changed || over}
              >
                Enregistrer
              </button>
            </div>
          </div>

          <div style={{ marginTop: 10 }}>
            <button
              type="button"
              className="btn"
              onClick={() => setShowDefault((v) => !v)}
            >
              {showDefault ? 'Masquer' : 'Afficher'} le prompt par défaut
            </button>
            {showDefault && (
              <pre
                style={{
                  marginTop: 8,
                  padding: 10,
                  background: 'rgba(127,127,127,0.08)',
                  borderRadius: 4,
                  fontSize: '0.78rem',
                  maxHeight: 300,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {brick.default}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

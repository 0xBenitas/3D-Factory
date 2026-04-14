import { useCallback, useEffect, useState } from 'react'
import PrintParams from './PrintParams.jsx'
import {
  generateExport,
  getExportListingUrl,
  getExportZipUrl,
  listExports,
  listTemplates,
} from '../api.js'

// SPECS §4.6 — visible uniquement quand validation === 'approved'.
// - Si aucun export : bouton "Générer export" (choix du template).
// - Si un export existe : affichage du dernier + boutons Copier/ZIP/Regénérer.
// - Pendant "photos"/"packing" : spinner + auto-refresh.
const RUNNING_STATUSES = new Set(['photos', 'packing'])

// Délai max (ms) avant de considérer qu'un POST /generate a échoué
// silencieusement (le pipeline_status n'est jamais passé en photos/packing).
// Au-delà, on retire l'état "démarrage" pour ne pas bloquer l'UI.
const START_WATCHDOG_MS = 15000

export default function ExportPanel({ model, onChanged }) {
  const [templates, setTemplates] = useState([])
  const [template, setTemplate] = useState('')
  const [exports_, setExports] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)
  // True entre le POST /generate réussi et la transition observée
  // pipeline_status → photos/packing (évite le "trou" de 3s où l'UI
  // affichait "Aucun export encore généré" avant le prochain poll).
  const [starting, setStarting] = useState(false)

  // Charge la liste des templates une fois au mount.
  useEffect(() => {
    let cancelled = false
    listTemplates()
      .then((list) => {
        if (cancelled) return
        setTemplates(list)
        if (list.length > 0) {
          setTemplate((prev) => prev || list[0].name)
        }
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.detail || exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const reloadExports = useCallback(async () => {
    try {
      const list = await listExports(model.id)
      setExports(list)
      setError(null)
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setLoading(false)
    }
  }, [model.id])

  useEffect(() => {
    reloadExports()
  }, [reloadExports])

  // Auto-refresh pendant que le pipeline export tourne.
  useEffect(() => {
    if (!RUNNING_STATUSES.has(model.pipeline_status)) return
    const t = setInterval(reloadExports, 3000)
    return () => clearInterval(t)
  }, [model.pipeline_status, reloadExports])

  const latest = exports_[0] || null
  const pipelineBusy = RUNNING_STATUSES.has(model.pipeline_status)

  // Dès qu'on observe la transition photos/packing (ou un nouvel export),
  // on peut retirer l'état de démarrage.
  useEffect(() => {
    if (starting && pipelineBusy) setStarting(false)
  }, [starting, pipelineBusy])

  const handleGenerate = async () => {
    if (!template) return
    setBusy(true)
    setError(null)
    try {
      await generateExport({ model_id: model.id, template })
      // Entre ce point et le prochain poll de ModelsPage (~3s), le
      // pipeline_status est encore sur sa valeur précédente ("pending"/
      // "done"). On affiche un état "démarrage" pour éviter le flash
      // "Aucun export encore généré".
      setStarting(true)
      // Watchdog : si la transition n'arrive jamais (échec silencieux du
      // background task), on débloque l'UI au bout de 15s.
      setTimeout(() => setStarting((s) => (s ? false : s)), START_WATCHDOG_MS)
      onChanged?.()
    } catch (exc) {
      setError(exc.detail || exc.message)
    } finally {
      setBusy(false)
    }
  }

  const handleCopyListing = async () => {
    if (!latest) return
    setError(null)
    try {
      const resp = await fetch(getExportListingUrl(latest.id), {
        credentials: 'same-origin',
      })
      if (!resp.ok) {
        throw new Error(`${resp.status} ${resp.statusText}`)
      }
      const text = await resp.text()
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (exc) {
      setError(exc.message || 'Copie impossible')
    }
  }

  return (
    <div className="export-panel">
      <div className="export-panel__header">
        <h3>Export marketplace</h3>
        <label className="export-panel__template">
          <span>Template</span>
          <select
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            disabled={busy || pipelineBusy || templates.length === 0}
          >
            {templates.length === 0 && <option value="">—</option>}
            {templates.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {pipelineBusy && (
        <div className="export-panel__running muted">
          {model.pipeline_status === 'photos'
            ? '📸 Génération des photos lifestyle…'
            : '📦 Assemblage du ZIP…'}
        </div>
      )}

      {!pipelineBusy && starting && (
        <div className="export-panel__running muted">
          ⚙️ Démarrage de l'export…
        </div>
      )}

      {!pipelineBusy && !starting && latest && (
        <div className="export-panel__result">
          <div className="export-panel__title">
            <strong>{latest.title || `Export #${latest.id}`}</strong>
            <span className="muted">
              Template : {latest.template}
              {latest.price_suggested > 0 && (
                <>  ·  Prix suggéré : {latest.price_suggested.toFixed(2)}€</>
              )}
            </span>
          </div>

          {latest.description && (
            <p className="export-panel__desc">{latest.description}</p>
          )}

          {latest.tags && latest.tags.length > 0 && (
            <div className="export-panel__tags">
              {latest.tags.map((t) => (
                <span key={t} className="chip chip--tag">
                  #{t}
                </span>
              ))}
            </div>
          )}

          <PrintParams params={latest.print_params} />

          <div className="export-panel__actions">
            <button className="btn" onClick={handleCopyListing}>
              {copied ? '✓ Copié' : '📋 Copier listing'}
            </button>
            <a
              href={getExportZipUrl(latest.id)}
              className="btn btn--primary"
              download
            >
              📥 Télécharger ZIP
            </a>
            <button
              className="btn"
              onClick={handleGenerate}
              disabled={busy || !template}
              title="Relance photos + SEO + ZIP"
            >
              🔄 Regénérer
            </button>
          </div>
        </div>
      )}

      {!pipelineBusy && !starting && !latest && !loading && (
        <div className="export-panel__empty">
          <p className="muted">Aucun export encore généré.</p>
          <button
            className="btn btn--primary"
            onClick={handleGenerate}
            disabled={busy || !template}
          >
            {busy ? 'Envoi…' : '🚀 Générer export'}
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}
    </div>
  )
}

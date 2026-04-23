import { useCallback, useEffect, useState } from 'react'
import PrintParams from './PrintParams.jsx'
import { useToast } from './Toast.jsx'
import {
  generateExport,
  getExportListingUrl,
  getExportZipUrl,
  listExports,
  listTemplates,
  patchExport,
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

// Copie dans le presse-papier avec fallback : `navigator.clipboard` n'est
// dispo qu'en contexte sécurisé (HTTPS ou localhost). En HTTP ou dans un
// iframe sandboxée on tombe sur une textarea temporaire + execCommand, qui
// marche partout même si officiellement déprécié.
async function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // permissions / contexte non sécurisé → fallback
    }
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.top = '0'
  ta.style.left = '0'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    const ok = document.execCommand('copy')
    if (!ok) throw new Error('execCommand copy refusé')
  } finally {
    document.body.removeChild(ta)
  }
}

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
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)  // { title, description, tags, price_suggested }
  const [savingEdit, setSavingEdit] = useState(false)
  const toast = useToast()

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

  const beginEdit = () => {
    if (!latest) return
    setDraft({
      title: latest.title || '',
      description: latest.description || '',
      tags: (latest.tags || []).join(', '),
      price_suggested: latest.price_suggested ?? 0,
    })
    setEditing(true)
    setError(null)
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraft(null)
  }

  const saveEdit = async () => {
    if (!latest || !draft) return
    setSavingEdit(true)
    setError(null)
    try {
      const patch = {
        title: draft.title.trim(),
        description: draft.description,
        tags: draft.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        price_suggested: Number(draft.price_suggested) || 0,
      }
      await patchExport(latest.id, patch)
      toast('Listing mis à jour', { type: 'success' })
      setEditing(false)
      setDraft(null)
      await reloadExports()
    } catch (exc) {
      const msg = exc.detail || exc.message || 'Sauvegarde échouée'
      setError(msg)
      toast(msg, { type: 'error' })
    } finally {
      setSavingEdit(false)
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
      // Le backend doit renvoyer du text/plain ; si un middleware ou un
      // proxy a substitué du JSON/HTML, on refuse plutôt que de coller
      // du contenu inattendu dans le presse-papier de l'utilisateur.
      const ctype = (resp.headers.get('content-type') || '').toLowerCase()
      if (!ctype.startsWith('text/plain')) {
        throw new Error(`Réponse inattendue du serveur (content-type: ${ctype || 'vide'})`)
      }
      const text = await resp.text()
      await copyToClipboard(text)
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

      {!pipelineBusy && !starting && latest && !editing && (
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
            <button className="btn" onClick={beginEdit} title="Éditer titre/desc/tags/prix sans appeler Claude (gratuit)">
              ✏️ Éditer
            </button>
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
              title="Relance photos + SEO + ZIP (coûte des crédits)"
            >
              🔄 Regénérer
            </button>
          </div>
        </div>
      )}

      {!pipelineBusy && !starting && latest && editing && draft && (
        <div className="export-panel__edit">
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            ✏️ Édition manuelle — gratuit, pas d'appel Claude. Le ZIP sera
            reconstruit avec les nouvelles valeurs.
          </div>
          <label>
            <span>Titre</span>
            <input
              type="text"
              value={draft.title}
              maxLength={200}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              disabled={savingEdit}
            />
          </label>
          <label>
            <span>Description</span>
            <textarea
              rows={5}
              value={draft.description}
              maxLength={5000}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              disabled={savingEdit}
            />
          </label>
          <label>
            <span>Tags (séparés par virgule)</span>
            <input
              type="text"
              value={draft.tags}
              onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
              disabled={savingEdit}
              placeholder="3D print, STL, decor, minimalist"
            />
          </label>
          <label>
            <span>Prix suggéré (€)</span>
            <input
              type="number"
              min="0"
              max="10000"
              step="0.01"
              value={draft.price_suggested}
              onChange={(e) => setDraft({ ...draft, price_suggested: e.target.value })}
              disabled={savingEdit}
              style={{ width: 120 }}
            />
          </label>
          <div className="export-panel__actions">
            <button
              className="btn btn--primary"
              onClick={saveEdit}
              disabled={savingEdit || !draft.title.trim()}
            >
              {savingEdit ? 'Sauvegarde…' : '✓ Enregistrer'}
            </button>
            <button className="btn" onClick={cancelEdit} disabled={savingEdit}>
              Annuler
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

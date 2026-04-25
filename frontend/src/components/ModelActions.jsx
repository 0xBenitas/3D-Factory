import { useEffect, useState } from 'react'
import { useToast } from './Toast.jsx'
import {
  createRecipe,
  regenerateModel,
  remeshModel,
  repairModel,
  suggestSmartRegen,
  validateModel,
} from '../api.js'

// SPECS §4.5 : approuver / regénérer / remesh / repair / rejeter.
// Chaque bouton ouvre un sous-formulaire inline pour confirmer.
export default function ModelActions({ model, onChanged }) {
  const [panel, setPanel] = useState(null)  // 'regen' | 'remesh' | 'repair' | 'reject' | null
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [prompt, setPrompt] = useState(model.optimized_prompt || '')
  const [polycount, setPolycount] = useState(30000)
  const [reason, setReason] = useState('')
  const [repairMode, setRepairMode] = useState('normalize')
  const [smartRationale, setSmartRationale] = useState(null)
  const [smartLoading, setSmartLoading] = useState(false)
  const [recipeName, setRecipeName] = useState('')
  const toast = useToast()

  // Resynchronise le formulaire quand on navigue vers un autre modèle ou
  // quand le modèle courant est rafraîchi après une regénération :
  // `useState(...)` ne capture la valeur qu'au premier render, donc sans ça
  // le champ resterait figé sur l'ancien prompt. Le panel et l'erreur sont
  // aussi réinitialisés pour éviter d'afficher un état périmé du précédent.
  useEffect(() => {
    setPrompt(model.optimized_prompt || '')
    setPanel(null)
    setError(null)
    setReason('')
    setSmartRationale(null)
    setRecipeName(`${model.category || 'Recette'} ${model.engine}`)
  }, [model.id, model.optimized_prompt, model.category, model.engine])

  const disabled =
    busy ||
    ['prompt', 'generating', 'repairing', 'scoring', 'photos', 'packing'].includes(
      model.pipeline_status,
    )

  const wrap = async (fn, successMsg) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      setPanel(null)
      if (successMsg) toast(successMsg, { type: 'success' })
      onChanged?.()
    } catch (exc) {
      const msg = exc.detail || exc.message
      setError(msg)
      toast(msg || 'Action échouée', { type: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const approve = () =>
    wrap(
      () => validateModel(model.id, 'approve'),
      `Modèle #${model.id} approuvé`,
    )

  const reject = () =>
    wrap(
      () => validateModel(model.id, 'reject', reason || null),
      `Modèle #${model.id} rejeté`,
    )

  const regenerate = () =>
    wrap(
      () => regenerateModel(model.id, prompt || null),
      `Regénération #${model.id} lancée`,
    )

  const remesh = () =>
    wrap(
      () => remeshModel(model.id, polycount),
      `Remesh #${model.id} lancé (${polycount.toLocaleString('fr')} faces)`,
    )

  const autoFix = () =>
    wrap(
      () => repairModel(model.id, 'auto'),
      `Auto-Fix #${model.id} lancé`,
    )

  const repairWithMode = () =>
    wrap(
      () => repairModel(model.id, repairMode),
      `Repair #${model.id} lancé (${repairMode})`,
    )

  const saveAsRecipe = () =>
    wrap(
      () =>
        createRecipe({
          name: recipeName.trim(),
          engine: model.engine,
          image_engine: model.image_engine || null,
          category: model.category || null,
          notes: `Créée à partir du modèle #${model.id}`,
        }),
      `Recette "${recipeName.trim()}" enregistrée`,
    )

  const fetchSmartSuggestion = async () => {
    setSmartLoading(true)
    setError(null)
    setSmartRationale(null)
    try {
      const s = await suggestSmartRegen(model.id)
      setPrompt(s.suggested_prompt)
      setSmartRationale(s.rationale)
      setPanel('regen')
      toast('Suggestion Claude prête — révise et confirme', { type: 'info' })
    } catch (exc) {
      const msg = exc.detail || exc.message
      setError(msg)
      toast(msg || 'Suggestion impossible', { type: 'error' })
    } finally {
      setSmartLoading(false)
    }
  }

  return (
    <div className="model-actions">
      <div className="model-actions__buttons">
        <button
          className="btn btn--success"
          onClick={approve}
          disabled={disabled || model.validation === 'approved'}
        >
          ✓ Approuver
        </button>
        <button
          className={`btn ${panel === 'regen' ? 'btn--active' : ''}`}
          onClick={() => {
            setPanel(panel === 'regen' ? null : 'regen')
            setSmartRationale(null)
          }}
          disabled={disabled}
        >
          ↻ Regénérer
        </button>
        <button
          className="btn"
          onClick={fetchSmartSuggestion}
          disabled={disabled || smartLoading || model.qc_score == null}
          title={model.qc_score == null ? 'Score requis pour suggérer un ajustement' : 'Claude analyse le score et propose un prompt ajusté'}
        >
          {smartLoading ? '🧠 Analyse…' : '🧠 Regen smart'}
        </button>
        <button
          className={`btn ${panel === 'remesh' ? 'btn--active' : ''}`}
          onClick={() => setPanel(panel === 'remesh' ? null : 'remesh')}
          disabled={disabled || !model.engine_task_id}
          title={!model.engine_task_id ? 'Pas de task_id disponible' : undefined}
        >
          🔧 Remesh
        </button>
        <button
          className="btn"
          onClick={autoFix}
          disabled={disabled || !model.glb_path}
          title={!model.glb_path ? 'GLB indisponible' : 'Repair auto (CPU local, gratuit)'}
        >
          🩹 Auto-Fix
        </button>
        <button
          className={`btn btn--ghost ${panel === 'repair' ? 'btn--active' : ''}`}
          onClick={() => setPanel(panel === 'repair' ? null : 'repair')}
          disabled={disabled || !model.glb_path}
          title="Modes manuels (normalize / fill_holes / hard)"
        >
          ⚙ Repair…
        </button>
        <button
          className={`btn ${panel === 'recipe' ? 'btn--active' : ''}`}
          onClick={() => setPanel(panel === 'recipe' ? null : 'recipe')}
          disabled={disabled}
          title="Sauvegarder engine + image_engine + category comme recette réutilisable"
        >
          💾 Recette
        </button>
        <button
          className={`btn btn--danger ${panel === 'reject' ? 'btn--active' : ''}`}
          onClick={() => setPanel(panel === 'reject' ? null : 'reject')}
          disabled={disabled || model.validation === 'rejected'}
        >
          ✕ Rejeter
        </button>
      </div>

      {panel === 'regen' && (
        <div className="model-actions__panel">
          {smartRationale && (
            <div className="smart-rationale" title="Justification Claude">
              🧠 <em>{smartRationale}</em>
            </div>
          )}
          <label>
            <span>Prompt (modifiable, vide = ré-optimiser depuis l'input)</span>
            <textarea
              rows={4}
              value={prompt}
              maxLength={5000}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </label>
          <button className="btn btn--primary" onClick={regenerate} disabled={busy}>
            {busy ? 'Envoi…' : 'Confirmer regénération'}
          </button>
        </div>
      )}

      {panel === 'remesh' && (
        <div className="model-actions__panel">
          <label>
            <span>Target polycount ({polycount.toLocaleString('fr')} faces)</span>
            <input
              type="range"
              min={2000}
              max={100000}
              step={1000}
              value={polycount}
              onChange={(e) => setPolycount(Number(e.target.value))}
            />
          </label>
          <button className="btn btn--primary" onClick={remesh} disabled={busy}>
            {busy ? 'Envoi…' : 'Confirmer remesh'}
          </button>
        </div>
      )}

      {panel === 'repair' && (
        <div className="model-actions__panel">
          <label>
            <span>Mode de repair</span>
            <select value={repairMode} onChange={(e) => setRepairMode(e.target.value)}>
              <option value="normalize">normalize — merge vertices + normales</option>
              <option value="fill_holes">fill_holes — ferme les petits trous</option>
              <option value="hard">hard — pymeshfix forcé (peut distordre)</option>
            </select>
          </label>
          <p className="muted">Aucun appel API externe — recalcule juste localement.</p>
          <button className="btn btn--primary" onClick={repairWithMode} disabled={busy}>
            {busy ? 'Envoi…' : `Confirmer ${repairMode}`}
          </button>
        </div>
      )}

      {panel === 'recipe' && (
        <div className="model-actions__panel">
          <label>
            <span>Nom de la recette</span>
            <input
              type="text"
              value={recipeName}
              maxLength={120}
              onChange={(e) => setRecipeName(e.target.value)}
            />
          </label>
          <p className="muted" style={{ margin: '4px 0', fontSize: '0.8em' }}>
            Capture : engine = <strong>{model.engine}</strong>
            {model.image_engine ? <>, image_engine = <strong>{model.image_engine}</strong></> : ''}
            {model.category ? <>, category = <strong>{model.category}</strong></> : ''}
          </p>
          <button
            className="btn btn--primary"
            onClick={saveAsRecipe}
            disabled={busy || !recipeName.trim()}
          >
            {busy ? 'Envoi…' : 'Enregistrer la recette'}
          </button>
        </div>
      )}

      {panel === 'reject' && (
        <div className="model-actions__panel">
          <label>
            <span>Raison (optionnelle, stockée pour apprentissage)</span>
            <input
              type="text"
              value={reason}
              maxLength={2000}
              onChange={(e) => setReason(e.target.value)}
              placeholder="ex: proportions ratées, détails illisibles…"
            />
          </label>
          <button className="btn btn--danger" onClick={reject} disabled={busy}>
            {busy ? 'Envoi…' : 'Confirmer rejet'}
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useToast } from './Toast.jsx'
import { regenerateModel, remeshModel, validateModel } from '../api.js'

// SPECS §4.5 : approuver / regénérer / remesh / rejeter.
// Chaque bouton ouvre un sous-formulaire inline pour confirmer.
export default function ModelActions({ model, onChanged }) {
  const [panel, setPanel] = useState(null)  // 'regen' | 'remesh' | 'reject' | null
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [prompt, setPrompt] = useState(model.optimized_prompt || '')
  const [polycount, setPolycount] = useState(30000)
  const [reason, setReason] = useState('')
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
  }, [model.id, model.optimized_prompt])

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
          onClick={() => setPanel(panel === 'regen' ? null : 'regen')}
          disabled={disabled}
        >
          ↻ Regénérer
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
          className={`btn btn--danger ${panel === 'reject' ? 'btn--active' : ''}`}
          onClick={() => setPanel(panel === 'reject' ? null : 'reject')}
          disabled={disabled || model.validation === 'rejected'}
        >
          ✕ Rejeter
        </button>
      </div>

      {panel === 'regen' && (
        <div className="model-actions__panel">
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

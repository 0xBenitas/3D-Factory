import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useToast } from '../components/Toast.jsx'
import {
  cancelBatch,
  createBatch,
  getBatch,
  listBatches,
  listRecipes,
} from '../api.js'

// Page Batch (Phase 1.9). Crée un job batch (recette + liste de prompts +
// budget cap) puis poll son état toutes les 3s.
export default function BatchPage() {
  const [recipes, setRecipes] = useState([])
  const [batches, setBatches] = useState([])
  const [recipeId, setRecipeId] = useState('')
  const [promptsRaw, setPromptsRaw] = useState('')
  const [budget, setBudget] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const toast = useToast()

  const promptsList = useMemo(
    () => promptsRaw.split('\n').map((s) => s.trim()).filter(Boolean),
    [promptsRaw],
  )

  useEffect(() => {
    let cancelled = false
    listRecipes()
      .then((rs) => { if (!cancelled) setRecipes(rs || []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // Polling de la liste des batches (3s)
  useEffect(() => {
    let cancelled = false
    let timer = null
    const fetchAll = async () => {
      try {
        const data = await listBatches()
        if (!cancelled) setBatches(data || [])
      } catch (exc) {
        if (!cancelled) toast(exc.detail || exc.message, { type: 'error' })
      }
    }
    fetchAll()
    timer = setInterval(fetchAll, 3000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [toast])

  // Polling du détail du batch sélectionné (3s)
  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    let timer = null
    const fetchDetail = async () => {
      try {
        const d = await getBatch(selectedId)
        if (!cancelled) setDetail(d)
      } catch (exc) {
        if (!cancelled) toast(exc.detail || exc.message, { type: 'error' })
      }
    }
    fetchDetail()
    timer = setInterval(fetchDetail, 3000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [selectedId, toast])

  const submit = async (e) => {
    e.preventDefault()
    if (!recipeId || promptsList.length === 0) return
    setBusy(true)
    try {
      const b = await createBatch({
        recipe_id: Number(recipeId),
        prompts: promptsList,
        max_budget_eur: budget ? Number(budget) : null,
      })
      toast(`Batch #${b.id} lancé (${b.total} items)`, { type: 'success' })
      setPromptsRaw('')
      setBudget('')
      setSelectedId(b.id)
    } catch (exc) {
      toast(exc.detail || exc.message || 'Échec de la création', { type: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const onCancel = async (id) => {
    if (!confirm(`Annuler le batch #${id} ? Les items en cours finissent, les suivants sont skipped.`)) return
    try {
      await cancelBatch(id)
      toast(`Batch #${id} : annulation demandée`, { type: 'info' })
    } catch (exc) {
      toast(exc.detail || exc.message, { type: 'error' })
    }
  }

  return (
    <section className="batch-page">
      <h2>Batch</h2>
      <p className="muted">
        Lance N générations en série avec une recette commune. Coûts plafonnés par budget.
      </p>

      <form onSubmit={submit} className="batch-form">
        <label className="input-form__field">
          <span>Recette *</span>
          <select
            value={recipeId}
            onChange={(e) => setRecipeId(e.target.value)}
            disabled={busy}
            required
          >
            <option value="">— Choisis une recette —</option>
            {recipes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} {r.category ? `(${r.category})` : ''} · {r.engine}
              </option>
            ))}
          </select>
          {recipes.length === 0 && (
            <small className="muted">
              Aucune recette — crée-en une depuis la page d'un modèle (bouton 💾 Recette).
            </small>
          )}
        </label>

        <label className="input-form__field">
          <span>Prompts (1 par ligne, max 200)</span>
          <textarea
            rows={8}
            value={promptsRaw}
            onChange={(e) => setPromptsRaw(e.target.value)}
            disabled={busy}
            placeholder={'dragon avec ailes déployées\nstatuette zen\nporte-clé en forme de chat\n...'}
          />
          <small className="muted">{promptsList.length} prompt(s) détecté(s)</small>
        </label>

        <label className="input-form__field">
          <span>Budget cap (EUR, optionnel) — stoppe le batch quand atteint</span>
          <input
            type="number"
            min="0"
            step="0.5"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            disabled={busy}
            placeholder="ex: 5"
          />
        </label>

        <button
          type="submit"
          className="btn btn--primary"
          disabled={busy || !recipeId || promptsList.length === 0}
        >
          {busy ? 'Création…' : `🚀 Lancer le batch (${promptsList.length} items)`}
        </button>
      </form>

      <h3 style={{ marginTop: '2rem' }}>Batches récents</h3>
      {batches.length === 0 ? (
        <p className="muted">Aucun batch pour l'instant.</p>
      ) : (
        <ul className="batch-list">
          {batches.map((b) => (
            <li
              key={b.id}
              className={`batch-list__item ${selectedId === b.id ? 'batch-list__item--active' : ''}`}
              onClick={() => setSelectedId(b.id === selectedId ? null : b.id)}
            >
              <div className="batch-list__row">
                <strong>#{b.id}</strong>
                <span className={`batch-status batch-status--${b.status}`}>{b.status}</span>
                <span className="muted">{b.recipe_name || '?'}</span>
                <span>{b.done}/{b.total} ✓ · {b.failed} ✕</span>
                <span className="muted">{b.spent_eur.toFixed(2)}€{b.max_budget_eur ? ` / ${b.max_budget_eur.toFixed(2)}€` : ''}</span>
                {(b.status === 'pending' || b.status === 'running') && !b.cancel_requested && (
                  <button
                    className="btn btn--ghost"
                    onClick={(e) => { e.stopPropagation(); onCancel(b.id) }}
                  >
                    Annuler
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {detail && selectedId && (
        <div className="batch-detail">
          <h4>Batch #{detail.id} — items</h4>
          <ul className="batch-items">
            {detail.items.map((it) => (
              <li key={it.id} className={`batch-item batch-item--${it.status}`}>
                <span className="batch-item__pos">#{it.position + 1}</span>
                <span className={`batch-status batch-status--${it.status}`}>{it.status}</span>
                <span className="batch-item__prompt" title={it.prompt}>{it.prompt}</span>
                {it.model_id && (
                  <Link to={`/models?focus=${it.model_id}`} className="muted">model #{it.model_id}</Link>
                )}
                {it.error && <span className="error">{it.error}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

import { useCallback, useState } from 'react'
import CostTracker from '../components/CostTracker.jsx'
import InputForm from '../components/InputForm.jsx'
import PipelineTracker from '../components/PipelineTracker.jsx'
import { startPipeline } from '../api.js'

// SPECS §"Frontend — 3 pages / CreatePage".
// Deux états : (1) formulaire vide, (2) tracker polling du model_id.
// Le CostTracker remonte son état pour que le bouton "Générer" soit
// disabled préventivement quand le budget est dépassé (évite le 429).
export default function CreatePage() {
  const [currentId, setCurrentId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [budgetInfo, setBudgetInfo] = useState(null)

  const handleSubmit = async (payload) => {
    setBusy(true)
    try {
      const res = await startPipeline(payload)
      setCurrentId(res.model_id)
    } finally {
      setBusy(false)
    }
  }

  const handleStats = useCallback((stats) => {
    setBudgetInfo(
      stats.budget_exceeded
        ? `Budget du jour atteint (${stats.today_cost_eur.toFixed(2)}€ / ${stats.max_daily_budget_eur.toFixed(2)}€). Modifiable dans Settings.`
        : null,
    )
  }, [])

  return (
    <section className="page create-page">
      <div className="page__header">
        <h2>Create</h2>
        <p className="muted">Texte ou photo → .stl imprimable + score.</p>
      </div>

      {currentId === null ? (
        <InputForm
          onSubmit={handleSubmit}
          busy={busy}
          disabledReason={budgetInfo}
        />
      ) : (
        <>
          <PipelineTracker modelId={currentId} />
          <div className="page__footer">
            <button
              className="btn"
              onClick={() => setCurrentId(null)}
            >
              ← Générer un autre modèle
            </button>
          </div>
        </>
      )}

      <CostTracker boost={currentId !== null} onStats={handleStats} />
    </section>
  )
}

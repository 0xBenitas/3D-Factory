import { useEffect, useState } from 'react'
import { getStats } from '../api.js'

// SPECS §4.7 CostTracker — bandeau en bas de CreatePage.
// Refresh toutes les 30s (SPECS). Ici on est plus agressif pendant qu'un
// pipeline tourne (via la prop `boost`), 5s, pour voir le coût monter en
// temps réel. Le parent peut observer l'état via `onStats` (appelé à
// chaque refresh réussi) pour griser préventivement le bouton "Générer".

export default function CostTracker({ boost = false, onStats = null }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    let timer = null

    const load = async () => {
      try {
        const s = await getStats()
        if (!cancelled) {
          setStats(s)
          setError(null)
          onStats?.(s)
        }
      } catch (exc) {
        if (!cancelled) setError(exc.detail || exc.message)
      }
    }

    load()
    timer = setInterval(load, boost ? 5000 : 30000)
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
    // onStats est volontairement hors deps : on ne veut pas relancer le
    // polling si le parent change sa référence de callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boost])

  if (error) return <div className="cost-tracker cost-tracker--error">💰 {error}</div>
  if (!stats) return null

  const {
    today_cost_eur,
    max_daily_budget_eur,
    today_count,
    budget_exceeded,
    budget_disabled,
  } = stats
  const budgetEnabled = !budget_disabled && max_daily_budget_eur > 0
  const pct = budgetEnabled
    ? Math.min(100, (today_cost_eur / max_daily_budget_eur) * 100)
    : 0
  const pctClass = !budgetEnabled
    ? 'bar--muted'
    : pct >= 95
    ? 'bar--bad'
    : pct >= 80
    ? 'bar--warn'
    : 'bar--good'

  return (
    <div className={`cost-tracker ${budget_exceeded ? 'cost-tracker--over' : ''}`}>
      <div className="cost-tracker__row">
        <span>
          💰 Aujourd'hui : <strong>{today_cost_eur.toFixed(2)}€</strong>
          {budgetEnabled && <> / {max_daily_budget_eur.toFixed(2)}€</>}
        </span>
        <span className="muted">{today_count} modèle{today_count > 1 ? 's' : ''}</span>
      </div>
      <div className={`bar ${pctClass}`}>
        <div className="bar__fill" style={{ width: `${pct}%` }} />
      </div>
      {budget_disabled && (
        <div className="cost-tracker__warn">
          ⚠️ Plafond journalier désactivé (max_daily_budget_eur ≤ 0). Définis une valeur
          positive dans Settings pour limiter les dépenses API.
        </div>
      )}
      {budget_exceeded && (
        <div className="cost-tracker__warn">
          Budget dépassé — le pipeline refuse toute nouvelle requête jusqu'à demain.
        </div>
      )}
    </div>
  )
}

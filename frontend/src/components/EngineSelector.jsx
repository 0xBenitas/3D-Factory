import { useEffect, useState } from 'react'
import { listEngines } from '../api.js'

// Dropdown moteur 3D. Fait un GET /api/engines au premier mount et reste
// contrôlé par le parent via value/onChange.
// Phase 5 : ajoutera un second dropdown "moteur image" — pour l'instant on
// garde stability en dur via les settings backend.
export default function EngineSelector({ value, onChange, disabled = false }) {
  const [engines, setEngines] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    listEngines()
      .then((list) => {
        if (cancelled) return
        setEngines(list)
        // Sélection par défaut : premier moteur dispo si rien n'est choisi.
        if (!value && list.length > 0) onChange(list[0].name)
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.detail || exc.message)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) return <span className="muted">Chargement moteurs…</span>
  if (error) return <span className="error">Moteurs indisponibles : {error}</span>

  return (
    <label className="engine-selector">
      <span>Moteur 3D</span>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || engines.length === 0}
      >
        {engines.map((e) => (
          <option key={e.name} value={e.name}>
            {e.name}
            {e.supports_image ? ' (texte + image)' : ' (texte)'}
          </option>
        ))}
      </select>
    </label>
  )
}

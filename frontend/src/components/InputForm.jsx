import { useEffect, useState } from 'react'
import EngineSelector from './EngineSelector.jsx'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const ACCEPTED_MIMES = ['image/jpeg', 'image/png']

// Coûts approximatifs (cohérents avec backend/costs.py). Juste un hint UI,
// la valeur réelle est calculée côté serveur et affichée dans le CostTracker.
const COST_GEN_EUR = 0.11       // prompt (~0,003) + meshy preview (~0,10) + scoring (~0,005)
const COST_EXPORT_EUR = 0.10    // lifestyle + 3×stability + listing + print_params

// InputForm — textarea OU drop image + EngineSelector + bouton Go.
// SPECS §4.1 :
// - Si texte + image : le texte est prioritaire (image ignorée)
// - Disabled si aucun des deux
// - Validation client : jpeg/png, max 5MB
// - Disabled si `disabledReason` fourni (ex: budget dépassé)
export default function InputForm({ onSubmit, busy = false, disabledReason = null }) {
  const [text, setText] = useState('')
  const [imageFile, setImageFile] = useState(null)
  const [imagePreview, setImagePreview] = useState(null)
  const [engine, setEngine] = useState('')
  const [error, setError] = useState(null)

  // Libère l'URL object lors du changement d'image.
  useEffect(() => {
    if (!imageFile) {
      setImagePreview(null)
      return
    }
    const url = URL.createObjectURL(imageFile)
    setImagePreview(url)
    return () => URL.revokeObjectURL(url)
  }, [imageFile])

  const handleFile = (file) => {
    setError(null)
    if (!file) {
      setImageFile(null)
      return
    }
    if (!ACCEPTED_MIMES.includes(file.type)) {
      setError('Format refusé : JPEG ou PNG uniquement.')
      return
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setError(`Image trop grande (${(file.size / 1024 / 1024).toFixed(1)} Mo) — max 5 Mo.`)
      return
    }
    setImageFile(file)
  }

  const canSubmit =
    !busy &&
    !disabledReason &&
    engine &&
    (text.trim().length > 0 || imageFile !== null)

  const fileToDataUrl = (file) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!canSubmit) return
    setError(null)
    try {
      // SPECS §4.1 : texte prioritaire si les deux sont remplis.
      const usingText = text.trim().length > 0
      const payload = {
        engine,
        input_text: usingText ? text.trim() : null,
        input_image: usingText ? null : await fileToDataUrl(imageFile),
      }
      await onSubmit(payload)
    } catch (exc) {
      setError(exc.detail || exc.message || 'Erreur inconnue')
    }
  }

  return (
    <form className="input-form" onSubmit={handleSubmit}>
      <label className="input-form__field">
        <span>Description (texte)</span>
        <textarea
          rows={3}
          placeholder="Décris l'objet : pot de plante géométrique, figurine dragon, support téléphone..."
          value={text}
          maxLength={5000}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
        />
      </label>

      <div className="input-form__or">— OU —</div>

      <label className="input-form__drop">
        <input
          type="file"
          accept="image/jpeg,image/png"
          onChange={(e) => handleFile(e.target.files?.[0] || null)}
          disabled={busy}
        />
        {imagePreview ? (
          <img src={imagePreview} alt="preview" className="input-form__preview" />
        ) : (
          <span className="muted">
            📷 Clique pour uploader une photo (JPEG/PNG, max 5 Mo)
          </span>
        )}
      </label>

      <div className="input-form__controls">
        <EngineSelector value={engine} onChange={setEngine} disabled={busy || !!disabledReason} />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={!canSubmit}
          title={disabledReason || undefined}
        >
          {busy ? 'Envoi…' : '🚀 Générer'}
        </button>
      </div>

      <div className="input-form__hint muted">
        Coût estimé : <strong>~{COST_GEN_EUR.toFixed(2)}€</strong> pour la génération
        {' '}· <strong>+{COST_EXPORT_EUR.toFixed(2)}€</strong> si tu valides et exportes.
      </div>

      {disabledReason && <div className="error">{disabledReason}</div>}
      {error && <div className="error">{error}</div>}
    </form>
  )
}

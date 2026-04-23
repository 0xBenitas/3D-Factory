import { useEffect, useState } from 'react'
import EngineSelector from './EngineSelector.jsx'
import { getCostHints } from '../api.js'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const ACCEPTED_MIMES = ['image/jpeg', 'image/png']

// Fallback si l'appel `/api/costs/hints` échoue (réseau, déploiement partiel).
// Ces valeurs doivent rester cohérentes avec `backend/costs.py` — elles ne
// servent que si le backend est inaccessible, donc pas dramatique si elles
// dérivent un peu.
const FALLBACK_COST_GEN = 0.11
const FALLBACK_COST_EXPORT = 0.10

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
  const [costHints, setCostHints] = useState(null)

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

  // Coûts dynamiques depuis le backend (évite la dérive avec costs.py).
  // En cas d'échec on garde les fallbacks — le formulaire reste utilisable.
  useEffect(() => {
    let cancelled = false
    getCostHints()
      .then((h) => { if (!cancelled) setCostHints(h) })
      .catch(() => { /* fallbacks utilisés */ })
    return () => { cancelled = true }
  }, [])

  const costGen = costHints?.generation_eur ?? FALLBACK_COST_GEN
  const costExport = costHints?.export_eur ?? FALLBACK_COST_EXPORT

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
        Coût estimé : <strong>~{costGen.toFixed(2)}€</strong> pour la génération
        {' '}· <strong>+{costExport.toFixed(2)}€</strong> si tu valides et exportes.
      </div>

      {disabledReason && <div className="error">{disabledReason}</div>}
      {error && <div className="error">{error}</div>}
    </form>
  )
}

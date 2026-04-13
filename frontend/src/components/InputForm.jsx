import { useEffect, useState } from 'react'
import EngineSelector from './EngineSelector.jsx'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const ACCEPTED_MIMES = ['image/jpeg', 'image/png']

// InputForm — textarea OU drop image + EngineSelector + bouton Go.
// SPECS §4.1 :
// - Si texte + image : le texte est prioritaire (image ignorée)
// - Disabled si aucun des deux
// - Validation client : jpeg/png, max 5MB
export default function InputForm({ onSubmit, busy = false }) {
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
    !busy && engine && (text.trim().length > 0 || imageFile !== null)

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
        <EngineSelector value={engine} onChange={setEngine} disabled={busy} />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={!canSubmit}
        >
          {busy ? 'Envoi…' : '🚀 Générer'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}
    </form>
  )
}

import { useState } from 'react'
import { scoreClass } from '../utils/score.js'
import { getThumbUrl } from '../api.js'

// SPECS §4 : carte dans la grille de ModelsPage.
// Thumbnail 256×256 généré post-REPAIR → dispo dès le statut "pending".
// Si le thumb n'existe pas encore (pipeline en cours, modèle legacy), on
// bascule sur un placeholder textuel plutôt que de montrer un 404 cassé.

const VALIDATION_LABELS = {
  pending: 'En attente',
  approved: 'Approuvé',
  rejected: 'Rejeté',
}

const PIPELINE_LABELS = {
  prompt: 'Prompt…',
  generating: 'Génération…',
  repairing: 'Repair…',
  scoring: 'Score…',
  pending: 'Prêt pour validation',
  photos: 'Photos…',
  packing: 'Export…',
  done: 'Terminé',
  failed: 'Échec',
}

export default function ModelCard({ model, selected = false, onClick }) {
  const [thumbFailed, setThumbFailed] = useState(false)

  const isPending = ['prompt', 'generating', 'repairing', 'scoring'].includes(
    model.pipeline_status,
  )
  const isFailed = model.pipeline_status === 'failed'
  const canHaveThumb = !['prompt', 'generating', 'repairing', 'failed'].includes(
    model.pipeline_status,
  )
  const title =
    model.input_text ||
    (model.input_type === 'image' ? 'Depuis photo' : 'Modèle')

  return (
    <button
      type="button"
      className={`model-card ${selected ? 'model-card--selected' : ''}`}
      onClick={onClick}
    >
      <div className="model-card__thumb">
        {canHaveThumb && !thumbFailed ? (
          <img
            src={getThumbUrl(model.id)}
            alt={`Aperçu du modèle #${model.id}`}
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span className="model-card__thumb-placeholder" aria-hidden="true">
            {isFailed ? '✕' : isPending ? '⋯' : '◐'}
          </span>
        )}
      </div>
      <div className="model-card__body">
        <div className="model-card__header">
          <span className="model-card__id">#{model.id}</span>
          <span className={`chip chip--${model.validation}`}>
            {VALIDATION_LABELS[model.validation] || model.validation}
          </span>
        </div>

        <div className="model-card__title">{title}</div>

        <div className="model-card__meta">
          <span className="muted">{model.engine}</span>
          <span className={`score-pill ${scoreClass(model.qc_score)}`}>
            {model.qc_score != null ? `${model.qc_score.toFixed(1)} / 10` : '—'}
          </span>
        </div>

        <div
          className={`model-card__status ${
            isPending ? 'model-card__status--running' :
            isFailed ? 'model-card__status--failed' : ''
          }`}
        >
          {PIPELINE_LABELS[model.pipeline_status] || model.pipeline_status}
        </div>
      </div>
    </button>
  )
}

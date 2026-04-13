// SPECS §4 : miniature dans la grille de ModelsPage.
// Pas de thumbnail à ce stade (Phase 4 ajoutera les screenshots) — on
// montre un bloc texte riche + status/score.

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

function scoreClass(score) {
  if (score == null) return 'score--muted'
  if (score < 4) return 'score--bad'
  if (score < 6) return 'score--warn'
  return 'score--good'
}

export default function ModelCard({ model, selected = false, onClick }) {
  const isPending = ['prompt', 'generating', 'repairing', 'scoring'].includes(
    model.pipeline_status,
  )
  const isFailed = model.pipeline_status === 'failed'
  const title =
    model.input_text ||
    (model.input_type === 'image' ? 'Depuis photo' : 'Modèle')
  return (
    <button
      type="button"
      className={`model-card ${selected ? 'model-card--selected' : ''}`}
      onClick={onClick}
    >
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
    </button>
  )
}

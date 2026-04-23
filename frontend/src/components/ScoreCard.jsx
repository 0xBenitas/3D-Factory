import { scoreClass } from '../utils/score.js'

// SPECS §4.4 : carte score + métriques mesh brutes.
// Les métriques sont TOUJOURS affichées même si le score Claude est null.

function metricBadge(value, thresholds, unit = '') {
  // thresholds = { good: v=>bool, warn: v=>bool }. Par défaut ok.
  if (value === null || value === undefined) {
    return { icon: '?', cls: 'metric--muted', text: `${unit}—` }
  }
  const { good, warn } = thresholds
  if (good(value)) return { icon: '✓', cls: 'metric--good',  text: String(value) + unit }
  if (warn && warn(value)) return { icon: '!', cls: 'metric--warn', text: String(value) + unit }
  return { icon: '✕', cls: 'metric--bad', text: String(value) + unit }
}

export default function ScoreCard({ score, meshMetrics, qcDetails }) {
  const hasScore = score !== null && score !== undefined
  const summary = qcDetails?.summary
  const m = meshMetrics || {}

  // Règles de badge alignées avec SPECS §1.3 et §4.4.
  const manifold = {
    icon: m.is_manifold ? '✓' : '✕',
    cls: m.is_manifold ? 'metric--good' : 'metric--bad',
    text: m.is_manifold ? 'OK' : `${m.non_manifold_edges ?? '?'} arêtes bizarres`,
  }
  const watertight = {
    icon: m.is_watertight ? '✓' : '✕',
    cls: m.is_watertight ? 'metric--good' : 'metric--bad',
    text: m.is_watertight ? 'OK' : 'Fuite',
  }
  const thickness = metricBadge(
    m.min_wall_thickness_mm,
    { good: (v) => v >= 1.5, warn: (v) => v >= 0.8 },
    'mm',
  )
  const overhang = metricBadge(
    m.max_overhang_angle_deg,
    { good: (v) => v <= 45, warn: (v) => v <= 60 },
    '°',
  )
  const components = {
    icon: m.connected_components === 1 ? '✓' : '✕',
    cls: m.connected_components === 1 ? 'metric--good' : 'metric--bad',
    text: `${m.connected_components ?? '?'} composant${m.connected_components > 1 ? 's' : ''}`,
  }
  const degenerate = {
    icon: m.has_degenerate_faces ? '✕' : '✓',
    cls: m.has_degenerate_faces ? 'metric--bad' : 'metric--good',
    text: `${m.degenerate_face_count ?? 0} dégénérées`,
  }
  const faces = metricBadge(
    m.face_count,
    { good: (v) => v <= 50000, warn: (v) => v <= 100000 },
    ' faces',
  )
  const bbox = m.bounding_box_mm
    ? `${m.bounding_box_mm.map((x) => x.toFixed(0)).join('×')} mm`
    : '—'

  return (
    <div className="score-card">
      <div className={`score-card__score ${scoreClass(score)}`}>
        {hasScore ? (
          <>
            <span className="score-card__value">{score.toFixed(1)}</span>
            <span className="score-card__max"> / 10</span>
            <div className="score-bar">
              <div
                className="score-bar__fill"
                style={{ width: `${Math.min(100, Math.max(0, (score / 10) * 100))}%` }}
              />
            </div>
          </>
        ) : (
          <span className="muted">Score indisponible</span>
        )}
      </div>

      <ul className="score-card__metrics">
        <MetricRow label="Manifold"       badge={manifold} />
        <MetricRow label="Watertight"     badge={watertight} />
        <MetricRow label="Épaisseur min"  badge={thickness} />
        <MetricRow label="Surplomb max"   badge={overhang} />
        <MetricRow label="Composants"     badge={components} />
        <MetricRow label="Dégénérées"     badge={degenerate} />
        <MetricRow label="Faces"          badge={faces} />
        <MetricRow label="Dimensions"     badge={{ icon: 'ℹ', cls: 'metric--muted', text: bbox }} />
      </ul>

      {summary && <p className="score-card__summary">💬 {summary}</p>}
    </div>
  )
}

function MetricRow({ label, badge }) {
  return (
    <li className={`metric ${badge.cls}`}>
      <span className="metric__icon">{badge.icon}</span>
      <span className="metric__label">{label}</span>
      <span className="metric__value">{badge.text}</span>
    </li>
  )
}

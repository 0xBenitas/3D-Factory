// SPECS §4 — affiche les paramètres d'impression recommandés par Claude.
// Toutes les clés sont optionnelles : une valeur manquante est simplement
// masquée (pas de "—" moche dans l'UI).

export default function PrintParams({ params }) {
  if (!params || Object.keys(params).length === 0) return null

  const {
    layer_height_mm,
    infill_percent,
    supports_needed,
    support_notes,
    nozzle_diameter_mm,
    material_recommended,
    estimated_print_time_h,
    estimated_material_g,
    orientation_tip,
    difficulty,
  } = params

  return (
    <div className="print-params">
      <h4 className="print-params__title">Paramètres d'impression</h4>
      <ul className="print-params__list">
        <Row label="Couche" value={numUnit(layer_height_mm, 'mm')} />
        <Row label="Infill" value={numUnit(infill_percent, '%')} />
        <Row
          label="Supports"
          value={
            supports_needed == null
              ? null
              : supports_needed
              ? `oui${support_notes && support_notes !== '—' ? ` (${support_notes})` : ''}`
              : 'non'
          }
        />
        <Row label="Buse" value={numUnit(nozzle_diameter_mm, 'mm')} />
        <Row label="Matériau" value={sanitize(material_recommended)} />
        <Row label="Temps estimé" value={numUnit(estimated_print_time_h, ' h')} />
        <Row label="Matière" value={numUnit(estimated_material_g, ' g', '~')} />
        <Row label="Orientation" value={sanitize(orientation_tip)} />
        <Row label="Difficulté" value={sanitize(difficulty)} />
      </ul>
    </div>
  )
}

function Row({ label, value }) {
  if (value == null || value === '' || value === '—') return null
  return (
    <li className="print-params__row">
      <span className="print-params__label">{label}</span>
      <span className="print-params__value">{value}</span>
    </li>
  )
}

function numUnit(value, unit, prefix = '') {
  if (value == null || value === '') return null
  return `${prefix}${value}${unit}`
}

function sanitize(s) {
  if (s == null) return null
  const str = String(s).trim()
  if (!str || str === '—') return null
  return str
}

// Classe CSS pour un score 0-10 (ou null). Partagée entre ScoreCard et
// ModelCard — l'ancienne duplication à deux endroits divergeait facilement
// au premier changement de seuil.
export function scoreClass(score) {
  if (score == null) return 'score--muted'
  if (score < 4) return 'score--bad'
  if (score < 6) return 'score--warn'
  return 'score--good'
}

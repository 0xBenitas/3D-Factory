import { useEffect, useRef } from 'react'

// Hook unifié pour les polls périodiques de l'app (ModelsPage, BatchPage,
// ExportPanel). Bénéfices vs setInterval brut éparpillés :
//   - cleanup au unmount + à chaque dep change (garanti)
//   - pause auto quand l'onglet est caché (visibilitychange) — évite des
//     timers fantômes qui consomment des credits backend si l'utilisateur
//     a switché vers un autre onglet
//   - bypass de l'intervalle au tout premier tick (le caller doit avoir
//     déjà fait son fetch initial via un useEffect séparé — ce hook ne
//     déclenche QUE des ticks périodiques)
//
// Usage:
//   usePolling(fetchData, 3000, { enabled: anyRunning })
export default function usePolling(fn, intervalMs, { enabled = true } = {}) {
  // Stocke la fn dans un ref pour que les changements de closure
  // (ex. setState dépendant de props) ne reset pas le timer.
  const fnRef = useRef(fn)
  useEffect(() => { fnRef.current = fn }, [fn])

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return undefined
    let timer = null
    const tick = () => { fnRef.current?.() }
    const start = () => {
      if (timer != null) return
      timer = setInterval(tick, intervalMs)
    }
    const stop = () => {
      if (timer == null) return
      clearInterval(timer)
      timer = null
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else start()
    }
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      stop()
    }
  }, [enabled, intervalMs])
}

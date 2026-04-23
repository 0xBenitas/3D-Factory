import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

// Petit système de toast léger (pas de deps). Un seul provider monté dans
// App, les composants appellent `useToast()` puis `toast(msg, {type})`.
// Les types pilotent la classe CSS (`toast--success`, etc.).

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  // On tient un compteur en ref pour générer des ids stables même quand
  // plusieurs toasts sont créés dans le même tick.
  const nextId = useRef(1)

  const remove = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const show = useCallback(
    (message, { type = 'info', duration = 3500 } = {}) => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, message, type }])
      if (duration > 0) {
        setTimeout(() => remove(id), duration)
      }
      return id
    },
    [remove],
  )

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toast-container" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.type}`}>
            {t.message}
            <button
              type="button"
              className="toast__close"
              onClick={() => remove(t.id)}
              aria-label="Fermer la notification"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const show = useContext(ToastContext)
  if (!show) {
    // En tests ou si l'app est montée sans provider, on retombe sur un
    // no-op plutôt que de crasher — mieux vaut un toast perdu qu'une page
    // blanche.
    return () => null
  }
  return show
}

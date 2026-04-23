import { Suspense, useRef } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { Bounds, Center, Environment, OrbitControls, useBounds, useGLTF } from '@react-three/drei'

// SPECS §4.3 : viewer Three.js avec rotation + zoom.
// `<Bounds>` + `<Center>` auto-scale + auto-center le modèle, donc on
// n'a pas besoin de connaître la bbox à l'avance.
function GLBModel({ url }) {
  const { scene } = useGLTF(url)
  return <primitive object={scene} />
}

// Exposé depuis l'intérieur du Canvas : stocke une ref vers `useBounds()`
// pour que le bouton externe puisse déclencher le recadrage initial.
function RegisterBoundsHandle({ handleRef }) {
  const bounds = useBounds()
  const { controls } = useThree()
  handleRef.current = () => {
    bounds.refresh().clip().fit()
    // OrbitControls reset aussi son target pour repartir du centre propre.
    if (controls && typeof controls.reset === 'function') {
      try { controls.reset() } catch { /* selon version drei, peut échouer silencieusement */ }
    }
  }
  return null
}

export default function ModelViewer({ glbUrl, height = 400 }) {
  const resetRef = useRef(() => {})

  if (!glbUrl) {
    return (
      <div className="model-viewer model-viewer--empty" style={{ height }}>
        <span className="muted">Aucun modèle à afficher</span>
      </div>
    )
  }

  return (
    <div className="model-viewer" style={{ height }}>
      <button
        type="button"
        className="model-viewer__reset"
        onClick={() => resetRef.current?.()}
        title="Recadrer la vue"
        aria-label="Recadrer la vue"
      >
        ↻
      </button>
      <Canvas
        camera={{ position: [0, 0, 3], fov: 45 }}
        dpr={[1, 2]}
        // key force le remount quand l'URL change (évite le cache glTF
        // de useGLTF après un regenerate/remesh).
        key={glbUrl}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[5, 5, 5]} intensity={0.8} />
        <Suspense fallback={null}>
          <Bounds fit clip observe margin={1.2}>
            <Center>
              <GLBModel url={glbUrl} />
            </Center>
            <RegisterBoundsHandle handleRef={resetRef} />
          </Bounds>
          <Environment preset="city" background={false} />
        </Suspense>
        <OrbitControls makeDefault enablePan={false} />
      </Canvas>
    </div>
  )
}

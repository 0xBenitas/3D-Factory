import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { Bounds, Center, Environment, OrbitControls, useGLTF } from '@react-three/drei'

// SPECS §4.3 : viewer Three.js avec rotation + zoom.
// `<Bounds>` + `<Center>` auto-scale + auto-center le modèle, donc on
// n'a pas besoin de connaître la bbox à l'avance.
function GLBModel({ url }) {
  const { scene } = useGLTF(url)
  return <primitive object={scene} />
}

export default function ModelViewer({ glbUrl, height = 400 }) {
  if (!glbUrl) {
    return (
      <div className="model-viewer model-viewer--empty" style={{ height }}>
        <span className="muted">Aucun modèle à afficher</span>
      </div>
    )
  }

  return (
    <div className="model-viewer" style={{ height }}>
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
          </Bounds>
          <Environment preset="city" background={false} />
        </Suspense>
        <OrbitControls makeDefault enablePan={false} />
      </Canvas>
    </div>
  )
}

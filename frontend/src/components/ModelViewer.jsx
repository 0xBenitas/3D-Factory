import { Suspense, useEffect, useMemo, useRef } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import {
  Bounds,
  Center,
  ContactShadows,
  Environment,
  OrbitControls,
  useBounds,
  useGLTF,
} from '@react-three/drei'
import { ACESFilmicToneMapping, MeshStandardMaterial, SRGBColorSpace } from 'three'
import { Leva, useControls, folder } from 'leva'

// Studio viewer (Phase 2.10) — controls leva sur desktop, masqué sur
// mobile (cf. .leva-c-* dans index.css). Les contrôles bidouillent
// matériau / HDRI / lumières / fond / post-process. La persistence DB
// (table viewer_presets) viendra avec 2.13 recettes complètes — pour
// l'instant chaque session repart des défauts.

// HDRI presets fournis par drei (téléchargés depuis pmndrs/assets).
const HDRI_PRESETS = ['city', 'studio', 'apartment', 'sunset', 'dawn', 'warehouse', 'park', 'forest']

// Matériaux : valeurs (color, roughness, metalness) optimisées pour des
// rendus de modèles imprimés en 3D.
const MATERIAL_PRESETS = {
  Original: null, // garde le matériau natif du GLB
  'Porcelaine mat': { color: '#f0ede8', roughness: 0.6, metalness: 0.0 },
  PLA: { color: '#d8d8d8', roughness: 0.45, metalness: 0.0 },
  ABS: { color: '#cccccc', roughness: 0.55, metalness: 0.0 },
  Résine: { color: '#e8e8e8', roughness: 0.15, metalness: 0.0 },
  'Métal brossé': { color: '#bababa', roughness: 0.35, metalness: 0.85 },
}

const LIGHT_PRESETS = {
  'Studio 3-points': { ambient: 0.4, key: 0.9, fill: 0.4, rim: 0.5 },
  Softbox: { ambient: 0.6, key: 0.6, fill: 0.5, rim: 0.2 },
  Dramatic: { ambient: 0.15, key: 1.2, fill: 0.1, rim: 0.8 },
  Flat: { ambient: 1.0, key: 0.2, fill: 0.2, rim: 0.0 },
}


function GLBModel({ url, materialOverride }) {
  const { scene } = useGLTF(url)
  // Override de matériau : on clone une fois et on remplace tous les
  // mesh.material. useMemo évite de recréer à chaque render.
  const cloned = useMemo(() => {
    if (!materialOverride) return scene
    const newMat = new MeshStandardMaterial(materialOverride)
    scene.traverse((obj) => {
      if (obj.isMesh) obj.material = newMat
    })
    return scene
  }, [scene, materialOverride])
  // Cache GLTF de drei : libère l'entrée quand on quitte ce modèle pour
  // que le prochain affichage de la même URL refetche (utile après un
  // regenerate qui réécrit le .glb sous la même URL).
  useEffect(() => () => useGLTF.clear(url), [url])
  return <primitive object={cloned} />
}


function RegisterBoundsHandle({ handleRef }) {
  const bounds = useBounds()
  const { controls } = useThree()
  handleRef.current = () => {
    bounds.refresh().clip().fit()
    if (controls && typeof controls.reset === 'function') {
      try { controls.reset() } catch { /* selon version drei */ }
    }
  }
  return null
}


function StudioLights({ preset }) {
  const cfg = LIGHT_PRESETS[preset] || LIGHT_PRESETS['Studio 3-points']
  return (
    <>
      <ambientLight intensity={cfg.ambient} />
      <directionalLight position={[5, 5, 5]} intensity={cfg.key} castShadow />
      <directionalLight position={[-4, 2, -3]} intensity={cfg.fill} />
      <directionalLight position={[0, 4, -5]} intensity={cfg.rim} />
    </>
  )
}


export default function ModelViewer({ glbUrl, height = 400 }) {
  const resetRef = useRef(() => {})

  const {
    hdri,
    showHdriBackground,
    bgColor,
    material,
    lights,
    exposure,
    autoRotate,
    contactShadow,
  } = useControls(
    {
      Environnement: folder({
        hdri: { value: 'studio', options: HDRI_PRESETS },
        showHdriBackground: { value: false, label: 'HDRI en fond' },
        bgColor: { value: '#1c1c1f', label: 'Couleur fond (si HDRI off)' },
      }),
      Matériau: folder({
        material: { value: 'Original', options: Object.keys(MATERIAL_PRESETS) },
      }),
      Lumière: folder({
        lights: { value: 'Studio 3-points', options: Object.keys(LIGHT_PRESETS) },
        exposure: { value: 1.0, min: 0.2, max: 2.5, step: 0.05 },
      }),
      Avancé: folder({
        autoRotate: { value: false, label: 'Auto-rotation' },
        contactShadow: { value: true, label: 'Ombre portée' },
      }, { collapsed: true }),
    },
    { hidden: false },
  )

  if (!glbUrl) {
    return (
      <div className="model-viewer model-viewer--empty" style={{ height }}>
        <span className="muted">Aucun modèle à afficher</span>
      </div>
    )
  }

  const materialOverride = MATERIAL_PRESETS[material]

  return (
    <div className="model-viewer" style={{ height }}>
      <Leva
        collapsed
        titleBar={{ title: 'Studio', drag: true }}
        theme={{ sizes: { rootWidth: '240px', controlWidth: '110px' } }}
      />
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
        shadows
        camera={{ position: [0, 0, 3], fov: 45 }}
        dpr={[1, 2]}
        gl={{ toneMapping: ACESFilmicToneMapping, outputColorSpace: SRGBColorSpace }}
        onCreated={({ gl }) => { gl.toneMappingExposure = exposure }}
      >
        <color attach="background" args={[bgColor]} />
        <StudioLights preset={lights} />
        <Suspense fallback={null}>
          <Bounds fit clip observe margin={1.2}>
            <Center key={glbUrl}>
              <GLBModel url={glbUrl} materialOverride={materialOverride} />
            </Center>
            <RegisterBoundsHandle handleRef={resetRef} />
          </Bounds>
          <Environment preset={hdri} background={showHdriBackground} />
          {contactShadow && (
            <ContactShadows
              position={[0, -0.6, 0]}
              opacity={0.5}
              scale={5}
              blur={2.4}
              far={2}
            />
          )}
        </Suspense>
        <OrbitControls makeDefault enablePan={false} autoRotate={autoRotate} autoRotateSpeed={0.8} />
        <ExposureUpdater exposure={exposure} />
      </Canvas>
    </div>
  )
}


// Petit pont pour propager les changements d'exposure depuis leva vers
// le renderer Three (gl.toneMappingExposure n'est lu qu'à chaque frame).
function ExposureUpdater({ exposure }) {
  const { gl, invalidate } = useThree()
  gl.toneMappingExposure = exposure
  invalidate()
  return null
}

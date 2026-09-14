'use client';

import { Component, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, useGLTF } from '@react-three/drei';
import { Box3, Vector3, type Object3D, type Mesh, type MeshStandardMaterial } from 'three';
import { Loader2, ImageOff, RefreshCw, RotateCcw, Camera, Move3d, Box } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { RenderView } from './RenderView';

/**
 * La 3D INTERACTIVE du board : le modèle GLB exporté par KiCad
 * (`kicad-cli pcb export glb` — carte, pistes, pastilles, zones), servi par
 * `GET /api/projects/[id]/model`, affiché dans Three.js avec des contrôles
 * d'orbite. Clic-glisser pour tourner, molette pour zoomer, clic droit pour
 * déplacer — demandé le 2026-09-14 : « je clique avec le curseur et je peux
 * tourner n'importe où ».
 *
 * ⚠️ L'image du service n'a AUCUN modèle 3D de composant (0 installé) : les
 * composants n'apparaissent que par leurs pastilles. Le rendu « photo »
 * (raytracé, `RenderView`) reste accessible par le bouton Photo.
 */

export interface Board3DViewProps {
  projectId: string;
  version?: number | string | undefined;
}

export interface ModelUrlOptions {
  /** Les corps des composants (défaut) ou la carte nue — option demandée le 2026-09-14. */
  readonly components?: boolean;
}

export function modelUrl(projectId: string, version?: number | string, attempt = 0, options: ModelUrlOptions = {}): string {
  const q = new URLSearchParams();
  if (version !== undefined) q.set('v', String(version));
  if (options.components === false) q.set('components', '0');
  if (attempt) q.set('r', String(attempt));
  const s = q.toString();
  return `/api/projects/${encodeURIComponent(projectId)}/model${s ? `?${s}` : ''}`;
}

/**
 * Le GLB de KiCad est en MÈTRES (un board de 40 mm fait 0,04 unité). On le
 * ramène à une unité de large et on le centre : caméra, lumières et bornes de
 * zoom deviennent indépendantes de la taille de la carte — un 20 × 15 mm et
 * un 208 × 156 mm arrivent cadrés pareil.
 */
/**
 * Le style du visualiseur 3D de KiCad, demandé le 2026-09-14 : carte VERTE,
 * pastilles dorées, composants, fond dégradé bleu-gris. Le GLB porte le vert
 * sombre du masque (0.08/0.20/0.14, ce que KiCad écrit) et un gris pour le
 * cœur FR4 : ce sont l'éclairage et la teinte de KiCad qui font le rendu.
 * Fonction PURE, testée : (r, g, b) ∈ [0,1] → couleur KiCad ou null (on ne
 * touche pas aux composants ni au cuivre).
 */
export const VERT_MASQUE_KICAD = '#2a8a4a';
export const FR4_KICAD = '#b9b47a';

export function couleurStyleKiCad(r: number, g: number, b: number): string | null {
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  // Le masque : vert dominant, sombre.
  if (g > r * 1.5 && g > b * 1.2 && lum < 0.35) return VERT_MASQUE_KICAD;
  // Le cœur de la carte : gris neutre à mi-luminance (le `mat_1` 0.5/0.5/0.5 du GLB).
  if (Math.abs(r - g) < 0.03 && Math.abs(g - b) < 0.03 && lum > 0.4 && lum < 0.6) return FR4_KICAD;
  return null;
}

function appliquerStyleKiCad(scene: Object3D): void {
  scene.traverse((o) => {
    const mesh = o as Mesh;
    if (!mesh.isMesh) return;
    const materiaux = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of materiaux) {
      const std = m as MeshStandardMaterial;
      if (!std.color || (std.userData as { kicadStyle?: boolean }).kicadStyle) continue;
      const teinte = couleurStyleKiCad(std.color.r, std.color.g, std.color.b);
      if (teinte) {
        std.color.set(teinte);
        std.roughness = 0.45;
        std.metalness = 0.05;
      }
      (std.userData as { kicadStyle?: boolean }).kicadStyle = true;
    }
  });
}

function Board({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  useMemo(() => appliquerStyleKiCad(scene), [scene]);
  const { scale, position } = useMemo(() => {
    const box = new Box3().setFromObject(scene);
    const size = new Vector3();
    const center = new Vector3();
    box.getSize(size);
    box.getCenter(center);
    const plusGrand = Math.max(size.x, size.y, size.z) || 1;
    const s = 1 / plusGrand;
    return { scale: s, position: [-center.x * s, -center.y * s, -center.z * s] as [number, number, number] };
  }, [scene]);
  // Le cadrage est porté par un GROUPE, jamais par la scène elle-même : `useGLTF`
  // la met en cache, et un remontage (« Recentrer ») mesurerait une scène déjà
  // mise à l'échelle — la carte sortait 25 fois trop petite.
  return (
    <group scale={scale} position={position}>
      <primitive object={scene} />
    </group>
  );
}

/** Ce que le serveur dit des modèles de composants : `X-Model-Components: trouvés/déclarés`. */
export interface ComposantsInfo {
  readonly found: number;
  readonly declared: number;
}

export function lireComposantsInfo(entete: string | null): ComposantsInfo | undefined {
  const m = /^(\d+)\/(\d+)$/.exec((entete ?? '').trim());
  return m ? { found: Number(m[1]), declared: Number(m[2]) } : undefined;
}

type Etat =
  | { kind: 'loading' }
  | { kind: 'ready'; composants?: ComposantsInfo | undefined }
  | { kind: 'error'; message: string };

/**
 * Un chargeur glTF qui échoue (modèle corrompu, WebGL absent) lève pendant
 * le rendu : sans frontière, c'est toute la page qui tombe. Ici l'erreur
 * reste dans le viewer, avec son message.
 */
class FrontiereCanvas extends Component<{ children: ReactNode; onError: (message: string) => void }> {
  override state = { casse: false };
  static getDerivedStateFromError() { return { casse: true }; }
  override componentDidCatch(err: unknown) {
    this.props.onError(err instanceof Error ? err.message : '3D rendering failed');
  }
  override render() { return this.state.casse ? null : this.props.children; }
}

/**
 * On vérifie d'abord que le modèle est disponible (et on lit le message
 * d'erreur du serveur) avant de confier l'URL au chargeur glTF, qui ne sait
 * pas dire pourquoi un 502 a échoué.
 */
function useModeleDisponible(url: string): [Etat, () => void, (message: string) => void] {
  const [etat, setEtat] = useState<Etat>({ kind: 'loading' });
  const [tentative, setTentative] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setEtat({ kind: 'loading' });
    (async () => {
      try {
        const r = await fetch(url, { method: 'GET', signal: controller.signal, headers: { Accept: 'model/gltf-binary' } });
        if (cancelled) return;
        if (!r.ok) {
          let message = `3D model unavailable (${r.status})`;
          try {
            const corps = (await r.json()) as { error?: unknown };
            if (typeof corps.error === 'string') message = corps.error;
          } catch {
            // pas de JSON
          }
          if (!cancelled) setEtat({ kind: 'error', message });
          return;
        }
        // Le corps est lu pour que le cache HTTP le garde ; le chargeur glTF le relira de là.
        await r.arrayBuffer();
        if (!cancelled) setEtat({ kind: 'ready', composants: lireComposantsInfo(r.headers.get('x-model-components')) });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setEtat({ kind: 'error', message: err instanceof Error ? err.message : '3D model request failed' });
      }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [url, tentative]);
  return [etat, () => setTentative((t) => t + 1), (message) => setEtat({ kind: 'error', message })];
}

export function Board3DView({ projectId, version }: Board3DViewProps) {
  const [photo, setPhoto] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const [composants, setComposants] = useState(true);
  const url = useMemo(() => modelUrl(projectId, version, 0, { components: composants }), [projectId, version, composants]);
  const [etat, reessayer, signalerErreur] = useModeleDisponible(url);
  // Ce que le serveur sait des corps de composants : `n/m` présents, ou rien.
  const infoComposants = etat.kind === 'ready' ? etat.composants : undefined;
  const texteComposants = !composants
    ? 'carte nue'
    : infoComposants === undefined
      ? null
      : infoComposants.declared === 0
        ? 'aucun composant à modéliser'
        : infoComposants.found === 0
          ? `aucun modèle 3D installé sur le service (0/${infoComposants.declared})`
          : `composants ${infoComposants.found}/${infoComposants.declared}`;

  if (photo) {
    return (
      <div className="relative flex-1 min-h-0 flex flex-col" data-testid="board-3d-photo">
        <RenderView projectId={projectId} family="3d" version={version} />
        <button
          type="button"
          onClick={() => setPhoto(false)}
          className="absolute top-2 right-3 z-10 flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-[#8be05a] border border-[#3f7a2a]/40 bg-[#0a0a0a]/80"
          title="Retour à la 3D interactive"
        >
          <Move3d size={10} /> Interactif
        </button>
      </div>
    );
  }

  return (
    <div className="relative flex-1 min-h-0 flex flex-col bg-[#060606] overflow-hidden" data-testid="board-3d-view">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1a1a1a] bg-[#0a0a0a]">
        <span className="text-[10px] font-mono text-[#3d3d3d] tracking-wider">
          GLB KiCad · glisser pour tourner · molette pour zoomer · clic droit pour déplacer
          {texteComposants && <span data-testid="board-3d-composants"> · {texteComposants}</span>}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <button type="button" onClick={() => setComposants((c) => !c)} aria-label="Toggle components" aria-pressed={composants}
            title={composants ? 'Afficher la carte nue (sans les corps des composants)' : 'Afficher les corps des composants'}
            className={cn('flex items-center gap-1 px-2 py-1 rounded-md text-[10px] border transition-all',
              composants ? 'text-[#8be05a] border-[#3f7a2a]/40' : 'text-[#555] border-[#1e1e1e] hover:text-[#888]')}>
            <Box size={10} /> Composants
          </button>
          <button type="button" onClick={() => setResetKey((k) => k + 1)} aria-label="Reset view" title="Recentrer"
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-[#555] border border-[#1e1e1e] hover:text-[#888]">
            <RotateCcw size={10} /> Recentrer
          </button>
          <button type="button" onClick={() => setPhoto(true)} aria-label="Photo render" title="Rendu photo raytracé (vues fixes)"
            className={cn('flex items-center gap-1 px-2 py-1 rounded-md text-[10px] border transition-all', 'text-[#555] border-[#1e1e1e] hover:text-[#888]')}>
            <Camera size={10} /> Photo
          </button>
        </div>
      </div>

      <div className="relative flex-1 min-h-0">
        {etat.kind === 'ready' && (
          <FrontiereCanvas onError={signalerErreur}>
            {/* Éclairage local seulement : un `Environment` de drei irait chercher un HDR sur un CDN, que la CSP bloque. */}
            <Canvas key={resetKey} camera={{ position: [0.5, 1.0, 1.1], fov: 40, near: 0.01, far: 100 }} dpr={[1, 2]} data-testid="board-3d-canvas">
              {/* Fond dégradé bleu-gris et éclairage doux : le visualiseur 3D de KiCad. */}
              <color attach="background" args={['#8f93a8']} />
              <fog attach="fog" args={['#8f93a8', 3, 9]} />
              <hemisphereLight args={['#ffffff', '#5b6070', 1.1]} />
              <directionalLight position={[2, 3, 4]} intensity={1.5} />
              <directionalLight position={[-3, -2, 2]} intensity={0.5} />
              <Suspense fallback={null}>
                <Board url={url} />
              </Suspense>
              <OrbitControls makeDefault enableDamping dampingFactor={0.08} rotateSpeed={0.9} zoomSpeed={0.8} minDistance={0.2} maxDistance={20} />
            </Canvas>
          </FrontiereCanvas>
        )}
        {etat.kind === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3" role="status">
            <Loader2 size={18} className="animate-spin text-primary/60" />
            <span className="text-[11px] font-mono text-[#3d3d3d] tracking-wider">Exporting 3D model with KiCad…</span>
          </div>
        )}
        {etat.kind === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-8 text-center" role="alert">
            <div className="w-10 h-10 rounded-xl bg-[#1a0e0e] border border-destructive/20 flex items-center justify-center">
              <ImageOff size={16} className="text-destructive/70" />
            </div>
            <p className="text-xs font-semibold text-foreground/80">3D model unavailable</p>
            <p className="text-[11px] text-muted-foreground leading-relaxed max-w-sm">{etat.message}</p>
            <button type="button" onClick={reessayer}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#111] border border-border text-xs text-muted-foreground hover:text-foreground">
              <RefreshCw size={11} /> Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

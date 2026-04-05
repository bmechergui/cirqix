---
name: layrix-viewer
description: This skill should be used when the user asks to "implémenter le viewer PCB", "afficher le schéma KiCanvas", "viewer KiCad dans le navigateur", "afficher le viewer 3D", "sélectionner un composant dans le viewer" or mentions KiCanvas, Three.js, STEP, .kicad_sch, .kicad_pcb, rendu PCB.
version: 0.2.0
---

# Layrix — Viewer PCB

## Architecture viewer

```
Schéma (.kicad_sch) → KiCanvas web component → onglet Schematic
PCB    (.kicad_pcb) → KiCanvas web component → onglet Routing
STEP               → Three.js + occt-import-js → onglet 3D (plan Maker+)
```

Les fichiers `.kicad_sch` et `.kicad_pcb` sont stockés dans Supabase Storage :
```
storage/{userId}/{projectId}/schema.kicad_sch
storage/{userId}/{projectId}/board.kicad_pcb
```

---

## Viewer Schéma + PCB — KiCanvas

### Installation

```bash
pnpm --filter @layrix/web add @kicanvas/kicanvas
```

### Wrapper React

```typescript
// apps/web/src/widgets/viewer/ui/KiCanvasViewer.tsx
'use client';
import { useEffect } from 'react';

interface KiCanvasViewerProps {
  /** URL signée Supabase Storage vers .kicad_sch ou .kicad_pcb */
  src: string | null;
  type: 'schematic' | 'board';
  className?: string;
}

export function KiCanvasViewer({ src, type, className }: KiCanvasViewerProps) {
  useEffect(() => {
    // Import web components KiCanvas (browser-only)
    void import('@kicanvas/kicanvas');
  }, []);

  if (!src) {
    return (
      <div className={`flex items-center justify-center bg-[#090909] ${className ?? ''}`}>
        <p className="text-[#3D3D3D] text-xs font-mono">
          {type === 'schematic' ? 'Schéma non encore généré' : 'PCB non encore généré'}
        </p>
      </div>
    );
  }

  if (type === 'schematic') {
    return (
      // @ts-expect-error — web component KiCanvas
      <kicanvas-schematic
        src={src}
        class={`block w-full h-full ${className ?? ''}`}
      />
    );
  }

  return (
    // @ts-expect-error — web component KiCanvas
    <kicanvas-board
      src={src}
      class={`block w-full h-full ${className ?? ''}`}
    />
  );
}
```

### Déclaration TypeScript web components

```typescript
// apps/web/src/shared/types/kicanvas.d.ts
declare namespace JSX {
  interface IntrinsicElements {
    'kicanvas-schematic': React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement> & { src?: string },
      HTMLElement
    >;
    'kicanvas-board': React.DetailedHTMLProps<
      React.HTMLAttributes<HTMLElement> & { src?: string },
      HTMLElement
    >;
  }
}
```

### Intégration ViewerPanel

```typescript
// apps/web/src/widgets/viewer/ui/ViewerPanel.tsx
// Import conditionnel (SSR off)
const KiCanvasViewer = dynamic(
  () => import('./KiCanvasViewer').then((m) => m.KiCanvasViewer),
  { ssr: false, loading: () => <PCBPlaceholder /> }
);

// Dans le render :
{mode === 'schematic' && (
  <KiCanvasViewer
    src={pcbState?.kicad_sch_url ?? null}
    type="schematic"
    className="h-full"
  />
)}
{mode === 'routing' && (
  <KiCanvasViewer
    src={pcbState?.kicad_pcb_url ?? null}
    type="board"
    className="h-full"
  />
)}
```

---

## Supabase Storage — Upload fichiers KiCad

```typescript
// apps/web/src/app/api/agent/route.ts — dans le handler pcb_state
if (event.type === 'pcb_state' && event.state['kicad_sch_content']) {
  const schContent = event.state['kicad_sch_content'] as string;
  const pcbContent = event.state['kicad_pcb_content'] as string | undefined;

  // Upload .kicad_sch
  await supabase.storage
    .from('kicad-files')
    .upload(`${user.id}/${body.projectId}/schema.kicad_sch`, schContent, {
      contentType: 'text/plain',
      upsert: true,
    });

  // Signed URL (1h)
  const { data: schUrl } = await supabase.storage
    .from('kicad-files')
    .createSignedUrl(`${user.id}/${body.projectId}/schema.kicad_sch`, 3600);

  if (schUrl) {
    event.state['kicad_sch_url'] = schUrl.signedUrl;
  }

  // Idem pour .kicad_pcb si présent
  if (pcbContent) {
    await supabase.storage
      .from('kicad-files')
      .upload(`${user.id}/${body.projectId}/board.kicad_pcb`, pcbContent, {
        contentType: 'text/plain',
        upsert: true,
      });
    const { data: pcbUrl } = await supabase.storage
      .from('kicad-files')
      .createSignedUrl(`${user.id}/${body.projectId}/board.kicad_pcb`, 3600);
    if (pcbUrl) event.state['kicad_pcb_url'] = pcbUrl.signedUrl;
  }
}
```

### Migration Supabase — Bucket kicad-files

```sql
-- Bucket privé — accès par signed URL uniquement
INSERT INTO storage.buckets (id, name, public) VALUES ('kicad-files', 'kicad-files', false);

-- RLS : chaque user accède uniquement à son dossier
CREATE POLICY "kicad files owner only"
  ON storage.objects FOR ALL
  USING (bucket_id = 'kicad-files' AND (storage.foldername(name))[1] = auth.uid()::text);
```

---

## Viewer 3D — Three.js (fichier STEP)

```typescript
// apps/web/src/widgets/viewer/ui/PCBViewer3D.tsx
'use client';
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export function PCBViewer3D({ stepUrl }: { stepUrl: string }) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mountRef.current) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0A0A0A);

    const camera = new THREE.PerspectiveCamera(
      45,
      mountRef.current.clientWidth / mountRef.current.clientHeight,
      0.1, 1000
    );
    camera.position.set(0, 80, 100);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    mountRef.current.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.2);
    sun.position.set(50, 100, 50);
    scene.add(sun);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    // Charger STEP via occt-import-js (WebAssembly)
    // loadSTEP(stepUrl, scene, PCB_MATERIALS);

    let rafId: number;
    const animate = () => {
      rafId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(rafId);
      renderer.dispose();
    };
  }, [stepUrl]);

  return <div ref={mountRef} className="w-full h-full" />;
}
```

### Matériaux PCB réalistes

```typescript
import * as THREE from 'three';

export const PCB_MATERIALS = {
  fr4:        new THREE.MeshPhysicalMaterial({ color: 0x2d7a2d, roughness: 0.8, metalness: 0.0 }),
  copper:     new THREE.MeshPhysicalMaterial({ color: 0xd4a017, roughness: 0.3, metalness: 0.9 }),
  silkscreen: new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.9, metalness: 0.0 }),
  soldermask: new THREE.MeshPhysicalMaterial({ color: 0x1a5c1a, roughness: 0.5, metalness: 0.0, transparent: true, opacity: 0.85 }),
};
```

---

## Règles importantes

- `KiCanvasViewer` → `ssr: false` obligatoire (web component browser uniquement)
- Les URLs Supabase Storage signées expirent après 1h — regénérer au rechargement
- `kicad_sch_url` et `kicad_pcb_url` sont stockés dans `pcb_state` JSONB en DB
- Skeleton si URL null (fichier pas encore généré par l'agent)
- JAMAIS importer PixiJS pour le viewer schéma ou PCB (remplacé par KiCanvas)

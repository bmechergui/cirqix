---
name: layrix-viewer
description: This skill should be used when the user asks to "implémenter le viewer PCB", "afficher les layers PixiJS", "ajouter le viewer 3D", "zoomer/panner le PCB", "sélectionner un composant dans le viewer", "afficher les markers DRC" or mentions PixiJS, Three.js, STEP, layers, mmToPx, rendu PCB.
version: 0.1.0
---

# Layrix — Viewer PCB

## Viewer 2D — PixiJS (WebGL, 60 FPS)

### Couleurs des layers

```typescript
// packages/ui/src/viewer/layers.ts
export const LAYER_COLORS: Record<string, number> = {
  "F.Cu":       0xD4820A,  // cuivre avant → copper brand
  "B.Cu":       0x4488FF,  // cuivre arrière → bleu
  "F.SilkS":    0xCCCCCC,  // sérigraphie avant → gris clair
  "B.SilkS":    0x999999,  // sérigraphie arrière → gris
  "F.Mask":     0xD4820A,  // masque avant → copper (alpha 0.2)
  "B.Mask":     0x4488FF,  // masque arrière → bleu (alpha 0.2)
  "Edge.Cuts":  0xFFFF00,  // contour → jaune
  "F.Courtyard":0xFFFF00,  // courtyard (alpha 0.1)
  "DRC_ERROR":  0xEF4444,  // violation erreur → rouge (clignote)
  "DRC_WARNING":0xF59E0B,  // violation warning → amber
  "SELECTED":   0x00C2FF,  // composant sélectionné → cyan brand
};

export const LAYER_ORDER = [
  "B.Cu", "B.Mask", "B.SilkS",
  "F.Cu", "F.Mask", "F.SilkS",
  "F.Courtyard", "Edge.Cuts",
];

// 1mm = 10px au zoom 1×
export const MM_TO_PX = 10;
export const mmToPx = (mm: number) => mm * MM_TO_PX;
```

### Composant PCBViewer2D

```typescript
// packages/ui/src/viewer/PCBViewer2D.tsx
"use client";
import { useEffect, useRef } from "react";
import * as PIXI from "pixi.js";
import { renderPCB } from "./renderer";

interface Props {
  pcbJson: PCBData | null;
  visibleLayers?: string[];
  selectedRef?: string;
  drcViolations?: DRCViolation[];
  onSelectComponent?: (ref: string) => void;
}

export function PCBViewer2D({ pcbJson, visibleLayers = [], selectedRef, drcViolations = [], onSelectComponent }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const appRef  = useRef<PIXI.Application | null>(null);

  useEffect(() => {
    if (!mountRef.current) return;
    const app = new PIXI.Application({
      resizeTo: mountRef.current,
      backgroundColor: 0x0D0D0D,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
    });
    mountRef.current.appendChild(app.canvas);
    appRef.current = app;
    return () => { app.destroy(true); };
  }, []);

  useEffect(() => {
    if (!appRef.current || !pcbJson) return;
    renderPCB(appRef.current, pcbJson, { visibleLayers, selectedRef, drcViolations, onSelectComponent });
  }, [pcbJson, visibleLayers, selectedRef, drcViolations]);

  return <div ref={mountRef} className="w-full h-full bg-[#0D0D0D]" />;
}
```

### Renderer

```typescript
// packages/ui/src/viewer/renderer.ts
import * as PIXI from "pixi.js";
import { LAYER_COLORS, LAYER_ORDER, mmToPx } from "./layers";

export function renderPCB(app: PIXI.Application, pcb: PCBData, opts: RenderOpts) {
  const root = new PIXI.Container();
  app.stage.removeChildren();
  app.stage.addChild(root);

  // Layers
  for (const layer of LAYER_ORDER) {
    if (!opts.visibleLayers.includes(layer)) continue;
    root.addChild(renderLayer(pcb, layer));
  }

  // Composants (cliquables)
  for (const comp of pcb.components) {
    const fp = renderFootprint(comp, comp.ref === opts.selectedRef);
    fp.eventMode = "static";
    fp.cursor = "pointer";
    fp.on("pointertap", () => opts.onSelectComponent?.(comp.ref));
    root.addChild(fp);
  }

  // Markers DRC (rouge clignotant = erreur, amber = warning)
  for (const v of opts.drcViolations) {
    root.addChild(renderDRCMarker(v));
  }

  // Centrer
  const b = root.getBounds();
  root.x = (app.screen.width  - b.width)  / 2 - b.x;
  root.y = (app.screen.height - b.height) / 2 - b.y;
}

function renderDRCMarker(v: DRCViolation): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const color = v.severity === "error" ? LAYER_COLORS.DRC_ERROR : LAYER_COLORS.DRC_WARNING;
  g.circle(mmToPx(v.x_mm), mmToPx(v.y_mm), 8).fill({ color, alpha: 0.8 });
  if (v.severity === "error") {
    let t = 0;
    PIXI.Ticker.shared.add(() => { g.alpha = 0.5 + 0.5 * Math.sin(t++ * 0.1); });
  }
  return g;
}
```

### Toolbar layers

```tsx
// packages/ui/src/viewer/LayerToggle.tsx
const LAYERS = [
  { id: "F.Cu",     label: "F.Cu",  color: "#D4820A" },
  { id: "B.Cu",     label: "B.Cu",  color: "#4488FF" },
  { id: "F.SilkS",  label: "Silk",  color: "#CCCCCC" },
  { id: "Edge.Cuts",label: "Edge",  color: "#FFFF00" },
];

export function LayerToggle({ visible, onToggle }: { visible: string[]; onToggle: (id: string) => void }) {
  return (
    <div className="flex gap-1 p-2 bg-[#111111] border border-[#2E2E2E] rounded-lg">
      {LAYERS.map(({ id, label, color }) => (
        <button key={id} onClick={() => onToggle(id)}
          className={`px-2 py-1 text-xs rounded font-mono border transition-all ${
            visible.includes(id) ? "opacity-100" : "opacity-25"
          }`}
          style={{ borderColor: color, color }}>
          {label}
        </button>
      ))}
    </div>
  );
}
```

---

## Viewer 3D — Three.js (fichier STEP)

```typescript
// packages/ui/src/viewer/PCBViewer3D.tsx
"use client";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls";

export function PCBViewer3D({ stepUrl }: { stepUrl: string }) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mountRef.current) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0A0A0A);

    const camera = new THREE.PerspectiveCamera(45,
      mountRef.current.clientWidth / mountRef.current.clientHeight, 0.1, 1000);
    camera.position.set(0, 80, 100);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    mountRef.current.appendChild(renderer.domElement);

    // Éclairage réaliste PCB
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.2);
    sun.position.set(50, 100, 50);
    scene.add(sun);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    // Charger STEP via occt-import-js (WebAssembly)
    loadSTEP(stepUrl, scene, PCB_MATERIALS);

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
      mountRef.current?.removeChild(renderer.domElement);
    };
  }, [stepUrl]);

  return <div ref={mountRef} className="w-full h-full" />;
}
```

### Matériaux PCB réalistes

```typescript
// packages/ui/src/viewer/materials.ts
import * as THREE from "three";

export const PCB_MATERIALS = {
  fr4: new THREE.MeshPhysicalMaterial({
    color: 0x2d7a2d,   // vert FR4
    roughness: 0.8, metalness: 0.0,
  }),
  copper: new THREE.MeshPhysicalMaterial({
    color: 0xd4a017,   // cuivre doré
    roughness: 0.3, metalness: 0.9,
  }),
  silkscreen: new THREE.MeshPhysicalMaterial({
    color: 0xffffff,   // sérigraphie blanche
    roughness: 0.9, metalness: 0.0,
  }),
  soldermask: new THREE.MeshPhysicalMaterial({
    color: 0x1a5c1a,   // masque vert foncé
    roughness: 0.5, metalness: 0.0,
    transparent: true, opacity: 0.85,
  }),
};
```

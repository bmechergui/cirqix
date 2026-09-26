---
name: cirqix-viewer
description: This skill should be used when the user asks to "implémenter le viewer PCB", "afficher le schéma KiCanvas", "viewer KiCad dans le navigateur", "afficher le viewer 3D", "sélectionner un composant dans le viewer" or mentions KiCanvas, Three.js, STEP, .kicad_sch, .kicad_pcb, rendu PCB.
version: 0.2.0
---

# Cirqix — Viewer PCB

## Architecture viewer

```
Schéma (.kicad_sch) → KiCanvas web component → onglet Schematic
PCB    (.kicad_pcb) → KiCanvas web component → onglet Routing
PCB    (.kicad_pcb) → service POST /export/glb → GET /api/projects/[id]/model → Board3DView (mode 3d)
PCB    (.kicad_pcb) → service POST /render/auto (kicad-cli pcb render)
                     → GET /api/projects/[id]/render?view=&quality=&yaw=
                     → modes `png` (top/bottom) et `3d` (iso/front/back/left/right)
```

KiCanvas est monté en `controls="full"` + `controlslist="nooverlay"` : panneaux
couches / nets / objets / empreintes / propriétés comme dans KiCad ; l'événement
`kicanvas:select` (`detail.item`, émis sur l'objet viewer, voir ci-dessous) porte l'objet cliqué —
`describeSelection()` dans `KiCanvasViewer.tsx` le nomme. Presets et bornes des
rendus : `apps/web/src/shared/lib/render-presets.ts` (partagé route ↔ viewer).

---

## Viewer Schéma + PCB — KiCanvas

### KiCanvas

`apps/web/src/widgets/viewer/ui/KiCanvasViewer.tsx` charge le script par `loadKiCanvas()` (`apps/web/src/widgets/viewer/lib/kicanvas-loader.ts`), qui pose le thème dans `localStorage` (`kc:prefs:theme`) avant le chargement, et monte `<kicanvas-embed controls="full">`. L'événement `kicanvas:select` est émis sur l'objet viewer : un écouteur posé seulement sur l'élément DOM ne le reçoit pas. Composant client uniquement (`ssr: false`).

---

## Stockage

Bucket privé `kicad-files`, chemins `{userId}/{projectId}/schematic.kicad_sch` et `pcb.kicad_pcb`. Dépôt : `store.uploadArtifact` (`packages/agents/src/pipeline/store.ts`) ou `apps/web/src/app/api/agent/lib/kicad-storage.ts`. URL signées (1 h) réémises par `GET /api/projects/[id]/pcb-state`.

### Bucket kicad-files

Migrations `002_kicad_files_bucket.sql` (bucket privé, policies par dossier `{userId}/`), `024_kicad_files_png_renders.sql` et `025_kicad_files_bucket_glb.sql` (types MIME `image/png` et `model/gltf-binary`, sans lesquels le dépôt d'un rendu est refusé). Un nouveau type d'artefact demande sa migration de types MIME.

---

## Viewer 3D

`apps/web/src/widgets/viewer/ui/Board3DView.tsx` affiche le GLB exporté par `POST /export/glb` (`kicad-cli pcb export glb`), servi par `GET /api/projects/[id]/model` (cache `renders/<clé>.glb`), avec @react-three/fiber ≥ 9 et drei 10 : Next 15 embarque React 19 pour l'App Router. Pas de `<Environment>` de drei : la CSP bloque son HDR. Le rendu raytracé passe par `RenderView.tsx` (« Photo »).

---

## Règles importantes

- `KiCanvasViewer` → `ssr: false` obligatoire (web component browser uniquement)
- Les URLs Supabase Storage signées expirent après 1h — regénérer au rechargement
- `kicad_sch_url` et `kicad_pcb_url` sont stockés dans `pcb_state` JSONB en DB
- Skeleton si URL null (fichier pas encore généré par l'agent)
- JAMAIS importer PixiJS pour le viewer schéma ou PCB (remplacé par KiCanvas)

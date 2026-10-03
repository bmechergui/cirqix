---
name: cirqix-prompt-improver
version: 3.0.0
description: Améliore tout prompt avant exécution — ajoute le contexte Cirqix de la phase en cours et choisit le skill à invoquer. À invoquer avant chaque tâche.
---

## Phase active

Lire la phase en cours et les phases terminées dans la section « Phase actuelle » de `CLAUDE.md` et dans `PLAN.md` au moment de la tâche ; ne pas les recopier ici.

**Focus :** cascade footprint (KiCad → cache pgvector → SnapMagic → LCSC → Haiku), placement kicad-tools et routage Freerouting réels, DRC kicad-cli, export Gerbers/BOM/CPL et modèle 3D GLB, viewer KiCanvas, préparation de commande JLCPCB
**Fichiers :** `packages/agents/src/engines/`, `services/kicad/routers/`, `apps/web/src/widgets/viewer/`
**Contraintes à toujours mentionner :**
- Skill `cirqix-footprint` : cascade en 5 étapes (cache pgvector compris), arrêt à la première réussite
- Skill `cirqix-kicad-service` : service FastAPI (`/schematic/generate`, `/pcb/generate`, `/place/auto`, `/erc`, `/route/auto`, `/drc/auto`, `/export/all`, `/render/auto`, `/export/glb`), jeton Bearer requis sauf sur `/health`
- Skill `cirqix-drc` : boucle DRC max 3× dans le service ; kicad-cli fait foi ; corrections limitées (via vers le plan, remplissage des zones par pcbnew en processus enfant)
- Skill `cirqix-credits` : réserver avant le run, libérer sur échec, débiter après un succès prouvé (RPC atomiques)
- Skill `cirqix-viewer` : modes `native` (KiCanvas `controls="full"`), `spec` (vue Cirqix SVG), `png` et `3d` (rendus KiCad : `RenderView.tsx`, `Board3DView.tsx`)
- Moteurs : circuit_synth pour le schéma, kicad-tools pour le board ; pas de TSCircuit en nouveau code (déprécié depuis v0.3.0)
- JLCPCB : confirmation **"OUI JE CONFIRME"** obligatoire — jamais automatique
- Événements d'un run : `RunEvent` JSON (SSE en synchrone ; `pcb_run_events` + Realtime en asynchrone), sans marqueur `[DONE]`
- Orchestrateur = Sonnet 4.6, max 15 itérations ; seuls le schéma, l'empreinte IA et le reasoner appellent Haiku 4.5, les autres étapes sont des handlers déterministes
- Middleware auth : `apps/web/src/middleware.ts` → `/dashboard/*`
- Zustand store : `apps/web/src/shared/store/app-store.ts`

---

## Processus en 3 étapes

### Étape 1 — Analyser

- Intention réelle de l'utilisateur
- Fichier exact dans la structure FSD
- Contraintes manquantes (crédits ? RLS ? streaming ?)
- Ambiguïtés à lever

### Étape 2 — Réécrire en XML

```
[Phase en cours]
[Skill détecté : cirqix-xxx ou /skill-name]

📝 Prompt reçu :
[original]

✨ Prompt amélioré :
<context>
[Phase en cours]. Fichier : [chemin exact]. État actuel : [ce que fait le fichier maintenant].
</context>
<task>
[Verbe fort] [opération précise].
</task>
<constraints>
Contraintes réelles de la tâche, chacune avec sa raison (ex. : « réserver les crédits avant le run, débiter après succès — sinon un run échoué est facturé, ou deux runs partent sur le même solde »).
Critère d'arrêt : [condition vérifiable]
</constraints>
<output_format>
[type exact + interface TypeScript ou signature Python]
Fais uniquement ce qui est demandé. Aucune feature supplémentaire.
</output_format>

▶️ J'invoque [skill] avec ce prompt — confirme ou modifie.
```

### Étape 3 — Attendre confirmation

Confirme → exécuter. Modifie → reprendre sans redemander.

---

## Règles de réécriture

| Prompt contient | Ajouter |
|----------------|---------|
| "fais X" sans fichier | Chemin FSD exact |
| "agent" sans précision | Orchestrateur / Schéma / DRC / Footprint ? |
| "base de données" | Table + RLS + migration Supabase |
| "affiche X" | Composant + classes design system + états loading/empty/error |
| Touche aux crédits | Réserver avant, libérer sur échec, débiter après succès (skill `cirqix-credits`) |
| Touche aux agents | Modèle (Sonnet ; Haiku pour schéma, empreinte IA, reasoner), max 15 itérations, `RunEvent` (SSE ou `pcb_run_events`) |
| Touche à la DB | RLS + uuid-ossp + pgvector si embeddings |
| Touche au viewer | `widgets/viewer/ui/KiCanvasViewer.tsx`, `shared/lib/render-presets.ts`, `docs/design/design-system.md` |
| Touche à JLCPCB | Confirmation "OUI JE CONFIRME" obligatoire, jamais automatique |

## Correction linguistique

- Fautes → corriger silencieusement
- Langage vague ("truc", "machin") → terme technique précis
- Langue mixte → harmoniser en français technique

---

## Choix du skill

Choisir le skill Cirqix dont la description couvre la tâche. Pour un domaine technique qu'aucun skill Cirqix ne couvre, ajouter le skill global correspondant, dans l'ordre de priorité de la section « Skills — sélection et création » de `CLAUDE.md`. S'il y a plusieurs candidats, invoquer le plus central et nommer l'autre. Décider sans demander, avec une ligne de justification ; si aucun skill ne convient, exécuter directement.

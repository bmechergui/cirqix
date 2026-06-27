---
name: cirqix-prompt-improver
version: 3.0.0
description: Améliore tout prompt avant exécution — détecte phase active, ajoute contexte Cirqix Phase 4, détecte le skill à invoquer. Mettre à jour quand la phase change.
---

## Quand invoquer

**TOUJOURS — avant chaque tâche, quelle que soit la complexité.**

---

## Phase active : Phase 4 — Agent Footprint + Pipeline KiCad complet

> Pour les autres phases, lire `PLAN.md`. Mettre à jour ce skill quand la phase change.

**Phases complétées :** Phase 0 ✓ · Phase 1 ✓ · Phase 2 ✓ · Phase 3 ✓ · Phase 4.1 ✓

**Focus :** footprint cascade (KiCad → SnapMagic → LCSC → AI Haiku), pcbnew placement/routing réels, DRC natif, export Gerbers/BOM/STEP, viewer KiCanvas dual-mode, JLCPCB commande
**Fichiers :** `packages/agents/src/engines/`, `services/kicad/routers/`, `apps/web/src/widgets/viewer/`
**Contraintes à toujours mentionner :**
- Skill `cirqix-footprint` : cascade 4 étapes — s'arrêter à la 1ère réussite
- Skill `cirqix-kicad-service` : FastAPI pcbnew (`/place/auto`, `/route`, `/drc`, `/export`)
- Skill `cirqix-drc` : boucle DRC max 3×, corrections pcbnew automatiques
- Skill `cirqix-credits` : vérifier solde AVANT, déduire APRÈS succès
- Skill `cirqix-viewer` : KiCanvas dual-mode (native `.kicad_pcb` / spec SVG custom)
- Moteur PCB : **Circuit-Synth** (Python) — JAMAIS TSCircuit en nouveau code
- JLCPCB : confirmation **"OUI JE CONFIRME"** obligatoire — jamais automatique
- Streaming SSE : `Content-Type: text/event-stream`, event `[DONE]` en fin
- Orchestrateur = Sonnet 4.6, agents spécialisés = Haiku 4.5, max 15 itérations
- Middleware auth : `apps/web/src/middleware.ts` → `/dashboard/*`
- Zustand store : `apps/web/src/shared/store/app-store.ts`

---

## Pipeline

```
1. prompt-master-cirqix  → optimise pour Claude Code (9D matrix, XML, signal words)
2. cirqix-prompt-improver → ajoute contexte Phase 4 + détecte skill
   ↓
prompt final XML + skill sélectionné
```

---

## Processus en 4 étapes

### Étape 1 — Détecter la phase

Mots-clés Phase 4 : `footprint`, `kicad_mod`, `snapmagic`, `lcsc`, `gerber`, `bom`, `step`, `jlcpcb`, `drc`, `commande`, `placement réel`, `pcbnew`, `freerouting`
Mots-clés Phase 3 (encore actifs) : `placement`, `routage`, `drc`, `export`, `pcbnew`, `docker`
Mots-clés Phase 2 (toujours valides) : `dashboard`, `auth`, `chat`, `viewer`, `crédits`, `SSE`
Afficher : `[Phase 4 — Agent Footprint + Pipeline KiCad complet]`

### Étape 2 — Analyser

- Intention réelle de l'utilisateur
- Fichier exact dans la structure FSD
- Contraintes manquantes (crédits ? RLS ? streaming ?)
- Ambiguïtés à lever

### Étape 3 — Réécrire en XML

```
[Phase 4 — Agent Footprint + Pipeline KiCad complet]
[Skill détecté : cirqix-xxx ou /skill-name]

📝 Prompt reçu :
[original]

✨ Prompt amélioré :
<context>
Phase 4. Fichier : [chemin exact]. État actuel : [ce que fait le fichier maintenant].
</context>
<task>
[Verbe fort] [opération précise].
</task>
<constraints>
MUST : [contraintes obligatoires + Phase 2 spécifiques]
NEVER : [interdictions absolues]
Stop when : [condition binaire]
</constraints>
<output_format>
[type exact + interface TypeScript ou signature Python]
Fais uniquement ce qui est demandé. Aucune feature supplémentaire.
</output_format>

▶️ J'invoque [skill] avec ce prompt — confirme ou modifie.
```

### Étape 4 — Attendre confirmation

Confirme → exécuter. Modifie → reprendre sans redemander.

---

## Règles de réécriture

| Prompt contient | Ajouter |
|----------------|---------|
| "fais X" sans fichier | Chemin FSD exact |
| "agent" sans précision | Orchestrateur / Schéma / DRC / Footprint ? |
| "base de données" | Table + RLS + migration Supabase |
| "affiche X" | Composant + classes design system + états loading/empty/error |
| Touche aux crédits | Vérifier AVANT, déduire APRÈS (skill `cirqix-credits`) |
| Touche aux agents | Modèle (Sonnet ou Haiku), max 15 itérations, streaming SSE |
| Touche à la DB | RLS + uuid-ossp + pgvector si embeddings |
| Touche au viewer | `LAYER_COLORS`, `mmToPx`, design system |
| Touche à JLCPCB | Confirmation "OUI JE CONFIRME" obligatoire, jamais automatique |

## Correction linguistique

- Fautes → corriger silencieusement
- Langage vague ("truc", "machin") → terme technique précis
- Langue mixte → harmoniser en français technique

---

## Détection automatique du skill

```
├── agent / orchestrateur / boucle / SSE / itération  → cirqix-pcb-agent
├── footprint / kicad_mod / snapmagic / octopart       → cirqix-footprint
├── placement / routage / freerouting / gerber         → cirqix-kicad-service
├── viewer / kicanvas / kicad_sch / kicad_pcb / schéma  → cirqix-viewer
├── circuit-synth / @circuit / Net() / Component() / symbol mapping / KICAD_SYMBOL_DIR → cirqix-circuit-synth
├── génération kicad / python kicad / kicad_sch depuis python   → cirqix-circuit-synth + cirqix-kicad-service
├── crédit / balance / plan / lemon squeezy / top-up   → cirqix-credits
├── DRC / violation / clearance / track width          → cirqix-drc
├── dashboard / composant React / UI / tailwind        → /everything-claude-code:frontend-patterns
├── supabase / migration / RLS / pgvector / SQL        → /everything-claude-code:postgres-patterns
├── FastAPI / Python / pcbnew / docker                 → cirqix-kicad-service + python-patterns
├── test / playwright / e2e / vitest                   → /everything-claude-code:e2e
├── Claude API / SDK / tool_use / streaming            → /everything-claude-code:claude-api
├── architecture / plan / refactoring                  → /everything-claude-code:plan
└── autre → exécuter directement
```

- Plusieurs skills → invoquer skill Cirqix d'abord, skill global ensuite
- Aucun skill → exécuter directement
- 2 domaines → mentionner les deux, invoquer le plus central
- **Ne jamais demander** quel skill — décider et expliquer en une ligne

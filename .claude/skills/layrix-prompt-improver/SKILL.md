---
name: layrix-prompt-improver
version: 2.0.0
description: Améliore tout prompt avant exécution — détecte phase active, ajoute contexte Layrix Phase 2, détecte le skill à invoquer. Mettre à jour quand la phase change.
---

## Quand invoquer

**TOUJOURS — avant chaque tâche, quelle que soit la complexité.**

---

## Phase active : Phase 2 — Dashboard + Auth + Chat Agent MVP

> Pour les autres phases, lire `PLAN.md`. Mettre à jour ce skill quand la phase change.

**Focus :** Supabase Auth, chat agent Claude SDK, streaming SSE, viewer PixiJS, crédits
**Fichiers :** `apps/web/src/`, `packages/agents/src/orchestrator.ts`, `apps/api/app/api/`
**Contraintes à toujours mentionner :**
- Skill `layrix-pcb-agent` pour la boucle agentique
- Skill `layrix-credits` : vérifier solde AVANT, déduire APRÈS succès
- Skill `layrix-viewer` pour PixiJS (couleurs `LAYER_COLORS`, `mmToPx`)
- Streaming SSE : `Content-Type: text/event-stream`, event `[DONE]` en fin
- Middleware auth déjà en place : `apps/web/src/middleware.ts` → `/dashboard/*`
- Zustand store : `apps/web/src/shared/store/app-store.ts`
- FSD : features → `apps/web/src/features/`, widgets → `apps/web/src/widgets/`, entities → `apps/web/src/entities/`

---

## Pipeline

```
1. prompt-master-layrix  → optimise pour Claude Code (9D matrix, XML, signal words)
2. layrix-prompt-improver → ajoute contexte Phase 2 + détecte skill
   ↓
prompt final XML + skill sélectionné
```

---

## Processus en 4 étapes

### Étape 1 — Détecter la phase

Mots-clés Phase 2 : `dashboard`, `auth`, `login`, `chat`, `agent`, `streaming`, `viewer`, `crédits`, `SSE`, `Supabase`
Afficher : `[Phase 2 — Dashboard + Auth + Chat Agent MVP]`

### Étape 2 — Analyser

- Intention réelle de l'utilisateur
- Fichier exact dans la structure FSD
- Contraintes manquantes (crédits ? RLS ? streaming ?)
- Ambiguïtés à lever

### Étape 3 — Réécrire en XML

```
[Phase 2 — Dashboard + Auth + Chat Agent MVP]
[Skill détecté : layrix-xxx ou /skill-name]

📝 Prompt reçu :
[original]

✨ Prompt amélioré :
<context>
Phase 2. Fichier : [chemin exact]. État actuel : [ce que fait le fichier maintenant].
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
| Touche aux crédits | Vérifier AVANT, déduire APRÈS (skill `layrix-credits`) |
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
├── agent / orchestrateur / boucle / SSE / itération  → layrix-pcb-agent
├── footprint / kicad_mod / snapmagic / octopart       → layrix-footprint
├── placement / routage / freerouting / gerber         → layrix-kicad-service
├── viewer / pixijs / layer / F.Cu / 3D / three.js     → layrix-viewer
├── crédit / balance / plan / lemon squeezy / top-up   → layrix-credits
├── DRC / violation / clearance / track width          → layrix-drc
├── dashboard / composant React / UI / tailwind        → /everything-claude-code:frontend-patterns
├── supabase / migration / RLS / pgvector / SQL        → /everything-claude-code:postgres-patterns
├── FastAPI / Python / pcbnew / docker                 → layrix-kicad-service + python-patterns
├── test / playwright / e2e / vitest                   → /everything-claude-code:e2e
├── Claude API / SDK / tool_use / streaming            → /everything-claude-code:claude-api
├── architecture / plan / refactoring                  → /everything-claude-code:plan
└── autre → exécuter directement
```

- Plusieurs skills → invoquer skill Layrix d'abord, skill global ensuite
- Aucun skill → exécuter directement
- 2 domaines → mentionner les deux, invoquer le plus central
- **Ne jamais demander** quel skill — décider et expliquer en une ligne

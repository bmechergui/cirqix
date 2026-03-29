# Layrix — Workflow de développement

## Règle absolue — ordre d'exécution pour CHAQUE tâche

```
Prompt reçu
    │
    ▼
┌─────────────────────────────────────────────┐
│  1. prompt-master                           │
│     Optimise le prompt pour Claude Code     │
│     Format XML + signal words + stop cond.  │
└───────────────────────┬─────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────┐
│  2. layrix-prompt-improver                  │
│     Détecte la phase active (0→5)           │
│     Ajoute contexte Layrix                  │
│     Détecte le skill à invoquer             │
└───────────────────────┬─────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────┐
│  3. Sélection du skill technique            │
│                                             │
│  Priorité 1 → everything-claude-code:xxx   │
│  Priorité 2 → skills.sh (installés)        │
│  Priorité 3 → npx skills find "query"      │
│  Priorité 4 → skill-creator (créer)        │
└───────────────────────┬─────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────┐
│  4. Exécution + Review                      │
│     code-reviewer après chaque implémentation│
│     security-reviewer avant commit          │
└─────────────────────────────────────────────┘
```

---

## Workflow complet par tâche (prompt → PR)

### 1. Recevoir le prompt
```
Skill: layrix-prompt-improver  ← TOUJOURS en premier
Améliore + clarifie le prompt avant toute action.
```

### 2. Planifier
Claude choisit seul le niveau selon la complexité :

| Complexité | Action |
|------------|--------|
| Simple (1 fichier, bug fix) | Coder directement — pas de plan |
| Moyenne (feature, 2-5 fichiers) | Annoncer les étapes avant de coder |
| Complexe (feature multi-fichiers, archi) | `/everything-claude-code:plan` + doc avant de coder |
| Très complexe (nouveau système, agents, DB) | `architect` agent + `/superpowers:write-plan` |

```
Skill: /everything-claude-code:plan  ← feature complexe
Skill: /superpowers:brainstorm       ← si besoin d'explorer
```

### 3. Coder (TDD)
```
Skill: /everything-claude-code:tdd                ← écrire test d'abord
Skill: /everything-claude-code:frontend-patterns  ← Next.js
Skill: /everything-claude-code:backend-patterns   ← API
```

### 4. Review
```
Skill: /everything-claude-code:security-scan  ← sécurité
Agent: typescript-reviewer                    ← qualité code
Skill: /simplify                              ← nettoyer
```

### 5. Vérifier
```
pnpm type-check  ← 0 erreurs TypeScript
Skill: /superpowers:verification-before-completion
```

### 6. Commit + PR
```
Skill: /commit-commands:commit-push-pr  ← tout en un
```

### Résumé visuel
```
prompt → improver → plan → TDD → code → review → type-check → commit+PR
```

### Annonce obligatoire avant chaque appel

**ALWAYS** annoncer dans le texte avant d'invoquer :

```
[Skill : layrix-prompt-improver] — amélioration du prompt
[MCP : context7] — recherche docs officielle
[Agent : typescript-reviewer] — review qualité code
[Plugin : X] — raison
```

**NEVER** appeler un skill, MCP, agent ou plugin sans l'annoncer d'abord.

---

## Arbre de décision — trouver le bon skill

```
Besoin d'un skill pour la tâche X ?
│
├─ 1. Chercher dans everything-claude-code:
│      /everything-claude-code:frontend-patterns
│      /everything-claude-code:python-patterns
│      /everything-claude-code:postgres-patterns
│      /everything-claude-code:claude-api
│      /everything-claude-code:api-design
│      /everything-claude-code:tdd
│      /everything-claude-code:e2e
│      /everything-claude-code:security-scan
│      → Si trouvé → utiliser directement ✅
│
├─ 2. Chercher dans les skills installés (.claude/SKILLS.md) :
│      tscircuit, eda-pcb, kicad, jlcpcb, jlcpcb-component-finder
│      nextjs-supabase-auth, turborepo, bullmq-specialist
│      prompt-master
│      layrix-pcb-agent, layrix-footprint, layrix-kicad-service
│      layrix-viewer, layrix-credits, layrix-drc, layrix-prompt-improver
│      → Si trouvé → utiliser directement ✅
│
├─ 3. Chercher sur skills.sh :
│      npx skills find "query pertinente"
│      Critères de sélection :
│        - >100 installs = fiable
│        - Source connue (vercel, anthropic, etc.) = prioritaire
│        - GitHub stars > 100 = bonus
│      → Si trouvé → npx skills add owner/repo@skill -g -y
│      → Ajouter dans .claude/SKILLS.md + CLAUDE.md ✅
│
└─ 4. Créer avec skill-creator :
       Si aucun skill existant ne couvre le besoin
       Invoquer : /skill-creator:skill-creator
       Créer dans : .claude/skills/layrix-xxx.md
       → Ajouter dans .claude/SKILLS.md + CLAUDE.md ✅
```

---

## Workflow par phase

### Phase 0 — Setup infra
```
prompt-master → layrix-prompt-improver
→ turborepo (monorepo setup)
→ nextjs-supabase-auth (config Supabase)
→ everything-claude-code:postgres-patterns (migrations)
→ everything-claude-code:docker-patterns (KiCad headless)
```

### Phase 1 — Landing
```
prompt-master → layrix-prompt-improver
→ everything-claude-code:frontend-patterns (Next.js)
→ frontend-design:frontend-design (design system)
→ everything-claude-code:postgres-patterns (table waitlist)
```

### Phase 2 — Dashboard + Agent MVP
```
prompt-master → layrix-prompt-improver
→ layrix-pcb-agent (boucle orchestrateur)
→ everything-claude-code:claude-api (Claude SDK)
→ layrix-credits (déduction crédits)
→ layrix-viewer (PixiJS)
→ everything-claude-code:frontend-patterns (composants)
→ bullmq-specialist (queues Redis)
```

### Phase 3 — KiCad + Footprints
```
prompt-master → layrix-prompt-improver
→ layrix-kicad-service (FastAPI + pcbnew)
→ layrix-footprint (cascade 8 étapes)
→ layrix-drc (boucle DRC)
→ tscircuit (moteur <20 composants)
→ kicad (patterns KiCad)
→ everything-claude-code:python-patterns (FastAPI)
→ everything-claude-code:postgres-patterns (pgvector)
```

### Phase 4 — 3D + JLCPCB + Paiement
```
prompt-master → layrix-prompt-improver
→ layrix-viewer (Three.js 3D)
→ jlcpcb (commande fabrication)
→ jlcpcb-component-finder (recherche composants)
→ everything-claude-code:frontend-patterns (UI paiement)
```

### Phase 5 — Launch
```
prompt-master → layrix-prompt-improver
→ everything-claude-code:e2e (tests Playwright)
→ everything-claude-code:security-scan (audit sécurité)
→ everything-claude-code:tdd (couverture tests)
→ pr-review-toolkit:review-pr (review finale)
```

---

## Règles permanentes

| Règle | Action |
|-------|--------|
| Après chaque implémentation | Invoquer `code-reviewer` agent |
| Avant chaque commit | Invoquer `security-reviewer` agent |
| Nouveau skill utilisé | Mettre à jour `.claude/SKILLS.md` ET `CLAUDE.md` |
| Skill manquant 2 fois | Créer avec `skill-creator` |
| Instruction répétée 2 fois | Ajouter dans `CLAUDE.md` |
| Fin de session | Invoquer `/everything-claude-code:save-session` |

# Handoff — `delegation-agents-externes`

- **Status:** `IN_PROGRESS`
- **Owner:** `Claude Code`
- **Reviewer:** `none`
- **Receiver:** `human`
- **Branch:** `main`
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `f62ff71`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-08-08T00:00:00Z`

Le receiver relève le head Git courant local et distant au moment de la
réception ; ne pas le recopier ici, car le commit de ce fichier le périmerait.

## Objectif

Autoriser explicitement la délégation de tâches à des agents externes (Codex,
Kimi, Grok, Gemini) tout en garantissant que le dépôt principal et l'historique
Git ne sont modifiés que par un owner unique après vérification.

## Critère de terminaison

`COLLABORATION.md` définit le rôle d'agent externe, impose l'isolation par
worktree et interdit à un agent externe de commiter ; un modèle de brief de
délégation existe et est utilisable tel quel pour lancer une session externe.

## Périmètre autorisé

### Chemins possédés

- `docs/agents/handoffs/2026-08-08-delegation-agents-externes.md`
- `docs/agents/COLLABORATION.md`
- `docs/agents/DELEGATION_BRIEF_TEMPLATE.md`

### Lecture seule

- `docs/agents/HANDOFF_TEMPLATE.md`
- `docs/agents/handoffs/*.md`
- `CLAUDE.md`
- `AGENTS.md`

### Hors périmètre

- Tout chemin revendiqué par le handoff `2026-07-30-project-integrity`
  (`BLOCKED`, owner Codex) : migrations, routes API, tests web, handler export.
- Toute reconstruction de `011_project_integrity.sql`.
- Tout commit, push ou PR portant sur des fichiers non possédés ici.

## Modifications préexistantes non possédées

- 73 fichiers modifiés/non suivis dans le worktree principal — utilisateur et
  autres agents — préservés tels quels, ni stagés ni restaurés.
- `packages/db/supabase/migrations/011_project_integrity.sql` — Codex — **absent
  du worktree**, perte confirmée par lecture le 2026-08-08.

## Décisions prises

- Un agent externe ne devient jamais owner du dépôt principal : il produit un
  diff dans son propre worktree, jamais un commit sur `main`.
- L'isolation par worktree devient une obligation écrite et non une convention,
  car son absence a déjà causé une perte de travail documentée.
- Le protocole couvre les deux sens de délégation : brief émis depuis Claude
  Code, et session externe ouverte directement par l'utilisateur.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `git branch --show-current` | `main` | 2026-08-08 |
| `git rev-parse --short HEAD` | `f62ff71` | 2026-08-08 |
| `git status --porcelain \| Measure-Object -Line` | 73 lignes | 2026-08-08 |
| `git worktree list` | 8 worktrees actifs | 2026-08-08 |
| `Test-Path packages/db/supabase/migrations/011_project_integrity.sql` | `False` — fichier absent | 2026-08-08 |
| `Test-Path packages/db/tests/rls_isolation.sql` | `True` — 8172 octets | 2026-08-08 |
| Inventaire CLIs (`Get-Command`) | `codex`, `kimi`, `grok`, `gemini` présents ; `cursor-agent`, `opencode`, `qoder` absents | 2026-08-08 |
| `pnpm type-check` | non exécuté — aucune modification de code dans ce périmètre | 2026-08-08 |

## Risques et blocages

- Le handoff `2026-07-30-project-integrity` reste `BLOCKED` avec une migration
  de sécurité perdue ; ce handoff-ci ne le débloque pas.
- Le worktree principal reste sale (73 entrées) : tout commit doit lister des
  chemins explicites.

## Travail restant

- Décider avec l'utilisateur du premier périmètre réellement délégué.
- Traiter séparément la reconstruction de `011_project_integrity.sql`.

## Prochaine action atomique

Choisir avec l'utilisateur la première tâche déléguée et rédiger son brief
depuis `DELEGATION_BRIEF_TEMPLATE.md`.

## Git

- **État initial du worktree:** `main` sur `f62ff71`, 73 entrées modifiées ou
  non suivies appartenant à l'utilisateur et à d'autres agents.
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| 2026-08-08 | human | Claude Code | accepté | Délégation demandée avec owner unique et isolation par worktree. |

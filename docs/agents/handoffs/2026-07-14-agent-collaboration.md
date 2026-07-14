# Handoff — `2026-07-14-agent-collaboration`

- **Status:** `HANDOFF`
- **Owner:** `Codex`
- **Reviewer:** `architect sub-agent`
- **Receiver:** `Claude Code`
- **Branch:** `docs/agent-collaboration`
- **Worktree:** `<dedicated-worktree>`
- **Base commit:** `0230ebc5ba32a664f0a24fc792ec84ba4066ad2e`
- **Head commit:** `c141da3576de944aaf88f32bde115dfeb3ded7a8`
- **Updated UTC:** `2026-07-14T22:45:48Z`

## Objectif

Établir une collaboration Markdown fiable entre Claude Code et Codex sans
dupliquer ni désynchroniser les règles projet Cirqix.

## Critère de terminaison

`AGENTS.md` est un adaptateur court, les deux assistants connaissent le protocole
commun, le template de handoff est utilisable, les liens locaux résolvent et la
configuration Codex contenant des secrets est ignorée par Git.

## Périmètre autorisé

### Chemins possédés

- `AGENTS.md`
- `CLAUDE.md` — section de collaboration uniquement
- `docs/agents/COLLABORATION.md`
- `docs/agents/HANDOFF_TEMPLATE.md`
- `docs/agents/handoffs/2026-07-14-agent-collaboration.md`
- `.gitignore` — exclusion de la configuration Codex secrète uniquement

### Lecture seule

- `.claude/rules/**`
- `.claude/SKILLS.md`
- `PLAN.md`

### Hors périmètre

- Code applicatif et pipeline PCB
- Configuration locale `.claude/settings.local.json`
- Contenu et valeur des secrets dans `.codex/config.toml`

## Modifications préexistantes non possédées

- `.claude/settings.local.json` — modification utilisateur
- `docs/cirqix-full-resume.md` — modification utilisateur
- `services/kicad/kicad-tools` — état du submodule/worktree existant
- `.agents/`, `.codex/`, `.pnpm-store/` — fichiers locaux non suivis

## Décisions prises

- `CLAUDE.md` reste canonique temporairement car le projet est basé sur Claude
  et ce fichier contient la version la plus récente des règles.
- La copie de 41 Ko dans `AGENTS.md` est remplacée par un adaptateur Codex court.
- Les handoffs utilisent un fichier par tâche pour éviter un conflit sur un
  fichier global `CURRENT.md`.
- Les références Claude du runtime Anthropic restent littérales.

## Travail réalisé

- Inventaire des instructions Claude/Codex et comparaison des deux fichiers.
- Revue d’architecture indépendante par un sous-agent.
- Création de l’adaptateur, du protocole et du template partagé.
- Ajout d’une exclusion Git ciblée pour `.codex/config.toml`.
- Commit isolé poussé et pull request créée.

## Fichiers modifiés

- `AGENTS.md` — adaptateur Codex et règles de précédence.
- `CLAUDE.md` — point d’entrée vers le protocole partagé.
- `docs/agents/COLLABORATION.md` — contrat de collaboration.
- `docs/agents/HANDOFF_TEMPLATE.md` — format de transfert.
- `docs/agents/handoffs/2026-07-14-agent-collaboration.md` — état de cette tâche.
- `.gitignore` — protection de la configuration Codex locale.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `git diff --no-index --numstat AGENTS.md CLAUDE.md` avant refactor | `39 ajouts / 30 suppressions`, copie divergente confirmée | `2026-07-14T22:12:13Z` |
| Validation PowerShell des liens Markdown locaux | `tous les liens locaux résolvent` | `2026-07-14T22:19:00Z` |
| `pnpm type-check` via shim Corepack pnpm 9.0.0 | `exit 0 — 7 tâches réussies sur 7` | `2026-07-14T22:19:00Z` |

## Risques et blocages

- Un jeton Supabase personnel a été détecté dans `.codex/config.toml`; sa valeur
  n’a pas été copiée. L’ignorer empêche un futur commit, mais sa rotation externe
  reste obligatoire.
- La branche fonctionnelle d’origine contient des travaux antérieurs. Le commit
  et la PR sont donc préparés dans le worktree documentaire dédié.

## Travail restant

- Claude Code doit accepter ou refuser formellement le handoff après vérification.
- Le propriétaire du compte Supabase doit révoquer et remplacer le jeton local détecté.

## Prochaine action atomique

Révoquer le jeton Supabase local détecté, puis configurer le connecteur par variable d’environnement.

## Git

- **État initial du worktree:** sale avec modifications utilisateur préexistantes
- **État final du worktree:** seuls les metadata du handoff restent à committer
- **Commit:** `c141da3576de944aaf88f32bde115dfeb3ded7a8`
- **PR:** `https://github.com/bmechergui/cirqix/pull/49`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-14T22:12:13Z` | `Codex` | `Claude Code` | `planifié` | Transfert après commit et validations finales. |
| `2026-07-14T22:45:48Z` | `Codex` | `Claude Code` | `proposé` | Commit c141da3 et PR #49 prêts à vérifier. |

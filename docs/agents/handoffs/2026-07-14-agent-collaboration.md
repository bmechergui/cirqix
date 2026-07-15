# Handoff — `2026-07-14-agent-collaboration`

- **Status:** `HANDOFF`
- **Owner:** `Codex`
- **Reviewer:** `architect sub-agent`
- **Receiver:** `Claude Code`
- **Branch:** `docs/agent-collaboration`
- **Worktree:** `cirqix-agent-collaboration (dedicated)`
- **Base commit:** `0230ebc5ba32a664f0a24fc792ec84ba4066ad2e`
- **Content commit:** `b0317397816deb87d16ac378d84421231493f709`
- **Updated UTC:** `2026-07-15T00:09:31Z`

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
- Le handoff actif est sélectionné par branche et statut ; toute ambiguïté,
  métadonnée invalide ou `HEAD` détaché bloque les écritures.
- Le `Content commit` identifie le travail à relire et le head Git est vérifié
  dynamiquement pour éviter une référence autorécursive périmée.
- Un skill Cirqix absent de la session utilise explicitement les instructions
  versionnées sous `.claude/skills/`, sans prétendre invoquer un outil absent.

## Travail réalisé

- Inventaire des instructions Claude/Codex et comparaison des deux fichiers.
- Revue d’architecture indépendante par un sous-agent.
- Création de l’adaptateur, du protocole et du template partagé.
- Ajout d’une exclusion Git ciblée pour `.codex/config.toml`.
- Commit isolé poussé et pull request créée.
- Correction des quatre écarts de review : bootstrap skill, owner/reviewer,
  modèle `Content commit` et sélection du handoff actif.
- Ajout d’un garde fail-closed pour `HEAD` détaché et métadonnées invalides.

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
| Contrôles documentaires avant correction | `exit 1 — 5 invariants sur 5 en échec` | `2026-07-14T23:49:00Z` |
| Contrôles documentaires après correction | `exit 0 — 8 invariants sur 8 réussis` | `2026-07-15T00:04:00Z` |
| Validation des liens Markdown du diff | `exit 0 — 0 lien cassé` | `2026-07-15T00:07:00Z` |
| Scan secrets du diff | `exit 0 — 0 PAT/JWT/clé privée/chemin utilisateur` | `2026-07-15T00:04:00Z` |
| Revue architecture indépendante | `APPROVE` | `2026-07-15T00:01:00Z` |
| Revue sécurité indépendante | `PASS` | `2026-07-15T00:06:00Z` |
| `pnpm type-check` depuis le worktree principal avec dépendances installées | `exit 0 — 7 tâches réussies sur 7` | `2026-07-15T00:07:00Z` |

## Risques et blocages

- Le PAT Supabase a été retiré de la configuration locale sans être copié. Sa
  révocation externe dans le compte Supabase reste obligatoire.
- La branche fonctionnelle d’origine contient des travaux antérieurs. Le commit
  et la PR sont donc préparés dans le worktree documentaire dédié.
- Le worktree documentaire n’a pas de `node_modules` ; son premier type-check
  n’a pas démarré Turbo. La validation réussie a été exécutée depuis le worktree
  principal, dont le code applicatif est identique.

## Travail restant

- Claude Code doit accepter ou refuser formellement le handoff après vérification.
- Le propriétaire du compte Supabase doit encore révoquer l’ancien PAT dans le
  dashboard.

## Prochaine action atomique

Révoquer l’ancien PAT depuis la page des tokens du compte Supabase.

## Git

- **État initial du worktree:** sale avec modifications utilisateur préexistantes
- **État final du worktree:** propre après le commit de métadonnées ; vérifier dynamiquement
- **Commit:** contenu `b0317397816deb87d16ac378d84421231493f709` ; head PR à vérifier dynamiquement
- **PR:** `https://github.com/bmechergui/cirqix/pull/49`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-14T22:12:13Z` | `Codex` | `Claude Code` | `planifié` | Transfert après commit et validations finales. |
| `2026-07-14T22:45:48Z` | `Codex` | `Claude Code` | `proposé` | Commit c141da3 et PR #49 prêts à vérifier. |
| `2026-07-15T00:09:31Z` | `Codex` | `Claude Code` | `proposé` | Reviews APPROVE/PASS et content commit b031739 prêts à vérifier. |

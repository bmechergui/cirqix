# Handoff — `<task-id>`

- **Status:** `PLANNED | IN_PROGRESS | REVIEW | HANDOFF | BLOCKED | DONE`
- **Owner:** `Claude Code | Codex | human`
- **Reviewer:** `<agent ou none>`
- **Receiver:** `<agent ou none>`
- **Branch:** `<branch>`
- **Worktree:** `<repo-root ou identifiant logique>`
- **Base commit:** `<sha>`
- **Content commit:** `<sha, ou uncommitted uniquement avant HANDOFF>`
- **Updated UTC:** `<YYYY-MM-DDTHH:mm:ssZ>`

Le receiver relève le head Git courant local et distant au moment de la
réception ; ne pas le recopier ici, car le commit de ce fichier le périmerait.

## Objectif

<Résultat observable attendu.>

## Critère de terminaison

<Condition binaire permettant de déclarer DONE.>

## Périmètre autorisé

### Chemins possédés

- `<path>`

### Lecture seule

- `<path>`

### Hors périmètre

- `<path ou action>`

## Modifications préexistantes non possédées

- `<path — propriétaire supposé — état initial>`

## Décisions prises

- `<décision — justification>`

## Travail réalisé

- `<résultat concret>`

## Fichiers modifiés

- `<path — résumé>`

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `<commande ou non exécuté>` | `<code de sortie et résumé>` | `<timestamp>` |

## Risques et blocages

- `<risque, impact, condition de résolution>`

## Travail restant

- `<action non réalisée>`

## Prochaine action atomique

<Une seule action précise pour le receiver.>

## Git

- **État initial du worktree:** `<résumé git status>`
- **État final du worktree:** `<résumé git status>`
- **Commit:** `<sha ou none>`
- **PR:** `<URL ou none>`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `<timestamp>` | `<agent>` | `<agent>` | `<proposé/accepté/refusé>` | `<note>` |

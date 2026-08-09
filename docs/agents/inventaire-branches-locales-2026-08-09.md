# Inventaire des branches locales — 2026-08-09

État relevé après la session d'audit et de correctifs. `origin/main` = `4408648`.

> ⚠️ **Le test « ancêtre de main » ment sur ce dépôt.** Les PR sont fusionnées en
> **squash** : le sommet de la branche n'est jamais un ancêtre de `main`, même
> quand tout son contenu y est. `git merge-base --is-ancestor` renvoie donc faux
> pour des branches parfaitement intégrées. La colonne qui fait foi est l'état de
> la PR, pas la parenté Git.

## Branches à supprimer — PR fusionnée, contenu sur `main`

Leur travail est dans `main` sous un autre SHA. Suppression locale sans risque.

| Branche | PR |
|---|---|
| `fix/fail-closed-chaine-agents` | #100 |
| `fix/fail-closed-service-kicad` | #102 |
| `fix/export-fail-closed` | #103 |
| `fix/routing-mesure-reelle` | #104 |
| `fix/ls-abonnement-credits` | #106 |
| `fix/facturation-simulateur` | #107 |
| `fix/export-jamais-drc-clean` | #108 |
| `fix/pcb-state-ownership` | #109 |
| `fix/drc-pcbnew-isole` | #110 |
| `fix/webhook-idempotence-atomique` | #111 |
| `docs/corrige-thread-safety-pcbnew` | #112 |
| `docs/handoff-stm32-01-08` | #113 |
| `feat/phase-5-1-security` | #93 |
| `fix/project-integrity-hardening` | #83 |

## Branches à supprimer — PR fermée, contenu repris ailleurs

| Branche | PR | Sort |
|---|---|---|
| `fix/pipeline-fabricable-stm32` | #86 fermée | Delta moteur identique à #98 (fusionnée) ; handoff du 01/08 rapatrié par #113. **Ne jamais rebaser** : son `kct_route.py` est antérieur à #88/#90 et ferait ressusciter une version sans les réparations de vias. |
| `feat/routage-fabricable-stm32-rl-scaffold` | #95 fermée | Reconstruite en #98, fusionnée. |

## Branches temporaires

| Branche | Sort |
|---|---|
| `rebase98` | Branche de travail du rebase de #98 sur `main`. Poussée puis fusionnée. Supprimable. |

## Branches à CONSERVER — PR ouverte

| Branche | PR |
|---|---|
| `chore/graphify-multigraph` | #91 |
| `docs/bug-kicad-tools-vias-manquants` | #87 |
| `docs/rapatrie-handoffs-orphelins` | #82 |
| `fix/drc-rls-gates` | #66 |
| `feat/rl-lab-hard-gate-v2` | #99 — CI en échec, 5 `ImportError` dans le lab RL routing |

## Branches à CONSERVER — sans PR, à examiner

| Branche | Commits uniques | Remarque |
|---|---|---|
| `wip/pr95-local` | 22 | Ancienne branche de travail. Contenu moteur repris par #98 (vérifié par la présence de `convert_corners_45_drc_aware`, `allow_soldermask_bridges`, `_has_partial_result`, `_grid_too_coarse_for_clearance`, `restore_pad_angles`, `_normalize_origin_after_write`, `place_unplaced`, `_outline_bounds_local` sur `main`). Comparaison ligne à ligne **non faite** — filet à garder tant que ce n'est pas tranché. |
| `feat/placement-routing-backlog` | 22 | Même lignée que `wip/pr95-local`. |
| `fix-rls-footprints-waitlist` | 1 | Sans PR ; #101 porte le même sujet depuis `fix/rls-footprints-waitlist` (avec slash). Doublon probable — à vérifier avant suppression. |

## Branches de service — ne pas toucher

`live/codex`, `live/grok`, `live/kimi` : rattachées aux worktrees de délégation
(`C:\tmp\cirqix-live-*`). Les supprimer casserait les panneaux Pilote / Live.

`main` : à jour sur `4408648`.
`wip/post-correctifs` : branche de travail courante, alignée sur `origin/main`.

## Branches déjà contenues dans `main` (ancêtres réels)

`feat/led-full-pipeline-example`, `fix/stm32-industrial-routing`,
`validate/stm32-routing-industrial` — 0 commit unique, supprimables.

## Travail mis de côté ce jour

- **Stash** `stash@{0}` — « etat pre-correctifs wip/pr95-local du 2026-08-09 »,
  26 fichiers suivis. **Antérieurs aux PR #106-#113** : les réappliquer sur `main`
  annulerait les correctifs (`credits.ts` y contient encore `deductPipelineCost`,
  le webhook n'y a pas `credit_webhook_event`).
- **5 fichiers de test non suivis** déplacés vers
  `scratchpad/untracked-avant-bascule/` — ils bloquaient la bascule car les PR les
  ont ajoutés à `main`. Quatre diffèrent de la version fusionnée, un est identique.

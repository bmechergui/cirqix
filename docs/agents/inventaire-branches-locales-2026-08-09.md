# Inventaire des branches — local et distant — 2026-08-09

État relevé après la session d'audit et de correctifs. `origin/main` = `4408648`.

## Synchronisation local ↔ distant — VÉRIFIÉE

Les 9 branches locales comparées une à une à leur homologue distante.

| Branche locale | Local | Distant | État |
|---|---|---|---|
| `main` | `4408648` | `4408648` | ✅ synchronisée |
| `wip/post-correctifs` | `a53ebbb` | `a53ebbb` | ✅ synchronisée |
| `chore/graphify-multigraph` | `7958060` | `7958060` | ✅ synchronisée |
| `docs/rapatrie-handoffs-orphelins` | `d12f1d2` | `d12f1d2` | ✅ synchronisée |
| `fix/drc-rls-gates` | `9f6ca5e` | `9f6ca5e` | ✅ synchronisée |
| `docs/bug-kicad-tools-vias-manquants` | `554b937` | `554b937` | ✅ **corrigée** — elle était 2 commits en retard (`a63603d`), remise à niveau par `git fetch origin <branche>:<branche>` |
| `live/codex` · `live/grok` · `live/kimi` | — | **aucun distant** | ⚙️ voulu — branches de service des worktrees de délégation, elles n'ont pas à être poussées |

`git fetch --prune` a par ailleurs supprimé 5 références distantes mortes :
`feat/rl-lab-hard-gate`, `feat/rl-lab-placement-routing`, `fix/align-db-migrations`,
`fix/iteration-count-stale-guard`, `fix/reparations-court-circuit`.

**Aucun commit local non poussé. Aucun commit distant non tiré.**

## Branches distantes sans équivalent local — 20

**À conserver — PR ouverte (3)**

| Branche distante | PR |
|---|---|
| `docs/chaine-validation-stm32` | #89 |
| `feat/rl-lab-hard-gate-v2` | #99 — CI en échec, 5 `ImportError` |
| `fix/rls-footprints-waitlist` | #101 |

**✅ SUPPRIMÉES sur GitHub — 17**, chacune vérifiée juste avant (état de PR relu à
l'instant de la suppression, jamais la parenté Git). Vérifié après coup : les PR
fusionnées gardent leur commit de fusion (#98 → `2388363`, #106 → `f81214f`,
#110 → `0fc9681`, #113 → `4408648`) et les PR ouvertes restent saines.

État final : **9 branches locales, 9 distantes.**

Liste des supprimées :

Fusionnées : `fix/fail-closed-chaine-agents` #100 · `fix/fail-closed-service-kicad` #102 ·
`fix/export-fail-closed` #103 · `fix/routing-mesure-reelle` #104 · `fix/ls-abonnement-credits` #106 ·
`fix/facturation-simulateur` #107 · `fix/export-jamais-drc-clean` #108 · `fix/pcb-state-ownership` #109 ·
`fix/drc-pcbnew-isole` #110 · `fix/webhook-idempotence-atomique` #111 ·
`docs/corrige-thread-safety-pcbnew` #112 · `docs/handoff-stm32-01-08` #113 ·
`feat/phase-5-1-security` #93 · `fix/project-integrity-hardening` #83 ·
`feat/routage-fabricable-stm32-rebuilt` #98.

Fermées, contenu repris ailleurs : `fix/pipeline-fabricable-stm32` #86 ·
`feat/routage-fabricable-stm32-rl-scaffold` #95.

Leur suppression côté GitHub n'efface rien : le contenu est dans `main`, et une PR
fusionnée conserve son historique même après suppression de sa branche.

## ✅ MÉNAGE EFFECTUÉ — état final : 9 branches sur 32

**Conservées** — les quatre à PR ouverte (`chore/graphify-multigraph` #91,
`docs/bug-kicad-tools-vias-manquants` #87, `docs/rapatrie-handoffs-orphelins` #82,
`fix/drc-rls-gates` #66), les trois worktrees de délégation (`live/codex`,
`live/grok`, `live/kimi`), `main` et `wip/post-correctifs`.

**Supprimées — 23** : les 14 à PR fusionnée, les 2 à PR fermée avec contenu repris,
`rebase98`, les 3 vrais ancêtres de `main`, et les 3 examinées ci-dessous.

**Worktrees retirés — 12**, de `cirqix-analyse-*` à `cirqix-stm32-*`. Restent le
principal, celui de la PR #91, et les trois `live/*`.

**Récupéré au passage** : 4 handoffs qui n'existaient que dans des worktrees
temporaires (committés), 4 fichiers de test jamais exécutés contre le `main`
actuel (sauvegardés hors dépôt, pas committés pour ne pas casser la CI), et un
patch de 173 ko des 42 modifications de `cirqix-reconcile`.

**Pour restaurer une branche supprimée** — les commits ne sont pas détruits :
`git branch <nom> <sha>`, reflog conservé ~90 jours. SHA notés :
`wip/pr95-local` et `feat/placement-routing-backlog` = `f62ff71` ·
`fix-rls-footprints-waitlist` = `32749d8` (aussi sur GitHub via #101).

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

## Branches sans PR — EXAMEN TERMINÉ le 2026-08-09

Les trois ont été comparées au contenu réel de `main`, pas à la parenté Git.

### `wip/pr95-local` — superseded, supprimable

Le diff `origin/main → wip/pr95-local` sur `services/kicad/tools/` donne
**36 insertions pour 943 suppressions** : la branche est en RETARD, pas en avance.
Les 36 « ajouts » sont les versions *antérieures* du code — notamment le parseur
DRC/ERC tolérant qui renvoyait `[]` sur échec, précisément ce que #102 a remplacé
par un fail-closed. Les remettre serait une régression.

Vérification par symboles plutôt que par commentaires : les **28** fonctions et
constantes définies dans son `placement.py` existent toutes sur `main`. Aucun
symbole unique. Les seules chaînes absentes de `main` (« Tirages de l'Architecte »,
« irrécupérable ») sont des commentaires — #98 décrit le même mécanisme avec ses
propres mots.

Les huit fonctions clés du moteur sont sur `main` : `convert_corners_45_drc_aware`,
`allow_soldermask_bridges`, `_has_partial_result`, `_grid_too_coarse_for_clearance`,
`restore_pad_angles`, `_normalize_origin_after_write`, `place_unplaced`,
`_outline_bounds_local`.

### `feat/placement-routing-backlog` — doublon exact, supprimable

`git rev-list --count wip/pr95-local...feat/placement-routing-backlog` = **0**.
Les deux branches sont identiques. Même verdict que ci-dessus.

### `fix-rls-footprints-waitlist` — alias local, supprimable

Pointe sur `32749d8`, **exactement le même commit** que
`origin/fix/rls-footprints-waitlist`, la branche de la PR #101 ouverte. Simple
doublon local (tiret au lieu de slash). Supprimer la version à tiret ne touche pas
la PR.

## Branches de service — ne pas toucher

`live/codex`, `live/grok`, `live/kimi` : rattachées aux worktrees de délégation
(`C:\tmp\cirqix-live-*`). Les supprimer casserait les panneaux Pilote / Live.

`main` : à jour sur `4408648`.
`wip/post-correctifs` : branche de travail courante, alignée sur `origin/main`.

## Branches déjà contenues dans `main` (ancêtres réels)

`feat/led-full-pipeline-example`, `fix/stm32-industrial-routing`,
`validate/stm32-routing-industrial` — 0 commit unique, supprimables.

## Fichiers non suivis — TRIÉ le 2026-08-09

25 entrées traînaient depuis des semaines, mélangeant outillage indispensable et
cache local.

**Exclus** (`.gitignore`) : `services/kicad/models/` — **3,1 Go**, 101 archives
STEP/WRL re-téléchargeables ; `.cursor/` et `.gemini/`, adaptateurs locaux.

**Committés** (86 fichiers) : les 11 skills `*-delegate` dont dépend toute la
délégation ; `scripts/graphify-refresh.ps1`, que le hook `SessionStart` de
`.claude/settings.json` référence avec vérification d'empreinte SHA256 — il
pointait donc vers un fichier absent du dépôt ; `docs/agents/` (modèle de brief,
deux handoffs orphelins, cet inventaire) ; `examples/rl-placement-dataset/` et
`run_chaine_claire.py` ; `.graphifyignore`, `GEMINI.md`, `skills-lock.json`.

**Laissé non suivi** : `docs/kicad-tools-bug-vias-manquants.md`, déjà porté par la
PR #87 ouverte — le committer ici créerait un doublon à résoudre à la fusion.

## Travail mis de côté ce jour

- **Stash** `stash@{0}` — « etat pre-correctifs wip/pr95-local du 2026-08-09 »,
  26 fichiers suivis. **Antérieurs aux PR #106-#113** : les réappliquer sur `main`
  annulerait les correctifs (`credits.ts` y contient encore `deductPipelineCost`,
  le webhook n'y a pas `credit_webhook_event`).
- **5 fichiers de test non suivis** déplacés vers
  `scratchpad/untracked-avant-bascule/` — ils bloquaient la bascule car les PR les
  ont ajoutés à `main`. Quatre diffèrent de la version fusionnée, un est identique.

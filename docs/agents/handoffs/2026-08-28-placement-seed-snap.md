# Handoff — `placement-seed-snap`

- **Status:** `DONE`
- **Owner:** `Claude Code`
- **Reviewer:** `none`
- **Receiver:** `none`
- **Branch:** `chore/assainir-post-143` (snap fusionné via `feat/placement-seed-snap-bypass`, PR #143)
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `46de2a83`
- **Content commit:** `f394601` (squash de la PR #143)
- **Updated UTC:** `2026-09-03T19:40:00Z`

## Objectif

Le placement hybrid+cluster devient rejouable (même board → même seed → même suite de tirages) et les membres des clusters natifs POWER/TIMING sont ramenés à ≤ 5 mm de l'ancre (`FunctionalCluster.max_distance_mm`).

## Critère de terminaison

- `seed_from_board_bytes` est stable pour les mêmes octets.
- `apply_placement_seed` fixe `random` et force le GA séquentiel (pas de ProcessPool).
- `snap_cluster_members` rapproche un bypass 100 nF / VCC-GND à ≤ 5 mm de U1.
- `auto_place` applique le seed par tirage (`base + essai`) et le snap après le Géomètre.
- Les tests ciblés passent. Rien n'est stagé hors des chemins possédés.

## Périmètre autorisé

### Chemins possédés

- `services/kicad/tools/placement_seed.py`
- `services/kicad/tools/placement_bypass.py`
- `services/kicad/tools/placement.py`
- `services/kicad/routers/placement.py`
- `services/kicad/tests/test_placement_seed.py`
- `services/kicad/tests/test_placement_bypass_snap.py`
- `docs/agents/handoffs/2026-08-28-placement-seed-snap.md`

### Lecture seule

- `services/kicad/kicad-tools/src/kicad_tools/optim/`
- `services/kicad/kicad-tools/src/kicad_tools/explain/mistakes.py`
- `services/kicad/tests/test_placement.py`

### Hors périmètre

- `services/kicad/kicad-tools/` (sous-module, non stagé)
- Offset courtyard AABB / stackup 4L / Freerouting
- `CLAUDE.md` / `PLAN.md` (handoff `pcb-run-realtime` encore `REVIEW`)

## Modifications préexistantes non possédées

- `services/kicad/examples/arduino-uno/input/circuit.json`
- `services/kicad/examples/nucleo-f401/input/circuit.json`
- `services/kicad/scripts/generer_exemples.py`
- `services/kicad/kicad-tools` untracked

## Décisions prises

- Pas de patch du fork : `kct placement snap` n'est qu'une grille ; `WorkflowConfig` n'a pas de seed. On sème `random` et on force `EvolutionaryConfig.parallel=False`.
- Le snap applique le contrat natif `FunctionalCluster.max_distance_mm` (défaut 5 mm) via `detect_functional_clusters`, pas une nouvelle heuristique de détection.
- Chaque tirage de `auto_place` utilise `seed + essai` pour que le best-of-N reste exploratoire et rejouable.

## Travail réalisé

- **Snap bypass : LIVRÉ.** `tools/placement_bypass.py::snap_cluster_members`, appelé en
  étape ⑤ de `auto_place`, après le Géomètre et le halo. Fusionné dans `main` par la
  PR #143 (squash `f394601`). Mesure : 8 règles violées sur 9 avant, 0 après.
- **Seed de placement : NON FAIT, abandonné le 2026-09-03.** Le test RED
  `tests/test_placement_seed.py` importait un `tools/placement_seed.py` jamais écrit ;
  il a été retiré du dépôt. Forcer `EvolutionaryConfig.parallel=False` ralentirait
  le GA et changerait la stratégie de placement livrée : décision produit, consignée
  `en attente` dans `docs/DECISIONS.md` (D-2026-09-03-a).

## Fichiers modifiés

- `services/kicad/tools/placement_bypass.py` (nouveau)
- `services/kicad/tools/placement.py` (appel du snap en ⑤)
- `services/kicad/tests/test_placement_bypass_snap.py`, `tests/test_snap_apres_geometre.py`

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `pytest tests/test_placement_bypass_snap.py tests/test_snap_apres_geometre.py -q` | 11 passed | 2026-09-03T19:20Z |
| `pytest tests/test_placement_seed.py -q` | 1 error (collection, module absent) — test retiré | 2026-09-03T19:25Z |

## Risques et blocages

- Le Géomètre CMA-ES reste stochastique s'il a son propre RNG ; le snap final rattrape les bypass.
- Un module à origine décalée (Arduino) peut encore recouvrir un cap à 5 mm de l'origine — c'est l'offset courtyard, hors périmètre.

## Travail restant

- Aucun. Le seed attend une décision produit (D-2026-09-03-a).

## Prochaine action atomique

Aucune — handoff clos.

## Git

- **État initial du worktree:** dirty exemples + kicad-tools untracked (non possédés)
- **État final du worktree:** propre après la PR d'assainissement
- **Commit:** `f394601` (snap) · PR d'assainissement en cours
- **PR:** #143 (snap)

## Journal de transfert

- 2026-08-28 — Grok revendique seed + snap bypass sur `feat/placement-seed-snap-bypass`.
- 2026-09-03 — Claude Code reprend : snap déjà fusionné (PR #143), seed jamais commencé.
  Handoff clos, seed consigné en décision produit en attente.

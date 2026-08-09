# PLAN — RL placement (PPO vs DreamerV3 · best-of CMA)

Aligné sur [docs/rl/README.md](../README.md).
Prod inchangée tant que flag RL off.

## Rôles (rappel)

| Rôle | Qui (place) |
|------|-------------|
| **Manager** | PPO \| DreamerV3 (cible placeur) |
| **Opérateur + géométrie** | hybrid + **CMA 1×** (+ bras RL si flag) |
| **Physique** | ERROR, dérive 20 mm, hard gate |

Vocabulaire global : [../README.md](../README.md#rôles--manager--opérateur--géométrie--physique).

## Décision d’architecture (2026-08-03)

### Court terme — **prod safe** (chemin officiel)

```text
hybrid + Inspecteur → S
  → 1× CMA-ES(S)          ← refine « connu », budget fixe (prod actuelle)
  → option : RL_place(S)  ← candidat parallèle (flag)
  → filtre dérive ≤ 20 mm
  → best-of (CMA fixe vs bras RL)
  → suite routage + hard gate
```

| Règle | Détail |
|-------|--------|
| Hybrid + **1× CMA** | **Toujours** en prod ; jamais retiré |
| CMA | Un **seul** raffinement fixe (seed current, itérations/plafonds prod) |
| RL | **Candidat best-of** optionnel, **pas** pilote de CMA |
| Flag | `RL_PLACE_ALGO=off` par défaut |

### Cible RL place (objectif projet)

| Objectif | Détail |
|---------|--------|
| **Comparer PPO vs DreamerV3** | **Même env, mêmes actions, mêmes obs** |
| Encodeurs | **GNN** (prioritaire place) + **Transformer** optionnel ; CNN occupancy optionnel |
| Rôle RL | Placeur / politique de placement sur `S` (après hybrid), **pas** méta short/long/stop |
| Juge | Hard gate + best-of vs **CMA fixe** |

### Non-cible (lab historique seulement)

| Item | Statut |
|------|--------|
| RL **au-dessus** de CMA (actions short / long / stop) | **Legacy lab** — `KctPlacementEnv` + `placement_ppo_kct_v1.zip` 400 steps |
| Confondre méta-CMA et placeur RL | **Interdit** dans la doc / GO |

> Le checkpoint méta-CMA reste documenté pour traçabilité ; **il n’est pas** la feuille de route prod ni l’env de comparaison PPO↔Dreamer.

## Objectifs

1. Hard gate place/route (ERROR=0, route 100 %). **DRC=0 et unconnected_items=0
   obligatoires** ; absence de mesure = **NO-GO** fail-closed.
2. Best-of vs **CMA-ES fixe (1×)** ; jamais retirer hybrid/CMA.
3. Comparaison **PPO vs DreamerV3** sur l’env place cible (GNN ± Transformer).
4. Proxy step FOM+ERROR en lab ; sparse route si budget.

## Pipeline best-of (cible)

```text
hybrid + Inspecteur → S
  ├─ CMA-ES 1× (S)              ← toujours (prod)
  └─ RL_place(S) si flag        ← PPO | Dreamer (même contrat env)
→ filtre dérive ≤ 20 mm
→ best-of
→ suite routage
```

## Étapes

### P0 — Baseline moves (fait, legacy)

- [x] `PlacementEnv` + PPO multi-board v2
- [x] Gate A NO-GO vs CMA (0/6) — **legacy label**

### P1 — Méta-CMA lab (fait, **legacy — non feuille de route**)

- [x] `KctPlacementEnv` : actions CMA short/long/stop (**méta-contrôleur**)
- [x] Tests mock ; CLI `--env kct`
- [x] force_refine si ERROR
- [x] Train 400 steps → `models/placement_ppo_kct_v1.zip`

> Conservé pour tests / smoke. **Ne pas étendre** comme cible PPO vs Dreamer.

### P2 — Eval legacy (livré lab, **legacy gates**)

- [x] Eval multi-board FOM/ERROR — **historique legacy**
- [x] eval_route_arms percent — **historique legacy**
- [ ] Hard gate place+route **toutes** cartes + DRC mesuré

#### Résultats historiques legacy (non éligibles au GO déploiement)

| ID | Mesure | Résultat | Label |
|----|--------|----------|--------|
| L-A | Gate A majority FOM/ERROR | 5/6 pass (ex. 200/400 runs) | **legacy** |
| L-B | Gate B mean % / count 100% | 6/6 tie 100% | **legacy** — peut cacher ERROR place |
| L-ckpt | Checkpoint méta-CMA | 400 steps | lab only |

Ne plus cocher « GO prod = GO-A et GO-B ».

### P3 — Env place cible (PPO ↔ Dreamer) — **prochaine**

- [ ] Env placement **hors** short/long/stop : actions / obs placeur (GNN ± Transformer)
- [ ] Train / eval **PPO** sur cet env
- [ ] Train / eval **DreamerV3** sur le **même** env
- [ ] Best-of vs **CMA 1×** fixe (même S hybrid)
- [ ] Hard gate sur suite officielle

### P4 — Intégration prod

- [ ] Flag `RL_PLACE_ALGO=off|ppo|dreamer`
- [ ] Best-of prod path (CMA 1× toujours en lice)
- [ ] GO seulement hard gate (README global Phase 5–6)

## Critères de sélection (cible — hard)

| Priorité | Critère |
|----------|---------|
| 1 | `error_conflicts=0` sur **chaque** board |
| 2 | Aval route hard gate (100 % ; **DRC=0 et unconnected=0 obligatoires**, non mesuré = NO-GO) |
| 3 | Compétitif vs **CMA 1×** (FOM/WL) **après** 1–2 |
| 4 | Coût train/inférence (PPO vs Dreamer) |

Critères **legacy** (majority FOM, mean ERROR) : documentation historique uniquement.

## Encodeurs (place)

| Composant | Rôle |
|-----------|------|
| **GNN** | Encodeur **prioritaire** place (composants / nets) |
| **Transformer** | Glue optionnelle (séquence / global) |
| **CNN** | Occupancy locale optionnelle |
| Tête | PPO (transition) ou DreamerV3 (cible world model) |

Schéma global : [../README.md](../README.md#réseaux-options-encodeur).

## Commandes lab

Méta-CMA **legacy** (ne pas traiter comme cible) :

```bash
# Depuis services/kicad
python -m tools.rl.placement.train_placement \
  --pcb-dir examples/rl-placement-dataset/boards \
  --env kct --kct-backend cmaes --algo ppo --steps 400 \
  --out models/placement_ppo_kct_v1.zip \
  --resume models/placement_ppo_kct_v1.zip

python -m tools.rl.placement.eval_vs_cmaes \
  --pcb-dir examples/rl-placement-dataset/boards \
  --model models/placement_ppo_kct_v1.zip \
  --rl-env kct --kct-backend cmaes \
  --out-json tmp/rl_vs_cmaes_place.json
```

Env moves (ancien) :

```bash
python -m tools.rl.placement.train_placement \
  --pcb-dir examples/rl-placement-dataset/boards \
  --algo ppo --steps 100000 \
  --out models/placement_ppo_v2.zip
```

## Boucle si NO-GO

1. Hard gate instrumentation (DRC)
2. Data / reward / encodeur GNN
3. Resume train PPO puis Dreamer (même env)
4. Abandon après 3 tours sans progrès hard — **hybrid + 1× CMA seul**

## Règles

- Best-of toujours (CMA 1× reste candidat)
- Dérive max 20 mm
- Juge final : hard gate + outils kicad, pas proxy RL seul
- **Pas** de RL méta short/long/stop comme architecture cible
- Comparer **PPO vs DreamerV3** avant tout GO place

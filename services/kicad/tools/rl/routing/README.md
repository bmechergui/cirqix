# RL routing — module programme (routeur direct)

> Spec et plan : [`docs/rl/routing/PLAN.md`](../../../../docs/rl/routing/PLAN.md)  
> Vue d’ensemble : [`docs/rl/routing/README.md`](../../../../docs/rl/routing/README.md)

## Architecture (cible vs actuel)

Voir aussi [`docs/rl/README.md`](../../../../docs/rl/README.md) § Architecture cible.

| Couche | Cible | Aujourd’hui (v1) |
|--------|--------|------------------|
| Routage local | **CNN / U-Net + RL** (+ Transformer opt.) | **PPO + MLP** (`MlpPolicy`) |
| Routage global | **GNN + RL** (ordre nets) | non |
| Baseline / filet | **`kct route`** + best-of | **`kct route`** |

## But

**Modèle RL qui route** : à partir d’un `.kicad_pcb` **déjà placé**, la policy
pose segments / vias (grille `RoutingGrid`), pas un second placement.

```text
PCB placé (ex. led-blinker output/5_placed.kicad_pcb)
  → env Gymnasium (routeur local PPO)
  → export .kicad_pcb candidat
  → gate : routed_percent → 100 %, DRC kicad-cli → 0
  → best-of vs kct route  → livrer le meilleur
```

## Différence avec placement

| Module | Fait |
|--------|------|
| `tools/rl/placement/` | Bouger composants (X/Y), FOM / ERROR |
| `tools/rl/placement/eval_route_arms.py` | Place déjà fait → **route classique** `route_kct` (mesure) |
| **`tools/rl/routing/`** | **RL qui trace** les pistes (modèle routeur) |

## Organisation

```text
tools/rl/routing/
  README.md          ← ce fichier
  board_grid.py      ✅ RoutingGrid + obs 8 canaux
  actions.py         ✅ 8 moves + via + finish
  reward.py          ✅ barème PLAN
  env.py             ✅ RoutingEnv Gymnasium (1 net / épisode)
  export.py          ✅ path → segments sur .kicad_pcb
  train_routing.py   ✅ PPO / random smoke
  eval_vs_kct.py     ✅ même board → RL vs kct route

tests/
  test_rl_routing_board_grid.py  ✅
  test_rl_routing_env.py         ✅

models/
  routing_ppo_vN.zip     # local, gitignoré

tmp/
  rl_routing_vN_*.json
```

### Smoke env + train + eval

```bash
cd services/kicad
python -m pytest tests/test_rl_routing_board_grid.py tests/test_rl_routing_env.py -q

# Random step-rate smoke
python -m tools.rl.routing.train_routing --algo random --steps 2000

# PPO train (LED 5_placed) — cible 100k
python -m tools.rl.routing.train_routing \
  --algo ppo --steps 100000 \
  --out models/routing_ppo_v1.zip \
  --metrics-json tmp/rl_routing_v1_100k_metrics.json

# Comparer RL vs kct route (même board placé)
python -m tools.rl.routing.eval_vs_kct \
  --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \
  --model models/routing_ppo_v1.zip \
  --out-json tmp/rl_routing_vs_kct_100k.json
```

## Résultats lab vs `kct route` (LED `5_placed`)

Fixture : `examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb`.  
Modèle : `models/routing_ppo_v1.zip` (PPO+MLP).  
Rapport 100k : `tmp/rl_routing_vs_kct_100k.json`.

| Train | kct `routed_percent` | RL proxy (nets OK / 6) | Verdict |
|-------|----------------------|-------------------------|---------|
| Smoke ~5k | **100 %** | **17 %** (1/6) | NO-GO — garder kct |
| ~50k | **100 %** | **17 %** (1/6) | NO-GO — garder kct |
| **100k** (2026-07-31) | **100 %** | **17 %** (1/6) | **NO-GO — garder kct** |

- RL : collapse `FINISH_NET` immédiat (steps=0) sur 5/6 nets ; seul `TRIG_THR`
  “réussit” (pads déjà proches).
- **Prod** : `kct route` seul. RL routing = lab jusqu’à upgrade CNN + reward
  anti-collapse + re-gate 100 % / DRC 0.

## Première fixture

```text
services/kicad/examples/led-blinker-full-pipeline/
  output/5_placed.kicad_pcb          # entrée train
  expected/led_blinker_final.kicad_pcb  # baseline 100 % / DRC-clean
  input/schema.json                  # 6 nets
```

## Invariants

- `kct route` **jamais supprimé** (baseline + fallback).
- Candidat RL livré seulement si gates DRC / unconnected OK.
- Best-of : mean 100 % + DRC 0 + WL — garder le meilleur bras.

# RL placement — organisation du module (lab)

> Spec produit / boucle d’amélioration : [`docs/rl/placement/PLAN.md`](../../../../docs/rl/placement/PLAN.md)  
> Vue d’ensemble : [`docs/rl/placement/README.md`](../../../../docs/rl/placement/README.md)

## Règle en une phrase

**Code + tests versionnés** · **dataset d’exemples versionné** · **modèles & résultats de run locaux** (gitignorés) · **1 zip officiel par version**.

---

## Carte des chemins

```text
services/kicad/
│
├── tools/rl/placement/          ← CODE (à garder, versionné)
│   ├── README.md                ← ce fichier
│   ├── env.py                   ← Gymnasium PlacementEnv (mouvements)
│   ├── observation.py           ← tenseur d’état
│   ├── reward.py                ← FOM kicad-tools
│   ├── conflicts.py             ← ERROR PlacementAnalyzer
│   ├── generate_dataset.py      ← génère les boards synthétiques
│   ├── train_placement.py       ← train / resume PPO
│   ├── eval_vs_cmaes.py         ← Gate A (+ Gate B --route plus tard)
│   └── __init__.py
│
├── tests/                       ← TESTS unitaires (versionnés)
│   ├── test_rl_placement_env.py
│   ├── test_rl_placement_reward.py
│   └── test_rl_placement_gate.py
│
├── examples/rl-placement-dataset/   ← DATASET (versionné)
│   ├── manifest.json
│   ├── boards/*.kicad_pcb           ← train / eval multi-board
│   └── hybrid_snapshots/            ← (à venir) sorties post-hybrid
│
├── models/                      ← CHECKPOINTS (gitignoré) — 1 zip utile
│   ├── placement_ppo_v2.zip         ← modèle courant (Gate A fait)
│   └── placement_ppo_vN.zip         ← prochaines versions
│
└── tmp/                         ← ARTEFACTS DE RUN (gitignoré, jetables)
    ├── rl_ppo_v2_metrics.json
    ├── rl_vs_cmaes_v2.json
    └── rl_vs_cmaes_v2_art/          ← boards RL/CMA-ES par fixture
```

Docs (hors `services/kicad`, versionnés) :

```text
docs/rl/placement/
├── README.md    ← but, pipeline best-of, gates
└── PLAN.md      ← étapes, objectif 100%/DRC/WL, boucle d’amélioration
```

---

## Que garder / que jeter

| Élément | Garder ? | Où |
|---------|----------|-----|
| Code env / reward / obs / conflicts | **Oui** | `tools/rl/placement/*.py` |
| `generate_dataset.py` | **Oui** | idem |
| `train_placement.py` | **Oui** | idem |
| `eval_vs_cmaes.py` | **Oui** | idem |
| Tests `test_rl_placement_*.py` | **Oui** | `tests/` |
| Dataset `examples/rl-placement-dataset/` | **Oui** | boards + manifest |
| `placement_ppo_v2.zip` | **Oui** (lab) | `models/` — base fine-tune v3 |
| `*_ckpts/` (ts5000, ts10000…) | **Non** une fois train `completed` | supprimer |
| `tmp/rl_*_smoke*` | **Non** | supprimer |
| Anciens `rl_smoke_*.json`, `rl_ppo_10k.json` | **Non** | supprimer |
| `tmp/rl_vs_cmaes_v2.json` + `_art/` | **Oui temporairement** | preuve Gate A v2 |

**NEVER** committer `models/*.zip` ni `tmp/` (déjà dans `.gitignore`).

---

## Rôles des scripts (commandes depuis `services/kicad`)

### 1. Dataset

```bash
python -m tools.rl.placement.generate_dataset
# → examples/rl-placement-dataset/boards/*.kicad_pcb + manifest.json
```

### 2. Train

```bash
python -m tools.rl.placement.train_placement \
  --pcb-dir examples/rl-placement-dataset/boards \
  --algo ppo --steps 100000 \
  --out models/placement_ppo_v2.zip \
  --metrics-json tmp/rl_ppo_v2_metrics.json
```

- **1 zip principal** = `--out`  
- Copies `*_ckpts/` = secours pendant le train → **à effacer** quand `status=completed`

### 3. Eval vs CMA-ES (Gate A) — placement

```bash
python -m tools.rl.placement.eval_vs_cmaes \
  --pcb-dir examples/rl-placement-dataset/boards \
  --model models/placement_ppo_v2.zip \
  --out-json tmp/rl_vs_cmaes_v2.json \
  --artifact-dir tmp/rl_vs_cmaes_v2_art
```

### 3b. Gate B — routage des placements déjà faits

Prend les boards `arm_cmaes_result` / `arm_rl_result` et lance **`route_kct`**
(prod) pour comparer `routed_percent` :

```bash
python -m tools.rl.placement.eval_route_arms \
  --artifact-dir tmp/rl_vs_cmaes_v2_art \
  --timeout-s 120 \
  --out-json tmp/rl_vs_cmaes_v2_routed.json \
  --out-art tmp/rl_vs_cmaes_v2_art_routed
```

### 4. Tests

```bash
python -m pytest tests/test_rl_placement_env.py tests/test_rl_placement_reward.py tests/test_rl_placement_gate.py -q
```

---

## Convention de nommage

| Type | Pattern | Exemple |
|------|---------|---------|
| Modèle | `placement_ppo_v{N}.zip` | `placement_ppo_v2.zip` |
| Metrics train | `tmp/rl_ppo_v{N}_metrics.json` | |
| Eval Gate A | `tmp/rl_vs_cmaes_v{N}.json` | |
| Artefacts boards | `tmp/rl_vs_cmaes_v{N}_art/` | |
| Eval Gate B (futur) | `tmp/rl_vs_cmaes_v{N}_routed.json` | |

Une **version = un zip + un JSON eval** (voir PLAN boucle d’amélioration).

---

## Ce que le modèle utilise (runtime lab)

| Besoin | Fichier / outil |
|--------|-----------------|
| Env de déplacement | `env.py` + Gymnasium |
| Board | kicad-tools `PCB` (pas pcbnew en train) |
| Score step | `reward.py` → `compute_fom` |
| Collisions | `conflicts.py` |
| Algo | SB3 PPO charge `models/placement_ppo_vN.zip` |
| Comparaison | `eval_vs_cmaes.py` + `_refine_with_cmaes` (prod Géomètre) |

---

## État lab (2026-07-30)

| Item | État |
|------|------|
| Dataset 6 boards | OK |
| `placement_ppo_v2.zip` | train 100k **completed** |
| Gate A vs CMA-ES | **NO-GO** (0/6) — rapport `tmp/rl_vs_cmaes_v2.json` |
| Gate B / reward route | pas encore implémenté |
| Prod `auto_place` | **hybrid + CMA-ES** ; RL non branché |

Prochaine version utile : **v3** (fine-tune + hybrid snapshots + reward sparse route) — nouveau zip `placement_ppo_v3.zip`, pas 15 copies.

# RL phases — statut (2026-08-05 night closure)

> Prod Cirqix **inchangée**. Flag prod RL = **OFF** (Phase 6).
> Evidence lab tonight: place clean LED + full `route_kct` hard gate **GO**
> (scratch + `examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb`).

## Contrat hard gate (ne pas contredire)

| Fait | Détail |
|------|--------|
| Module | `services/kicad/tools/rl/quality_gate.py` |
| Branché | `eval_route_arms.py` **et** `run_phase_pipeline.py` (après route) |
| Exit pipeline | 0 seulement si hard gate **passed** (sauf skip flags) |
| `unrouted_count` | **Pas** obligatoire par défaut (`require_unrouted_count=False`) |
| DRC / unconnected | **Obligatoires** ; non mesuré (`kicad-cli` absent) = **NO-GO** fail-closed |
| Filet | `Schematic.validate` + `kct check --mfr jlcpcb` (kicad-tools only) |
| Autorité fab | `kicad-cli` sur **worker** — jamais chez l’utilisateur |

## Verdict audit — NO-GO production (flag)

| Bras | Rôle réel | Verdict |
|------|-----------|---------|
| Placement PPO+kct méta | short/long/stop (legacy) | Lab only / NO-GO prod |
| Placement RL cible GNN | PPO vs Dreamer | **TODO** / NO-GO |
| Routage grille PPO | ~17 % | NO-GO |
| Routage PPO+kct 3 actions | Sélecteur full-board | NO-GO |
| Manager `kct_net` PPO | code + smoke ; train court faible | Lab / **non prod** |
| Lab LED full kct after place fix | hard gate **GO** (mesure) | **Lab GO** ≠ flag prod |

**GO-A / GO-B historiques = legacy.** Phase 6 reste **OFF**.

## Tableau phases (0–6) — statut honnête ce soir

| Phase | Objectif | Statut |
|-------|----------|--------|
| **0** | Prod gelée + docs | **DONE** |
| **1** | Env kct + route_net API | **DONE lab** — mock + `kct_net` + `kct_full` proxy ; tests verts |
| **2** | Place RL (cible placeur GNN / PPO↔Dreamer) | **PARTIAL** — prod path hybrid+**1× CMA** + Inspecteur ; méta-CMA legacy ; **GNN/Dreamer place non livrés**. LED place fix → 0 ERROR (lab) |
| **3** | Route manager + KCT | **PARTIAL** — `kct_net` livré + multi-pad ; greedy ~67–83 % ; full `route_kct` 100 % sur LED clean ; PPO mock 8k ; **PPO vs Dreamer non fait** |
| **4** | Manager + FR fallback | **TODO** — pas d’étape 2 FR manager ; interim `kct_alt` only |
| **5** | Pipeline intégré + hard gate | **PARTIAL** — hard gate branchée ; **lab GO** mesuré sur LED clean+full kct (ERROR=0, 100 %, DRC=0, unconn=0) ; CI Docker/kicad-cli encore host-dependent |
| **6** | Flag prod RL | **OFF** — hard-gate lab GO n’active pas le flag prod sans e2e multi-board + politique produit |

### Preuve lab (2026-08-05)

| Item | Résultat |
|------|----------|
| LED place before | `error_conflicts=2` (U1/C2 pad clearance) |
| After `_resolve_remaining_conflicts` / PlacementFixer | **`error_conflicts=0`** |
| Board | `examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb` |
| Full `route_kct` | **100 %** |
| Hard gate | **`passed: true`** — reasons `[]` |
| Evidence files (session scratch) | `place_errors.json`, `hard_gate_full_kct.json`, `pytest_rl.txt` |
| Tests | `test_rl_route_net_api` + `test_rl_manager_env` + `test_rl_led_place_fix` |

### Détail livrables routage

| Livrable | Statut |
|----------|--------|
| API/mock `route_net` | **livré** |
| Proxy `kct_full` | **livré, lab-only** |
| `kct_net` (`--nets` + `--preserve-existing`) | **livré** |
| multi-pad net filter | **livré** |
| PPO manager mock | `routing_ppo_manager_mock_v2.zip` (8k) |
| PPO manager kct_net | smoke/v1 32 steps — **non validé** hard gate |
| DreamerV3 manager | **non livré** |
| Manager + FR | **non livré** |

## Placement — état modèle

| Item | Valeur |
|------|--------|
| Prod safe | hybrid → **1× CMA** + Inspecteur ; RL flag **OFF** |
| Cible | PPO vs Dreamer ; GNN±Transformer ; best-of vs CMA 1× |
| Non-cible | RL méta short/long/stop |
| Checkpoint legacy | `placement_ppo_kct_v1.zip` 400 steps |

## Routage — état modèle

| Item | Valeur |
|------|--------|
| Full kct LED (clean place) | **100 %** possible (stochastique ; un run host 2026-08-06 a fait 80 % puis 100 %) |
| Greedy kct_net (place clean) | **83 %** (5/6 nets) — GND sans cuivre tant que zone-fill kicad-cli manquant |
| PPO manager kct_net v1 (32 steps) | **0 %** — policy invalid slots (net_slot 16/21) ; non validé |
| PPO manager mock 8k | policy partielle (~17 % mock multi-pad) |
| Hard gate host sans kicad-cli | **NO-GO fail-closed** (DRC/unconnected non mesurés) même à 100 % kct |

### Lab host 2026-08-06 — manager + kct_net + hard gate

| Item | Résultat |
|------|----------|
| Script | `python -m tools.rl.routing.eval_manager_kct_net` |
| Input | `examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb` |
| Place ERROR | **0** (already clean) |
| Arm `full_kct` (suite multi-bras) | 80 % (OUT unrouted) ; re-run solo **100 %** (vcc traces et planes) |
| Arm `greedy_kct_net` | **83 %** winner multi-bras ; GND success=false (zones fill need kicad-cli) |
| Arm `ppo_manager_kct_net` (`routing_ppo_manager_kct_net_v1.zip`) | **0 %** / 32 actions hors nets valides |
| kicad-cli | **absent** host — zones fill rc=1 ; DRC non mesuré |
| Hard gate | **NO-GO** — `routed_percent<100` (winner 83 %) **et** DRC/unconn non mesurés |
| phase6_ready / prod flag | **false** / **OFF** |
| Report | `services/kicad/tmp/rl_mgr_kct_net_led/report.json` |
| Unit tests | `tests/test_rl_eval_manager_kct_net.py` (6 passed) |

### Lab host 2026-08-08 — action-space fix + manager v2

| Item | Résultat |
|------|----------|
| Fix | `ManagerRoutingEnv` : action space = `n_nets × N_STRATEGIES + stop` (plus 32 slots fantômes) |
| Train mock | `routing_ppo_manager_kct_net_v2_mock.zip` — **16 384** steps sur LED clean |
| Mock rollout | **100 %** manager (5/5 seeds, slots 0–5) |
| Fine-tune kct_net | partiel / interrompu (host lent ; zone-fill sans kicad-cli) |
| Eval v2 report | `tmp/rl_mgr_kct_net_led_v2/report.json` |
| Place ERROR | **0** |
| full_kct solo | **official 100 %** ; estimate S-expr **83 %** (plans non remplis) |
| greedy estimate | **83 %** |
| PPO v2 → kct_net (8 steps) | **0 %** — collé `net_slot=2` / `vcc_planes` (pas de crédit cuivre) |
| Hard gate | **NO-GO** — pas 100 % (metric estimate) **+** DRC/unconn non mesurés |
| phase6 / prod | **false** / **OFF** |
| Tests | `test_rl_manager_env` + `test_rl_eval_manager_kct_net` **14 passed** |

## Roadmap restante (après ce soir)

1. **Host/worker avec kicad-cli** : zone-fill + DRC officiel pour hard-gate mesurable
2. Phase 3 : plafond greedy/kct_net 100 % (GND/zones) ; **train manager sur kct_net réel** (mock→kct_net transfer encore 0 %)
3. Anti-boucle policy : ne pas rejouer le même (net, strategy) sans succès
4. Phase 2 placeur GNN / PPO↔Dreamer (pas méta-CMA)
5. Phase 4 : manager + FR
6. Phase 5 : hard gate GO multi-board + CI kicad-cli
7. Phase 6 : flag prod **seulement** après multi-board GO

## Stratégies KCT

> Taxonomie Cirqix **proposée** — mapping partiel ; non copiée de l’article.

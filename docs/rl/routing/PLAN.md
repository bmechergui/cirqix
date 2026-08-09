# PLAN — RL routing : manager (Dreamer/PPO) + opérateur KCT / FR

Aligné sur [docs/rl/README.md](../README.md).

## Objectifs

1. Hard gate (contrat global README) — **autorité uniquement où branchée**.
2. **Étape 1** : comparer **PPO vs DreamerV3** + opérateur **KCT** → choisir le manager principal.
3. **Étape 2** : comparer **PPO vs DreamerV3** + opérateur **FR** → choisir le fallback.
4. PPO et Dreamer = **même env/actions/obs** *par* opérateur (env KCT, puis env FR).
5. Best-of vs baseline kct full ; hard gate 100 % lab.

## Rôles

| Composant | Rôle |
|-----------|------|
| **PPO** | **Manager** candidat (transition) |
| **DreamerV3** | **Manager** candidat (cible world model) |
| **KCT** | **Opérateur principal** + géométrie (`kct_net` / batch) |
| **FR** | **Opérateur fallback** + géométrie (étape 2 — reprise partielle) |
| **kct_alt** | Interim secours KCT en attendant bras manager+FR |
| Hard gate / DRC | **Physique** / juge GO |
| Reasoner | Filet prod si % &lt; 100 |

Vocabulaire canonique : [../README.md](../README.md#rôles--manager--opérateur--géométrie--physique).

### Ordre de travail

```text
1) PPO vs Dreamer  +  KCT   →  retenir Manager_KCT
2) PPO vs Dreamer  +  FR    →  retenir Manager_FR  (après 1)
Pipeline : Manager_KCT + KCT  →  (si besoin) Manager_FR + FR  →  hard gate
```

### Strategy

> Taxonomie Cirqix **proposée** — **non implémentée** dans KCT,
> **non** extraite fidèlement de l’article (100 actions publiques non documentées Java).

Voir README global pour la table proposée (`shortest`, `low_vias`, …).

## Prod vs lab (ne pas confondre)

| | Production (`/route/auto`) | Lab RL cible |
|--|----------------------------|--------------|
| KCT | Sur boards simples ; accept **≥ 95 %** | Step manager ; hard gate vise **100 %** |
| FR | Si besoin ; souvent depuis **PCB entrée** clean | Reprise **partielle** post-kct (cible) |
| Reasoner | Si résultat &lt; 100 % | Filet après manager |

## Étapes

### R0 — Grille (fait, NO-GO)

- [x] PPO grille 100k → 17 % vs kct

### R1 — Sélecteur 3 actions (fait, **legacy**)

- [x] `KctRoutingEnv` / `FrRoutingEnv`
- [x] Train mock/real smoke
- [ ] Ne plus étendre comme cible Dreamer

### R1b — `route_net` (mock + **kct_net** par net)

- [x] Spec + mock TDD — `tools/rl/routing/route_net_api.py`
- [x] Backend `kct_full` proxy temporaire (full board) + **sync `MockRouterState`**
- [x] Backend **`kct_net`** — `route_kct_net` / `kct route --nets NAME` (kicad-tools)
- [x] Tests mock + `kct_full` + `kct_net` mockés
- [x] `estimate_routed_percent_from_pcb` (utilitaire PCB ; bras secondaire = kct_alt)
- [ ] Stratégies riches (layer / ripup géométrique) encore partielles

### R1c — Env manager (minimal fait)

- [x] `ManagerRoutingEnv` — net_slot × strategy + stop
- [x] Reward mock + tests `tests/test_rl_manager_env.py` (incl. `kct_full` progress)
- [ ] Obs spatiale (canaux)

### R2 — PPO-transition sur ManagerRoutingEnv

- [x] CLI `--env manager --kct-backend mock` (et `kct_full` proxy)
- [x] Smoke test `tests/test_rl_train_manager.py` (skip si pas SB3)
- [x] Train lab mock → `models/routing_ppo_manager_v1.zip` + **`routing_ppo_manager_mock_v2.zip` (8k steps)**
- [x] Train smoke kct_net → `routing_ppo_manager_kct_net_v1.zip` (32 steps — policy faible)
- [x] Baseline greedy kct_net LED → **67–83 %**, hard gate **NO-GO** (GND/VCC planes fragiles ; ERROR place **2** partagé)
- [x] Best-of LED : **full `route_kct` 100 %** vs greedy `kct_net` 67 % → **winner full_kct** ; hard gate encore NO-GO (ERROR=2, DRC=6) — *historique pre-clean*
- [x] Fix place ERROR (2) sur LED placed — `5_placed_clean` + `test_rl_led_place_fix` (0 ERROR)
- [x] Eval lab 2026-08-06 : `eval_manager_kct_net` — place clean · greedy **83 %** · PPO v1 **0 %** · hard gate **NO-GO** (pas 100 % + pas kicad-cli DRC)
- [ ] **Entraînement validé** hard gate GO (phase manager **non DONE** ; checkpoint kct_net v1 inutilisable)
- [ ] PPO manager long **seulement** après place clean + plafond per-net viable + **kicad-cli** ; interim = full kct pour plafond route

### R3 — Étape 1 : DreamerV3 + KCT (après PPO validé sur kct_net)

- [ ] Même env que PPO manager
- [ ] Comparaison PPO vs Dreamer sous hard gate + opérateur KCT
- [ ] Retenir **Manager_KCT**

### R4 — Étape 2 : Manager + FR (fallback)

- [ ] Env manager branché sur opérateur FR (reprise partielle)
- [ ] Comparaison **PPO vs Dreamer** + FR
- [ ] Retenir **Manager_FR** ; pipeline KCT → FR
- [ ] Interim : `kct_alt` jusqu’à R4 livré

### R5 — Intégration

- [x] `run_phase_pipeline.py` skeleton
- [x] **Hard gate dans pipeline** (`evaluate_final_hard_gate`)
- [x] Hard gate dans `eval_route_arms`
- [x] FR % = connectivité PCB (pas 50 % hardcodé)
- [ ] DRC mesurable en CI (kicad-cli) → Phase 5 peut sortir de PARTIAL

## Hard gate (rappel honnête)

| Check | Défaut code |
|-------|-------------|
| error_conflicts | obligatoire |
| routed_percent ≥ 100 | obligatoire |
| unrouted_count | **optionnel** (`require_unrouted_count=False`) |
| DRC / unconnected | obligatoire fail-closed si non mesuré |

## Commandes legacy sélecteur

```bash
python -m tools.rl.routing.train_routing \
  --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \
  --env kct --kct-backend mock --algo ppo --steps 512 \
  --out models/routing_ppo_kct_legacy_selector.zip
```

## Règles

- Pas de déploiement sur GO-B percent-only
- Timeouts durs
- Préférence kct full à égalité best-of

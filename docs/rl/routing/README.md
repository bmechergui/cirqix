# RL routing — manager + opérateur KCT

> Plan : [PLAN.md](PLAN.md) · Global : [../README.md](../README.md)

## But

Hard gate (quand instrumentée) : 100 % route, DRC/unconnected clean.
Séparer **manager RL** et **opérateur** géométrique (KCT).

## Rôles (route)

| Rôle | Qui |
|------|-----|
| **Manager** | **PPO** ou **DreamerV3** — on **compare** les deux (même env par opérateur) |
| **Opérateur principal** | **KCT** (`kct_net` / `route_net` / batch) |
| **Opérateur fallback** | **FR** (cible étape 2 ; interim lab = `kct_alt`) |
| **Physique / juge** | %, DRC, unconnected, hard gate |

### Objectif — 2 étapes

| Étape | Comparaison | Opérateur | But |
|-------|-------------|-----------|-----|
| **1** | **PPO vs DreamerV3** | **KCT** | Choisir le **manager** principal |
| **2** | **PPO vs DreamerV3** | **FR** | Choisir le **fallback** manager+FR |

```text
Étape 1 : Manager(PPO|Dreamer) + KCT  →  hard gate / best-of
Étape 2 : Manager(PPO|Dreamer) + FR   →  hard gate / best-of  (après étape 1)

Pipeline cible :
  Manager* + KCT  →  si insuffisant  →  Manager† + FR  →  hard gate
```

- Un manager à la fois par bras en prod.
- KCT/FR **n’exécutent que** la géométrie ; PPO/Dreamer **décident**.
- Vocabulaire : [../README.md](../README.md#rôles--manager--opérateur--géométrie--physique).

## Architecture cible

```text
Manager (Dreamer|PPO) → action {net, strategy…}
  → KCT (kct_net / route_net ; kct_full = proxy lab)
  → si fail hard → Manager + FR (étape 2) ; interim = kct_alt
  → reasoner prod si encore < 100 %
```

## Strategy

Taxonomie **proposée Cirqix** (mapping KCT partiel, non extraite de l’article).
Détail : [../README.md](../README.md).

## Article DreamerV3+FR

Manager imagine / ordre nets ; FR exécute (paper).  
Cirqix : **même rôle manager** ; opérateur principal **KCT** d’abord ;  
fallback **FR** = étape 2 (comparaison PPO vs Dreamer **aussi** sur FR).

## Lab v1 legacy (NO-GO prod)

3 actions full-board kct ; mock train 512 ; real 16 steps.
Hard gate dans `eval_route_arms` **et** `run_phase_pipeline` (exit code).

## Statut livrables (ne pas confondre)

| Livrable | Statut |
|----------|--------|
| API + mock `route_net` | **livré** |
| Proxy `kct_full` (1× full-board) | **livré, lab-only, non incrémental** |
| Vrai routage géométrique par net (`kct_net`) | **livré** — `route_kct_net` / `kct route --nets` |
| `ManagerRoutingEnv` + PPO manager mock | **code + train mock** ; train **non validé** hard gate / `kct_net` réel |
| Bras secondaire lab (ex-« FR ») | **`route_kct` kicad-tools** (`vcc_as_traces=False`) — **pas** pcbnew |

## Prochaine code

1. ~~Hard gate Phase 5 pipeline~~ fait
2. ~~API/mock `route_net` + ManagerRoutingEnv + PPO mock~~ fait
3. ~~Sync état `kct_full` + bras secondaire kct_alt~~ fait
4. ~~`kct_net` géométrique par net (`--nets`)~~ fait
5. ~~Eval lab manager + kct_net + hard gate~~ fait (`tools/rl/routing/eval_manager_kct_net.py`) — **NO-GO** 2026-08-06 (greedy 83 %, PPO v1 0 %, pas kicad-cli)
6. ~~Action space dynamique + train mock v2 16k~~ fait — mock **100 %** ; transfer kct_net encore **0 %** (2026-08-08)
7. **Étape 1b** : worker **kicad-cli** (zone-fill + DRC) ; train manager **sur kct_net réel** (pas seulement mock) ; viser hard gate GO
8. **Étape 1** : Dreamer vs PPO sur KCT sous hard gate
9. **Étape 2** : bras manager + **FR** ; comparer PPO vs Dreamer sur FR

### Eval lab (commande)

```bash
cd services/kicad
python -m tools.rl.routing.eval_manager_kct_net \
  --pcb examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb \
  --model models/routing_ppo_manager_kct_net_v1.zip \
  --out-dir tmp/rl_mgr_kct_net_led
```
7. kicad-cli en CI pour DRC mesurable

## Ce qu’on ne fait pas

- Déployer sélecteur 3 boutons
- Confondre prod (accept 95 % simple) et hard gate lab (100 %+DRC)
- Présenter GO-B percent-only comme GO déploiement
- Déclarer la phase manager **DONE** tant que le train n’est pas validé hard gate

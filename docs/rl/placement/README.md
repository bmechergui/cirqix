# RL placement — PPO vs DreamerV3 · best-of vs CMA 1×

> Plan : [PLAN.md](PLAN.md) · Global : [../README.md](../README.md)

## But

Candidat d’amélioration **après** hybrid+Inspecteur, en **best-of** contre le
raffinement CMA **fixe (1×)**.  
**hybrid + CMA-ES restent toujours.** Flag prod **OFF**.

Objectif scientifique / produit : **comparer PPO et DreamerV3** sur le **même**
env de placement (encodeurs **GNN** + **Transformer** optionnel).

## Rôles (place)

| Rôle | Qui |
|------|-----|
| **Manager** | **PPO** ou **DreamerV3** (cible placeur ; même env pour comparer) |
| **Opérateur + géométrie** | **hybrid + CMA 1×** (prod) ; bras RL optionnel (flag) |
| **Physique / juge** | ERROR place, dérive ≤ 20 mm, hard gate aval |

- CMA 1× = opérateur **fixe**, pas piloté par le RL.
- RL **n’est pas** le pilote short/long/stop de CMA (legacy seulement).
- Vocabulaire global : [../README.md](../README.md#rôles--manager--opérateur--géométrie--physique).

## Architecture (décision 2026-08-03)

### Prod safe (court terme)

```text
hybrid + Inspecteur → S
  ├─ CMA-ES 1× (S)          ← toujours (refine connu, budget fixe)
  └─ RL(S) si flag          ← option best-of (PPO|Dreamer — cible)
→ filtre dérive ≤ 20 mm
→ best-of
→ suite routage
```

- CMA = **un seul** raffinement prod (pas piloté par le RL).
- RL **n’est pas** au-dessus de CMA (pas short/long/stop comme design cible).

### Cible RL (feuille de route)

| | |
|--|--|
| Algorithmes | **PPO** (transition) vs **DreamerV3** (cible) — même env |
| Encodeurs | **GNN** prioritaire ; **Transformer** optionnel ; CNN optionnel |
| Sortie | Placement candidat sur `S` |
| Sélection | Best-of vs CMA 1× + hard gate |

### Lab historique (legacy — ne pas confondre)

| | |
|--|--|
| `KctPlacementEnv` | actions CMA short/long/stop = **méta-contrôleur** |
| `placement_ppo_kct_v1.zip` | 400 steps lab only |
| Statut | **Legacy** ; non GO ; non objectif PPO↔Dreamer |

## Autorité de jugement (contrat global)

| Mécanisme | Autorité déploiement ? |
|-----------|-------------------------|
| **Hard gate** (`quality_gate.py`) | **Oui** (quand branchée + DRC/unconnected mesurés) |
| Gate A FOM/ERROR majority | **Non** — **legacy** |
| Gate B percent-only | **Non** — **legacy** |

**GO prod placement RL** = hard gate sur **toutes** les cartes de la suite officielle
+ best-of vs **CMA 1×** + aval route sous hard gate.  
**Pas** « GO-A et GO-B » historiques. **Pas** « méta-CMA 400 steps ».

### Résultats historiques (legacy — non éligibles au GO)

| Mesure | Résultat |
|--------|----------|
| Gate A multi FOM | 5/6 (board 05 faible) — **legacy** |
| Gate B % 100 | 6/6 tie — **legacy** (peut coexister avec ERROR place) |
| Checkpoint méta-CMA | `placement_ppo_kct_v1.zip` **400** steps |

## Encodeurs

| Rôle | Archi |
|------|--------|
| Place | **GNN** prioritaire |
| Glue | **Transformer** optionnel |
| Local | CNN occupancy optionnel |
| Policy / world model | PPO \| DreamerV3 |

Détail : [../README.md](../README.md#réseaux-options-encodeur).

## Ce qu’on ne fait pas

- Supprimer hybrid / **1× CMA** prod
- Faire du RL un **pilote** CMA (short/long/stop) comme architecture cible
- Déployer sur GO-A/B legacy ou checkpoint 400 steps
- Comparer PPO et Dreamer sur des envs différents

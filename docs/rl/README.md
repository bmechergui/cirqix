# RL PCB — proposition Phase 6

Ce dossier décrit une évolution future du pipeline PCB Cirqix. Il ne modifie
pas le pipeline de production actuel : `kicad-tools` reste la baseline et le
fallback, tandis que KiCad 10 reste le juge final.

## Deux politiques séparées

| Politique | Rôle | Position dans le pipeline |
|---|---|---|
| [RL placement](placement/README.md) | Optimiser les positions X/Y des composants non ancrés | Après le placement hybride et son premier contrôle de conflits |
| [RL routing](routing/README.md) | Tracer directement les segments et vias d'un net | Après le placement validé, avant le DRC final |

Les deux politiques produisent seulement des **candidats**. Un candidat n'est
jamais livré sans les quality gates réels : analyse de placement, routage,
puis DRC officiel `kicad-cli pcb drc --format json`.

## Ordre de livraison

1. RL placement Phase 6a : PPO/MLP, candidat comparé au snapshot pré-RL.
2. RL routing sur le LED : une carte, deux couches, trois nets.
3. Extension du routeur RL à des cartes simples de 5 à 10 composants.
4. RL placement Phase 6b : encodeur GNN seulement après la preuve PPO/MLP.
5. Cartes STM32 et multicouches seulement après des résultats DRC reproductibles.

La procédure de démarrage est documentée dans
[l'exemple LED](routing/README.md#processus-led-pour-le-routeur-rl-direct).

## Invariants non négociables

Un résultat est accepté uniquement si :

```text
routing_complete = true
unrouted_count = 0
violations KiCad 10 = 0
unconnected_items KiCad 10 = 0
```

Un pourcentage annoncé par un optimiseur ou un routeur n'est jamais une preuve
suffisante de fabricabilité.

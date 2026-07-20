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

## Choix d'algorithme : PPO v1, DreamerV3 seulement sur preuve

Les deux politiques utilisent **PPO** (Stable-Baselines3) en v1. DreamerV3 est
écarté pour une raison structurelle : sa valeur est l'efficacité
d'échantillons quand chaque pas d'environnement coûte cher (world model +
entraînement en imagination). Or le surrogate tourne à ~10–50 µs/pas : les pas
sont quasi gratuits, l'avantage disparaît et il ne reste que les inconvénients
(stack JAX lourde ou portages torch non officiels, hyperparamètres sensibles,
débogage difficile, coût par pas supérieur).

- Placement : état compact, reward dense (FOM), épisodes courts — cas d'école
  PPO/MLP.
- Routing : si l'observabilité partielle de la grille exige de la mémoire,
  l'étape intermédiaire est **RecurrentPPO** (LSTM, sb3-contrib), pas un
  world model.

DreamerV3 n'est réexaminé que si l'une de ces conditions est mesurée :

1. l'entraînement doit se faire contre l'environnement réel KiCad (pas
   coûteux → l'efficacité d'échantillons redevient décisive) ;
2. PPO et RecurrentPPO plafonnent sur les cartes 5–10 composants (credit
   assignment long horizon) ;
3. le gap surrogate/réel impose un modèle appris de la dynamique.

Rôle de FreeRouting : baseline de comparaison aux côtés de `kct route`
(export DSN/SES) et source optionnelle de **behavioral cloning** pour
pré-entraîner la politique avant PPO. Jamais dans la boucle de pas RL :
trop lent.

## Critères d'échec et d'abandon

Chaque phase est une expérience avec un critère d'arrêt, pas un engagement.
Une phase qui échoue est abandonnée et le pipeline actuel reste inchangé :

- Phase 6a (placement PPO/MLP) : abandonnée si le candidat RL ne bat pas le
  FOM CMA-ES de plus de 5 % sur au moins 10 fixtures après l'expérience
  initiale, ou si l'inférence dépasse le budget par requête.
- RL routing LED : abandonné si le critère de passage quantifié de
  [routing/README.md](routing/README.md#critère-de-passage-au-board-suivant)
  n'est pas atteint après un budget d'entraînement fixé à l'avance.
- Phases suivantes : non démarrées tant que la phase précédente n'a pas
  produit un résultat DRC reproductible et quantifié.

Un échec documenté est un résultat valide : il ferme la piste RL et justifie
l'investissement dans le routeur déterministe existant.

## Coûts estimés

Ordres de grandeur à valider par un smoke run avant chaque phase. Hypothèses :
1 GPU grand public (classe RTX) ou 16 cœurs CPU, Stable-Baselines3 PPO/MLP,
cartes de 10 à 30 composants.

### Phase 6a — RL placement

- Entraînement : 1 à 5 M de pas PPO, pas surrogate à ~2–5 ms
  (calcul FOM `kicad-tools`) → **2 à 8 h GPU par expérience**.
- Inférence : épisode de 100 à 500 déplacements, forward MLP < 1 ms →
  **< 1 s par candidat**, négligeable face au budget CMA-ES actuel.

### RL routing LED

- Entraînement : 10 à 100 M de pas surrogate (grille 2 couches, 3 nets,
  pas ~10–50 µs vectorisé) → **12 à 48 h GPU par run**.
- Évaluations réelles : `kicad-cli pcb drc` ≈ 5–15 s sur le LED ; cadence
  1 checkpoint sur 20, checkpoint tous les 100 k pas → ~5 évaluations par
  run de 10 M de pas, **plafond 50 évaluations par run** (< 15 min au total).
- Inférence : épisode de 1 à 10 k pas → quelques secondes par candidat.

### Maintenance

- Modèles versionnés avec le commit `kicad-tools` et la version KiCad ayant
  servi à l'entraînement.
- Réentraînement complet requis après tout changement du FOM, des règles
  de design ou de la version majeure de KiCad : rejouer le budget
  d'entraînement ci-dessus.

Ces chiffres sont des estimations initiales : le premier smoke run (100 k pas)
doit mesurer le débit réel du surrogate et la durée réelle du DRC, puis cette
section est mise à jour avec les valeurs mesurées.

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

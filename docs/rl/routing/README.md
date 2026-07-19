# RL routing — routeur direct avec validation KiCad

## But

RL routing trace directement les segments et vias. Il ne se limite pas à
choisir le placement ou l'ordre des nets. `kct route` reste disponible comme
baseline et fallback, mais la politique RL construit le chemin d'un net.

## Architecture hiérarchique

Un seul agent qui choisit simultanément le net, la couche, les vias et chaque
pas sur une grande carte apprend trop difficilement. La proposition sépare :

```text
Contrôleur : choisit le net actif, la paire de pads et la couche de départ
Routeur local : avance sur une grille multicouche et pose segments/vias
Validateur rapide : rejette collisions, keepouts et sortie de carte
Validateur final : KiCad 10 DRC sur le .kicad_pcb écrit
```

## Observation du routeur local

Chaque couche cuivre est un ensemble de canaux rasterisés :

```text
1. pads source/cible du net actif
2. cuivre déjà posé du même net
3. cuivre des autres nets
4. courtyards, composants et keepouts
5. Edge.Cuts et marge cuivre-bord
6. congestion locale
7. position actuelle du curseur
8. carte de distance vers la cible
```

## Actions directes

```text
north | south | east | west
switch_layer
place_via
finish_net
```

Une action ne modifie le PCB que si le validateur rapide confirme largeur,
clearance, couche, contour et géométrie autorisée. Les actions invalides restent
dans l'épisode, reçoivent une pénalité et n'écrivent aucun cuivre.

## Reward

```text
+1000  pad cible réellement atteint
 -2    par pas de grille
-20    par via
-500   collision, clearance ou keepout interdit
-1000  net abandonné ou épisode sans connexion
```

Le reward accélère l'entraînement ; il n'est pas une preuve de succès. La seule
preuve est le DRC officiel après écriture du PCB.

## Double environnement

| Environnement | Usage | Validateur |
|---|---|---|
| `surrogate` rapide | millions de pas PPO | géométrie/grille en mémoire |
| `real` | évaluation de chaque checkpoint | PCB écrit → `kicad-cli pcb drc --format json` |

KiCad 10 et `kct route` ne sont pas exécutés à chaque pas RL : ils seraient trop
lents. Ils évaluent les candidats complets et empêchent le modèle d'optimiser
seulement un simulateur imparfait.

## Processus LED pour le routeur RL direct

Le dernier exemple est le terrain d'apprentissage initial :
`services/kicad/examples/led-blinker-full-pipeline/`.

```text
1. Prendre input/circuit.json et le PCB placé comme fixture immuable.
2. Construire une grille deux couches avec les trois nets : VCC, LED_ANODE, GND.
3. Entraîner d'abord un épisode par net, sans via.
4. Entraîner ensuite les trois nets dans un ordre choisi par le contrôleur.
5. Exporter les segments gagnants vers un .kicad_pcb temporaire.
6. Lancer kct route seulement comme baseline de comparaison.
7. Lancer kicad-cli pcb drc --format json.
8. Copier dans output/ uniquement un candidat avec 0 violation et 0 unconnected item.
```

Les artefacts d'expérimentation proposés sont :

```text
services/kicad/examples/led-blinker-full-pipeline/output/rl-routing/
├── episode_metrics.jsonl
├── candidate.kicad_pcb
├── kicad_drc.json
└── summary.json
```

## Point d'intégration proposé

```text
services/kicad/tools/rl/routing/
├── env.py
├── board_grid.py
├── actions.py
├── reward.py
├── policy.py
├── exporter.py
└── validate.py
```

Dans `routers/routing.py`, RL est derrière un feature flag. Il produit un
candidat ; si celui-ci ne passe pas les gates, le pipeline existant utilise
`kct route`, puis le placement-feedback actuel si le routage reste incomplet.

## Critère de passage au board suivant

Le LED ne doit être quitté qu'après des runs reproductibles qui satisfont :

```text
routing_complete = true
unrouted_count = 0
KiCad 10 violations = 0
KiCad 10 unconnected_items = 0
```

Le STM32 n'est introduit qu'après cette preuve sur le LED et des cartes simples
de complexité intermédiaire.

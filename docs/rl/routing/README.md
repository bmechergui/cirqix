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
ne | nw | se | sw            # diagonales 45°, obligatoires pour les
                             # évasions de pads fine-pitch
switch_layer
place_via
finish_net
```

Le pas de grille est fixé par design à la résolution du routage visé (par
exemple 0,1 mm sur le LED) et consigné dans la configuration de
l'environnement. Un routeur purement Manhattan est explicitement insuffisant
au-delà du LED : les actions diagonales font partie de l'espace d'actions de
base, pas d'une extension ultérieure.

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
| pré-filtre candidat | tri avant évaluation réelle | DRC natif `kicad-tools` (27 règles JLCPCB) |
| `real` | évaluation de chaque checkpoint | PCB écrit → `kicad-cli pcb drc --format json` |

Le DRC natif `kicad-tools` sert de pré-filtre sur les candidats : il tourne en
local, bien plus vite que `kicad-cli`, et écarte les candidats visiblement
mauvais avant l'évaluation réelle. Il ne remplace jamais le juge final —
conformément à la matrice de disponibilité de `routers/drc.py`, kicad-tools
niveau 1 ne court-circuite jamais `kicad-cli`, qui fait seul foi sur les
invariants d'acceptation.

KiCad 10 et `kct route` ne sont pas exécutés à chaque pas RL : ils seraient trop
lents. Ils évaluent les candidats complets et empêchent le modèle d'optimiser
seulement un simulateur imparfait.

L'évaluation réelle est cadencée et budgétée à l'avance : un DRC `kicad-cli`
prend plusieurs secondes, donc l'évaluation porte sur un checkpoint tous les
N checkpoints d'entraînement (N fixé par expérience, typiquement 10 à 50), avec
un plafond d'évaluations par run. La cadence et le plafond sont consignés dans
`summary.json`.

## Génération d'environnements d'entraînement

Entraîner sur une fixture immuable (le LED) produit une politique qui apprend
cette carte, pas le routage. Le LED sert uniquement de terrain d'apprentissage
initial et de preuve de concept instrumentée.

Pour les étapes 3+ du plan de livraison, un générateur procédural de boards
est requis : composants placés aléatoirement, densités et tailles de carte
variées, 2 à 10 composants, nets tirés selon des profils simples (power,
signal, bus). Le générateur réutilise les fixtures et le format
`circuit.json` existants, et chaque board généré est validé par
`kicad-cli pcb drc` avant d'entrer dans le corpus d'entraînement.

## Hors scope v1

La v1 du routeur RL ne traite pas :

- les paires différentielles (USB D+/D- et autres `sensitive_nets`) ;
- le length matching intra-bus ou intra-paire ;
- les contraintes RF (impédance contrôlée, stubs).

Ces nets restent routés par `kct route` ou marqués à router manuellement. Les
retirer de l'observation du routeur RL v1 évite un reward inatteignable.

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

« Reproductible » est quantifié : 10 épisodes consécutifs réussis sur chacune
des 3 seeds d'entraînement (30/30 au total), avec les métriques de
`episode_metrics.jsonl` à l'appui. Un succès intermittent ne débloque pas la
carte suivante.

Le STM32 n'est introduit qu'après cette preuve sur le LED et des cartes simples
de complexité intermédiaire.

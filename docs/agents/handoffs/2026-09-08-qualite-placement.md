# Plan de correction — la qualité de placement n'est pas celle d'un ingénieur

**Ouvert le 2026-09-08.** Owner : Claude Code. Branche : `fix/qualite-placement`.

Constat de l'utilisateur, capture à l'appui : *« le placement, c'est un placement
d'amateur, les cartes ne sont pas pro d'un ingénieur senior »*. Il a raison, et
chaque reproche se chiffre. Ce document ne conserve que des mesures.

---

## Les cinq défauts, mesurés

### D1 — Une paire à DEUX bornes finit à 87 mm

Une LED et sa résistance série partagent un net qui ne touche qu'**elles deux**.
C'est la paire la plus serrable qui existe sur une carte. Mesure sur les onze
cartes du banc (`\.captures/paires.py`) :

| carte | paires | moyenne | pire |
|---|---|---|---|
| carte-01 | 2 | 5,3 mm | 7,7 mm |
| carte-04 | 3 | 11,9 mm | 14,1 mm |
| carte-07 | 12 | 20,7 mm | **32,6 mm** (D13-R13) |
| carte-08 | 20 | 36,0 mm | **67,6 mm** (D12-R12) |
| carte-09 | 20 | 43,1 mm | **87,1 mm** (D10-R10) |
| carte-10 | 20 | 44,7 mm | **71,6 mm** (D1-R1) |

Un ingénieur pose ces deux-là à 2-3 mm. **La dégradation suit la taille de la
carte** — 5 mm à 5 composants, 45 mm à 70 : ce n'est pas du bruit, c'est le GA
qui disperse d'autant plus qu'il a de place.

⚠️ **CAUSE, et pourquoi le snap ne l'attrape pas.** Le snap
(`tools/placement_bypass.py`) ne traite que les clusters rendus par
`detect_functional_clusters` — POWER, TIMING, DRIVER, INTERFACE. Une paire
résistance-LED n'appartient à **aucun** de ces types : elle n'est jamais vue,
donc jamais serrée. Le snap fonctionne ; il ne regarde simplement pas là.

C'est le prolongement exact de la limite déjà inscrite dans CLAUDE.md
(« `FunctionalCluster` n'a qu'UNE ancre : rien ne contraint la distance entre
deux MEMBRES »), en pire : ici la paire n'est même pas un cluster.

### D2 — Presque aucun composant n'est sur une grille

| carte | sur grille 0,5 mm | orientations cardinales |
|---|---|---|
| carte-04 | **1 / 15** | 15 / 15 |
| carte-07 | **2 / 44** | 44 / 44 |
| carte-10 | **2 / 70** | 70 / 70 |
| nucleo-f401 | **0 / 55** | 55 / 55 |
| stm32-100 | **1 / 100** | 100 / 100 |

Les orientations sont propres (tout est à 0/90/180/270). Les **positions** ne le
sont pas : elles tombent au centième de millimètre, là où le GA les a laissées.
C'est la signature visuelle que l'utilisateur voit immédiatement — rien n'est
aligné avec rien.

⚠️ Un alignement sur grille n'est PAS cosmétique : il rend les rangées de
passifs parallèles, donc les pistes parallèles, donc le routage plus court. Mais
il se pose **après** l'optimisation, jamais pendant : arrondir des positions peut
créer un chevauchement, donc l'Inspecteur doit repasser derrière.

### D3 — La sortie d'un régulateur sur un net orphelin

`carte-07-multi-io`, boîtier `U2` (AMS1117-3.3, SOT-223-3_TabPin2) :

    schéma   +3V3 = [U2.2, C3.1, R1.1, ... 18 broches]      ← correct
    board    pad 2 → Net-(U2-2)   ·   languette → Net-(U2-2) ← orphelin

**Le schéma est juste.** C'est la génération du board qui perd l'assignation.
Le régulateur alimente donc… rien, et le DRC n'y voit aucune connexion manquante
puisque l'orphelin est un net à part entière — la famille de défauts que ce dépôt
poursuit depuis une semaine.

⚠️ **Intermittent** : `carte-02` et `carte-04` ont le MÊME boîtier, le même
symbole et la même structure de net, et sortent correctes (`+1V8`, `+3V3`).
Trois régénérations de `carte-07` reproduisent le défaut à l'identique. Ce n'est
donc pas un tirage malheureux ; quelque chose distingue ces schémas.

⚠️ Le boîtier a **deux pastilles numérotées 2** (la broche et la languette). Toute
correction doit les traiter ensemble : c'est le même nœud électrique.

### D4 — La sérigraphie se chevauche partout

`carte-07` : `silk_over_copper:11`, `silk_overlap:15` sur 29 violations. Sur les
tirages rejetés, jusqu'à `silk_over_copper:44, silk_overlap:22`. Aucune n'est une
erreur de fabrication — mais c'est ce qui rend les captures illisibles, et c'est
la première chose qu'un relecteur humain voit.

### D5 — Le fichier de PLACEMENT n'est pas livré

`expected/` ne contient que `final.kicad_pcb` (routé), `journal.txt`,
`mesures.json` et `rendu-3d.png`. Demande explicite de l'utilisateur :
*« je veux toujours voir le fichier placement et routage »*. Le board placé non
routé est aussi le **témoin** indispensable — sans lui on impute au routage des
défauts qui préexistaient, faute déjà commise dans ce dépôt.

---

## Ce qui N'EST PAS un défaut, vérifié

Deux reproches ne se confirment pas à la mesure, et il faut le dire :

- **Aucun composant au dos.** Les dix-huit cartes ont `0 / N` empreintes sur
  `B.Cu`. Tout est en face avant.
- **Aucun composant hors contour.** `0` sur les dix-huit.
- **Aucune carte à 6 couches.** Toutes les cartes livrées sont à **2 couches**.
  L'escalade existe (`_layer_ladder` 2→4→6→8) mais n'a servi sur aucune carte
  livrée — le banc du 2026-09-03 le disait déjà : « aucune escalade de couches
  n'a servi ».

Ce que les captures montrent et qui ressemble à ces défauts est la **dispersion**
(D1) : des composants isolés loin de tout donnent l'impression d'être hors carte.

---

## Le plan

### Lot A — le placement (le cœur du reproche)

1. **A1 · Serrer les paires à deux bornes.** Étendre le snap au-delà des clusters
   natifs : tout net qui ne touche que deux boîtiers est une contrainte
   d'adjacence. Plafond à proposer, à valider par l'utilisateur (décision
   produit : c'est un seuil chiffré qui change le comportement livré).
   ⚠️ L'ordre est contraint : après le Géomètre et après le halo, comme le snap
   existant — sinon il est défait. Garde de câblage obligatoire.
2. **A2 · Aligner sur grille après optimisation.** Arrondi des positions à 0,5 mm
   (ou 1 mm), puis Inspecteur, puis annulation si un conflit apparaît.
3. **A3 · Espacer la sérigraphie.** Décaler les textes de référence, pas les
   composants.

### Lot B — la génération du board

4. **B1 · Trouver pourquoi `carte-07` perd `+3V3`** et poser une garde : aucune
   pastille ne doit porter un net `Net-(<ref>-<pin>)` quand le schéma lui donne
   un nom. C'est mesurable sans exécuter le pipeline.

### Lot C — la livraison

5. **C1 · Versionner le board PLACÉ** (`expected/2_placement.kicad_pcb`) à côté du
   routé, plus les deux vues SVG de chacun.

### Lot D — le grand banc

6. **D1 · Une carte de référence réelle** (type `astra_piNas`) importée comme
   dix-neuvième cas : un board dessiné par un humain, pour comparer nos sorties à
   une référence qui n'est pas de nous.

---

## Journal

- **2026-09-08** — diagnostic ci-dessus, mesuré sur les 18 cartes. Aucun
  correctif encore appliqué.

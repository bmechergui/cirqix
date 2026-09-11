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

---

## Ce qui est LIVRÉ (2026-09-08, soir)

### B1 — la cause racine du net perdu : un piège de FORME, le onzième

`_patch_floating_nets` (`tools/pcb.py`) répare les nets orphelins. Elle ne
réparait rien, dans **trois expressions indépendantes** :

    (net 3 "GND")     ← kicad-tools, et KiCad ≤ 9      ← la seule acceptée
    (net "GND")       ← pcbnew de KiCad 10             ← ce que produisent TOUS nos boards

Mesure : `carte-02` numérotés=0 nus=93 · `carte-07` 0/570 · `carte-10` 0/988,
`generator_version "10.0"` partout. `net_id_to_name` était donc TOUJOURS vide et
la fonction rendait son entrée inchangée, sans un mot.

⚠️ C'est le MÊME piège que `_NET_DECL_RE` le 2026-08-20 — corrigé là-bas, jamais
ici. **Quand une forme de fichier trompe une expression, chercher SES SŒURS.**

⚠️ **UN SECOND DÉFAUT SE CACHAIT DERRIÈRE LE PREMIER.** Le découpage des
pastilles s'arrêtait sur `\n\t)` — UNE tabulation. pcbnew 10 en écrit deux, et
la dernière pastille d'un boîtier y est suivie de `(embedded_fonts no)` : la
**dernière pastille de chaque empreinte** n'était jamais réparée. Ma première
correction fut pire — s'arrêter au premier `\n\s*(` coupait le bloc AVANT le
champ `(net …)`. Une expression trop large et une trop étroite échouent
identiquement, en silence. On compte désormais les parenthèses.

Vérifié sur les onze boards réels : **16 pastilles d'alimentation** retrouvent
leur net, `carte-04/05/07/08/09/10` passent de 2-4 perdues à **0**.

### A1 + A2 — les deux leviers natifs jamais passés

`OptimizationWorkflow`, celui que nous appelons déjà :

| levier | où | défaut | effet du défaut |
|---|---|---|---|
| `constraints=[GroupingConstraint]` | `optim/workflow.py:244` → `add_grouping_constraints` (333) | jamais passé | paires à 101 mm |
| `WorkflowConfig.grid` | `optim/workflow.py:187` → `snap_to_grid` (348) | `0.0` = aucun snap | 2/62 alignés |

Les contraintes ne sont pas décoratives : `compute_constraint_forces`
(`optim/placement.py:1297`) entre à l'**étape 5** du calcul de forces (1783).
Vérifié dans le code, pas supposé.

Jamais appelés non plus, et à explorer ensuite : `optim/alignment.py`
(`align_components`, `distribute_components`), `optim/constraint_loader.py` —
dont l'exemple de documentation est littéralement `status_leds` alignées et
ordonnées — et `optim/bottom_up_placement.py`, une méthode **non-génétique** qui
groupe par motif, dispose dans chaque groupe, puis pose les groupes en blocs.
C'est la méthode d'un ingénieur, elle est dans la bibliothèque, rien ne l'utilise.

### Trois restrictions, chacune payée par une mesure

- **Pas les rails d'alimentation** — `GND` relie tout à tout.
- **Pas les concentrateurs** (`_PADS_MAX_PAIRE = 4`) — `carte-09` a 38 paires
  dont **20 de la forme `R<n>-U1`** : coller le MCU à vingt résistances est
  insatisfiable, le solveur aurait arbitré au hasard entre des ressorts
  contradictoires. Un placement pire, pas meilleur.
- **Pas les nets à trois bornes** — pas de « bonne » distance évidente.

### L'ORDRE, encore

`grid=0.5` transmis n'a **rien changé** : 2/62 avant, 2/62 après. Le natif aligne
en fin d'optimisation, puis le Géomètre, le halo, le snap et l'Inspecteur
déplacent tout. L'alignement est donc reposé **en dernier**
(`aligner_sur_grille`), avec le filet du snap — réparation native, retour arrière
si le compte d'erreurs monte.

Mesuré sur le board placé réel de `carte-09` : **2/62 → 62/62**, et
**0 erreur avant comme après**.

Les paires, elles, entrent dans le **même parcours** que le snap des clusters
(`_PaireEnSerie`), jamais en second passage : deux passages successifs se
défont l'un l'autre, piège déjà mesuré deux fois dans ce dépôt.

### Effet des contraintes seules, mesuré avant le snap dur

    paires   moyenne 55,3 → 35,7 mm      max 100,9 → 62,7 mm

Un vrai gain (−35 %), et insuffisant seul : ce sont des forces, et le dépôt
mesure déjà qu'elles sont dominées par les rails GND. D'où le serrage dur.

## Décisions produit EN ATTENTE de validation

Deux seuils chiffrés qui changent le comportement livré. Posés pour permettre la
mesure, **non validés** :

- `_GRILLE_MM = 0.5` — pas de la grille de placement
- `_RAYON_PAIRE_MM = 5.0` — rayon de rappel d'une paire en série

## État au 2026-09-10 (commits `133d690`, `510f959`, `9b8094c`)

- **GND est routé par défaut** (pistes + plan, comme la référence STM32
  d'Astra et `docs/methodologie-routage.md`) ; le confier au plan est un
  réglage (`gnd_confie_au_plan`). Suite verte : 1636 passed.
- **Les `RemoteDisconnected` sont expliqués et corrigés** : uvicorn abattait
  le worker qui relisait 564 Mo de journal Freerouting (GIL > 5 s). Lecteur
  incrémental `tools/journal_freerouting.py`. Trois diagnostics faux avant —
  lire `docs/DECISIONS.md`, section rectifiée.
- **Découplage** : chaque capa va au CI le plus proche sur son rail
  (`_reattribuer_les_decouplages`) et le snap POWER vise la BROCHE
  (`_pastille_partagee`). carte-05 : 7,1 → 2,5 mm mesuré, pas encore livré.
- Cartes 01-04 et 06 livrées 100 % / 0 erreur avec `placement.kicad_pcb`.
- Campagne en cours : `/tmp/campagne-1789040706` (11 cartes × 2), à livrer
  par `scripts/livrer_campagne.py` — **ne remplace que si meilleur**.

## État au 2026-09-11 matin (commits `24689b4` → `f9288dc`)

- **Placement structuré, étape 2 livrée** (`0baf8d0`) : un `GroupingConstraint`
  natif par CI (ses découplages à corps + 3 mm) entre dans le GA. Mesure sur
  carte-09 (62 composants), même board généré : découplage **19,0 → 4,2 mm**
  (max 28,8 → 7,4), paires 34 → 37 mm (bruit). Objectif ≤ 5 mm atteint.
- **Escalade incrémentale validée et réparée** : deux défauts rendaient
  4 couches pires que 2 — padstack de via codé `Via[0-1]` (jeté par
  Freerouting à 4/6 couches), pistes protégées sans leurs vias. Corrigés
  (`f9288dc`), mesure en cours sur carte-10/08.
- Livré cette nuit : carte-09 100 % / 0 erreur / 2 couches. carte-08 et 10 :
  98 % avec le routage d'aujourd'hui ; leur 100 % du 07/09 était un tirage
  chanceux (bissection : ancien code 98 % en 8 min).
- Livrés depuis : carte-07 100 % / 0 err / 2 couches (`36770a2`), carte-08
  100 % / 0 err à 6 couches puis, avec +20 % de contour, à 2 couches.
- **D-2026-09-11-b validée et livrée (`0971706`)** : une carte qui stagne à
  son plafond de couches est agrandie de 20 % (≤ 2 fois) ; le service rend le
  contour à la taille demandée. Campagne de mesure : `/tmp/campagne-1789150495`
  (08, 09, 10), service redémarré avant (module importé ≠ fichier monté).
- **Soirée du 2026-09-11 — GND à 98 %** : cause mesurée (GND dans 60/60
  verdicts ratés), trois règles générales livrées (`8ac00df` → `2176dde`) :
  repli GND ciblé itératif, tronçon du via réservé protégé, pastille sans
  raccord promue en connexion pleine, protection bornée à 80 % à l'escalade,
  empreinte du module au chargement. Détail : `docs/pipeline-placement-routage.md`.
  Campagne de mesure en cours : `/tmp/campagne-1789161948`.
- **Fork kicad-tools rebasé (`075dfe27`) : NON validé** — 9 conflits de
  placement non résolus à chaque tirage sur carte-05, 0 sur le fork courant.
  Détail et suspects dans `services/kicad/DEPENDENCIES.md`. Gitlink inchangé.

## Reste à faire

- **Placement structuré, étapes 1, 7, 8** : graine hiérarchique par grappes
  (réglage `graine_hierarchique`, à mesurer), échange de place quand l'anneau
  du CI est occupé, `kct placement align/distribute` pour les rangées LED/R.
- **C1** — livrer `expected/placement.kicad_pcb` pour les onze cartes (le
  mécanisme existe, `scripts/livrer_placements.py` ; 01-06, 09 couvertes, les
  autres attendent la campagne ci-dessus).
- **A3** — espacer la sérigraphie (`silk_over_copper`, `silk_overlap`).
- **D1** — la carte de référence réelle, type `astra_piNas`.
- Régénérer les onze cartes avec les correctifs.

# Banc « driver LLM » — dix cartes, du schéma aux Gerbers

Dix cartes de complexité croissante, **toutes passées par la chaîne complète**,
et dont le schéma est écrit par le driver : Claude Code joue l'agent Schéma, et
aucun appel au modèle n'a lieu.

## Pourquoi ce banc existe

⚠️ **Le banc historique ne teste pas ce que le produit promet.** Ses huit cartes
partent toutes de `circuit.json` **figés** — seul `led-blinker-full-pipeline`
part d'un `schema.json`. Aucune ne part d'une description en langage naturel, qui
est pourtant la promesse : *« conception PCB par langage naturel »*.

    stm32-validation   generate_design.py, project.kct
    nucleo-f401        circuit.json
    stm32-100          circuit.json
    arduino-uno        circuit.json

Le banc historique valide donc le **routage**. Il ne valide ni la génération du
schéma, ni la chaîne entière. Relevé par Grok le 2026-09-05, confirmé fichier
par fichier.

⚠️ Second motif : **le solde de l'API du modèle est épuisé** depuis le
2026-09-06. Un run enfilé dans la file échoue en 5 s. L'orchestrateur étant la
première étape, plus aucun pipeline ne peut aboutir par la voie normale. Ce banc
la contourne sans rien simuler : le schéma est réellement raisonné, simplement
par un assistant plutôt que par une requête facturée.

## Les cartes

Chaque dossier porte son `README.md` **généré depuis ses mesures**, avec sa
version git. Voir `scripts/readme_banc_driver.py`.

| carte | ce qu'elle ajoute |
|---|---|
| `carte-01-diviseur` | le minimum : un diviseur, une LED |
| `carte-02-alimentation` | deux régulateurs, découplage complet |
| `carte-03-oscillateur` | un SOIC-8, trois sorties |
| `carte-04-mcu-minimal` | **premier LQFP-48 fine-pitch**, SWD |
| `carte-05-capteur-i2c` | bus I2C, capteur LGA-8, tirages |
| `carte-06-io-etendu` | huit sorties, deux connecteurs |
| `carte-07-multi-io` | douze sorties **sur les quatre côtés**, cinq connecteurs |
| `carte-08-dense` | seize sorties, cinq connecteurs |
| `carte-09-tres-dense` | huit connecteurs, **plafond 4 couches** |
| `carte-10-maximale` | toutes les broches libres du LQFP-48 |

⚠️ Cette colonne dit une INTENTION de conception. Les comptes de composants et
les verdicts sont mesurés, et vivent dans le tableau généré en fin de page —
ils n'ont pas leur place ici, où ils dérivent. Celui-ci annonçait encore
« carte-07 : 47 composants » quand la carte en porte 48.

## Une règle de conception appliquée partout

⚠️ **Les broches d'entrée-sortie sont prises sur les QUATRE côtés du boîtier**,
jamais groupées d'un seul. Ce n'est pas un détail de style : `generer_exemples.py`
documente la mesure du 2026-08-28 sur la Nucleo — seize liaisons aboutissant dans
la même bande de 8 mm du LQFP-64, par des fils de 44 à 62 mm, et la carte
plafonnait à 68 %. Aucun routeur ne démêle cela, ni en ajoutant des couches, ni
en re-tirant.

## Ce qui a été trouvé en montant en complexité

Chacun de ces défauts n'apparaît qu'au-delà d'un certain nombre de composants,
ce qui est exactement l'intérêt d'un banc progressif.

**1. Le client coupait à 600 s** (`run_pipeline.py`). Le placement de la
`carte-07` le dépassait : `TimeoutError` côté client pendant que le service
travaillait encore. Porté à 3600 s, aligné sur le service.

**2. Les couches étaient codées en dur à 2.** Le service ne pouvait donc jamais
escalader, quelle que soit la densité — `carte-09` sortait à « 0 %, tous les
tirages ont stagné ». Le plafond se pilote désormais par `max_layers` dans le
schéma, et il ne PRESCRIT rien : le service part toujours de 2 et n'escalade que
sur preuve d'échec.

**3. Aucun budget de routage n'était transmis**, donc le service retombait sur
son défaut de 300 s alors qu'il en accepte 3600. Pilotable par `route_budget_s`.

⚠️ Ces trois défauts sont **la même famille**, déjà nommée dans `CLAUDE.md` :
« le plafond n'était pas UN endroit, mais QUATRE ». Un budget plus serré chez
l'appelant rend inatteignable tout ce qui est plus lent que lui, et rien dans la
réponse ne trahit la substitution.

**4. La surface, pas le DRC.** Ce qui a fait passer la `carte-08` de 216
connexions manquantes à ZÉRO est de l'avoir AGRANDIE — 110 × 80 mm puis
125 × 95. Rien d'autre n'a changé.

⚠️ **J'ai d'abord attribué ce gain à un correctif du DRC**, que j'avais écrit et
documenté ici : `/drc/auto` aurait mesuré avant de couler les plans. **C'est
faux, et la mesure directe l'a réfuté** — le même board, plans re-remplis ou
non, rend 5 connexions manquantes dans les deux cas. Le correctif et sa garde
ont été retirés.

C'est la faute que ce dépôt s'interdit explicitement : *« NEVER relayer le
message d'une garde comme un diagnostic »*, et sa jumelle — ne jamais garder
dans la documentation une explication qu'une mesure a démentie. Elle est
conservée ici en toutes lettres parce qu'un lecteur aurait construit dessus.

**5. La divergence du placement** (`carte-07`, 2026-09-07). Le placement de
cette carte dure **1560 s**, contre 104 s pour la `carte-08` (56 composants) et
130 s pour la `carte-10` (70). Douze fois plus long pour MOINS de composants.

Vérifié : son schéma est sain — aucune broche pointant vers un composant absent,
aucun composant isolé, la même structure que la `carte-08` dont elle dérive. La
cause est le placement lui-même, qui n'a **pas de graine fixe**
(`OptimizationWorkflow` en stratégie `hybrid`). Ce dépôt documentait déjà sa
dispersion en QUALITÉ — 6, 8 et 12 connexions manquantes selon le tirage ; on
mesure ici qu'elle porte aussi sur la DURÉE, et dans un rapport de douze.

Conséquence pratique : le temps d'un pipeline n'est pas prévisible à partir du
nombre de composants, et un budget client calibré sur une moyenne coupera
certaines cartes en plein travail.

**6. Freerouting tourne mille passes pour rien** (2026-09-07). Comptage sur le
journal du service, cinq travaux distincts :

    996 passes  score 815.45  (40 non routes)
    996 passes  score 701.71  (50 non routes)
    996 passes  score 685.09  (42 non routes)
    996 passes  score 650.03  (43 non routes)
    992 passes  score 770.97  (34 non routes)

Le score et le nombre de connexions manquantes sont **identiques d'un bout a
l'autre** : ces travaux n'ont rien ameliore apres leur premiere passe, et ont
consomme ~1,2 s chacune jusqu'au plafond de mille. Environ vingt minutes par
travail, entierement perdues — multipliees par les trois tirages de chaque
palier.

Le levier evident serait d'arreter sur absence de progression plutot que sur un
compte de passes. ⚠️ C'est un **seuil chiffre qui change le comportement
livre** : decision produit, donc proposee et non appliquee. Consignee dans
`docs/DECISIONS.md`.

⚠️ Ce que ce comptage ne dit PAS : que la machine etait saturee. Je l'ai cru en
voyant une JVM a 211 %% de processeur depuis sept heures. Mesure : **12
processeurs, charge moyenne 4,00**, et la liste des sessions du serveur est
vide. La lenteur de la `carte-07` n'est donc pas une contention — c'est bien son
placement, comme le disent les 1560 s.

## Ce qui compte comme « fabricable »

⚠️ **Le verdict se lit dans la SÉVÉRITÉ rendue par KiCad**, et il est mesuré sur
le **board livré**, pas sur le résumé du pipeline.

Deux règles, chacune payée par une mesure :

**La sévérité ne se devine pas.** `via_dangling`, `track_dangling`,
`silk_overlap` et `silk_over_copper` sont classés **warning** par KiCad — un via
orphelin est percé et plaqué, la carte se fabrique. Seul « Missing connection »
est classé **error**. Je les classais sur ma propre liste, plus sévère que KiCad
lui-même, ce qui déclarait non fabricables des cartes qui le sont.

**Le pipeline surestime.** Sur le MÊME fichier, `carte-09` :

    kicad-cli direct   :   9 non connectés,  70 violations
    service /drc/auto  :  18 non connectés, 154 violations

et jusqu'à 280 quand la boucle de correction itère. La cause de l'écart n'est
pas établie ; ce qui l'est, c'est lequel des deux juge le board qu'on livre.

## Relivraison compacte du 2026-09-20 (D-2026-09-20-a, 25 % d'occupation)

Chaîne complète place → route rejouée par HTTP sur les dix cartes avec la
carte de départ dimensionnée sur les composants. **Quatre** relivrées —
placement et board ensemble, `mesures.json` sous `carte_compacte` :

    carte-01   24,8 × 17  ->  20 × 14      0 erreur · 0 manquante
    carte-02   55 × 40    ->  35 × 25      0 erreur · 0 manquante
    carte-04   45 × 44,8  ->  39 × 30      0 erreur · 0 manquante
    carte-05   70 × 50    ->  46 × 33      0 erreur · 0 manquante

Les six autres gardent leur board du 2026-09-19 : 06 (48 × 36) et 08
(58 × 44, 6 couches) sortent à **1** connexion manquante ; 03 et 07 rendent
un board mauvais (12 et 204 erreurs) ; 09 et 10 ne rendent **aucun** board —
tous leurs tirages figent, et Freerouting 2.1.0 ne permet ni de borner un
routage ni d'en lire un partiel (voir CLAUDE.md). Le placement re-tiré de
ces cartes est en cause, pas la taille : le témoin grand format de l'A/B
échouait pareil.

## Rejeu du 2026-09-20 au soir — après le correctif des angles de pastilles

Le matin, 03/07/09/10 sortaient mauvaises ou sans board, et 05 a rechuté au
rejeu suivant. Cause commune : re-placer un board DÉJÀ placé comptait deux
fois la rotation du boîtier dans l'angle des pastilles (#224) — 205 erreurs
sur le board placé de carte-05, sans une piste. Même chaîne, même entrée,
après correctif :

    carte-01  20 × 13,5     0 erreur · 0 manquante
    carte-02  34,6 × 25,3   0 · 0
    carte-03  27,8 × 19,8   0 · 0     (12 erreurs · 9 manquantes le matin)  RELIVRÉE
    carte-04  38,8 × 30     0 · 0
    carte-05  45,5 × 32,5   1 · 0     (205 · 31 le matin)
    carte-06  48,4 × 36,3   0 · 0                                          RELIVRÉE
    carte-07  53,1 × 38,7   0 · 10    (204 · 54 le matin)
    carte-08  57,8 × 44     0 · 10
    carte-09  58,7 × 45,1   1 · 0     6 couches (aucun board le matin)
    carte-10  60,9 × 45,7   0 · 18    6 couches (aucun board le matin)

L'erreur unique de 05 et de 09 est la même : `courtyards_overlap` entre le
régulateur U2 et un passif voisin — un conflit que le placement avait signalé
lui-même. 07, 08 et 10 routent désormais mais gardent 10 à 18 connexions
manquantes sur ces cartes compactes : non relivrées, leur board du 19/09 reste.

## Banc en DEUX PHASES du 2026-09-21 — placement validé, puis routage gelé

Consigne de l'utilisateur : « placement d'abord ; s'il est valide on passe au
routage ; pas d'aller-retour ». Code de #226 (boîte orientée, filet DRC) et #227
(connecteurs collés au bord). Un seul tirage par carte, par HTTP.

**Phase A — le placement jugé SEUL.** Dix sur dix valides : 0 erreur DRC sur le
board placé, et le connecteur le plus loin d'un bord est à 2,0 mm (corps mesuré,
pas l'origine).

| carte | taille (mm) | croisements du chevelu |
|---|---|---|
| 01 | 20,0 × 14,0 | 1 |
| 02 | 34,8 × 25,3 | 9 |
| 03 | 25,2 × 20,0 | 21 |
| 04 | 38,8 × 30,0 | 24 |
| 05 | 45,5 × 32,5 | 74 |
| 06 | 48,4 × 36,3 | 157 |
| 07 | 53,1 × 38,7 | 209 |
| 08 | 57,8 × 44,0 | 406 |
| 09 | 58,7 × 45,1 | 483 |
| 10 | 60,9 × 45,7 | 564 |

**Phase B — routage des placements GELÉS, jamais re-placés.**

| carte | erreurs | manquantes | couches du board livré | durée |
|---|---|---|---|---|
| 01 | 0 | 0 | 2 | 80 s |
| 02 | 0 | 0 | 2 | 58 s |
| 03 | 0 | 0 | 2 | 68 s |
| 04 | 0 | 0 | 2 | 75 s |
| 05 | 0 | 0 | 2 | 76 s |
| 06 | 0 | 1 | 2 | 410 s |
| 07 | 0 | 2 | 2 | 550 s |
| 08 | 0 | 8 | 2 | 1921 s |
| 09 | 0 | 11 | 2 | 2574 s |
| 10 | 0 | **0** | 6 | 849 s |

Zéro erreur DRC sur les dix : les défauts de placement (chevauchement du
régulateur, angles de pastilles) ne reviennent pas. **carte-10 est relivrée**
(60,9 × 45,7 au lieu de 140 × 105, 6 couches). 06 à 09 ne le sont pas.

⚠️ **Ce que le journal dit de 08 et 09 — et ce n'est pas le placement.** Leur
board livré est celui du palier 2 couches (83 % et 80 %). Les paliers suivants
allaient PLUS LOIN, puis figeaient sans rendre de board :

    carte-08   4 couches : ~96 %, ~96 %, ~82 %   6 couches : ~92 %, puis budget épuisé
    carte-09   4 couches : ~41 %, ~51 %, ~82 %   6 couches : ~86 %, ~84 %

Un tirage figé ne se lit pas (limite de Freerouting 2.1.0, cf. CLAUDE.md) : la
chaîne garde donc le seul board qu'elle a, le moins bon. ⚠️ Un seul tirage par
carte : ces chiffres désignent une piste, ils ne prouvent pas une loi.

### Piste mesurée et RÉFUTÉE le 2026-09-21 — rejouer en CLI un tirage figé qui dépassait le board gardé

Idée : déclencher `_board_partiel_par_cli` (600 s stricts) non seulement quand
AUCUN board n'existe, mais aussi quand un tirage figé à 4 couches dépassait le
board gardé. Mesuré sur les placements GELÉS de la phase A, préparés à
4 couches exactement comme le palier (empilage, plan coulé, GND raccordé) :

| carte | board gardé (2 couches) | rejeu CLI à 4 couches |
|---|---|---|
| 08 | 0 erreur · 8 manquantes | 1 erreur · 7 manquantes — fini seul en 71 s |
| 09 | 0 erreur · 11 manquantes | 5 erreurs · 26 manquantes — fini seul en 101 s |

Pire sur 09, indifférent sur 08 : la règle n'est PAS étendue. ⚠️ Boards bruts,
sans les étapes d'après-routage, et un seul tirage. Fait nouveau : le CLI FINIT
seul en 1-2 min à 4 couches (il ne finissait pas sur carte-09 le 2026-09-20) —
il s'arrête en laissant des connexions. Monter en couches ne suffit donc pas
sur ces deux cartes compactes ; la piste suivante est la densité du placement
(406 et 483 croisements du chevelu), pas le routeur.

### ⚠️ La CHARGE DE LA MACHINE fausse le routage (mesure du 2026-09-22)

Même placement gelé de `carte-10`, même code, deux séries :

    machine LIBRE      4 tirages   4 x (0 erreur, 0 manquante)   139-392 s
    machine CHARGÉE    3 tirages   3 ÉCHECS (1 manq, 1 err, 1 manq)  603-1838 s

La charge venait d'une consultation d'agent externe lancée pendant le banc.

**Mécanisme** : l'abandon d'un tirage repose en partie sur `_PLAFOND_ATTENTE_S
= 300`, une horloge MURALE. Processeur disputé → moins de passes par seconde →
le plafond tire alors que le routeur progressait encore → tirage déclaré figé →
la chaîne garde un board moins bon. C'est ce que ce dépôt s'interdit ailleurs
(« NEVER conclure qu'un processus est bloqué en comparant l'horloge ») ; ici la
règle est DANS le code.

⚠️ **Les mesures d'intermittence du 2026-09-21 sont FAUSSÉES** — le « 1 tirage
sur 8 » a été relevé sur une machine chargée par mes propres tâches. Le taux
réel de défaut du plan de masse n'est pas connu ; il est plus bas.

⚠️ **NEVER lancer un agent externe, un build ou une autre mesure pendant un banc
de routage**, et le DIRE quand c'est arrivé : les chiffres ne valent alors rien.

**Corrigé le 2026-09-22** — `_faut_couper` a trois coupures, et une seule
ignorait la cadence :

    fenêtre de passes    compte des passes          indépendante de la machine
    routeur MUET         `max(300 s, 3 × cadence)`  SUIT déjà la cadence
    temps sans progrès   `> 300 s` en dur           NE LA SUIVAIT PAS

L'horloge ne peut plus couper avant la fenêtre de passes : le plafond vaut au
moins ce que cette fenêtre coûte au rythme OBSERVÉ. Ce n'est pas un second
seuil, c'est le premier traduit en secondes ; sans cadence mesurée, le plafond
habituel s'applique inchangé.

Preuve, `carte-10` sous charge délibérée (quatre boucles occupées) :

    avant le correctif   3 échecs sur 3    603-1838 s
    après                2 propres sur 2   233 et 255 s

### Combien de pastilles de masse finissent ENFERMÉES (mesure du 2026-09-21)

Seize boards routés mesurés (les dix du banc + les tirages de 07, 09, 10),
union-find des îlots GND reliés par les perçages :

    14 boards sur 16   un seul amas GND, AUCUNE pastille enfermée
    carte-07/tirage_3  2 amas — D16.1 enfermée
    carte-10/tirage_3  2 amas — C33.2 et C69.2 enfermées
    TOTAL              3 pastilles sur 16 boards

Toutes sont des passifs : la masse d'une LED et celle de deux condensateurs.

⚠️ **Le via d'échappement EST posé sur les trois** — à 0,9, 1,2 et 1,2 mm de la
pastille, avec son tronçon de masse. Ce n'est donc PAS un oubli de l'étape ②
(dogbone), hypothèse écartée par la mesure. Ce via descend vers la face
opposée, mais **à cet endroit la face opposée est elle aussi un îlot isolé** :
les deux faces sont coupées au même endroit, et le via ne relie que les deux
moitiés. C'est la paire de jumeaux du 2026-09-21, vue depuis sa cause.

Conséquence pour la suite : le remède n'est ni dans la couture (mesuré : aucun
site, aucun contournement), ni dans le dogbone (déjà posé). Il est dans le
ROUTAGE, qui encercle la même petite région sur les deux faces — piste non
encore mesurée : réserver un dégagement autour de chaque via d'échappement de
masse pour que les signaux ne le cernent pas. ⚠️ Voisine de l'« amorce sur la
face opposée », ESSAYÉE et RÉFUTÉE le 2026-09-02 (routeur trois fois plus lent,
aucun gain) : à mesurer avant toute proposition.

### Le placement se CALCULE — banc du 2026-09-21 au soir (graine en ÉTOILE)

Réglage de banc `graine_etoile`, DÉSARMÉ par défaut (D-2026-09-21-a, **en
attente**). Chaîne complète, un tirage par carte, code de `tools/graine_etoile.py`.

| carte | tirage `hybrid` (le matin) | graine en étoile (le soir) |
|---|---|---|
| 01 | 0 err · 0 manq | 0 · 0 |
| 02 | 0 · 0 | 0 · 0 |
| 03 | 0 · 0 | 0 · 0 |
| 04 | 0 · 0 | 0 · 0 |
| 05 | 0 · 0 | 0 · 0 (deux centres : U1 + U3) |
| 06 | 0 · **1** | 0 · 0 |
| 07 | 0 · **2** (GND) | 0 · **1** (GND) |
| 08 | 0 · **8** · 1921 s | 0 · 0 · 2 couches · 91 s |
| 09 | 0 · **11** · 2574 s | **1 err** (`starved_thermal` GND) · 0 manq |
| 10 | 0 · 0 · **6 couches** · 849 s | 0 · **1** (GND) · **2 couches** |

**Plus AUCUN signal manquant sur les dix cartes** — lignes de connecteur
(`EXT*`), `IO_L*`, `NRST`, `SWDIO` : toutes routées. Les trois défauts restants
sont tous du PLAN DE MASSE (îlot non cousu, pastille affamée), et ils
PRÉEXISTAIENT : le 07 du matin portait déjà ses 2 manquantes sur GND. Le
journal les explique : « couture : 1 via(s) posés » quand le plan compte
« GND@F.Cu en 17 îlots ».

Croisements du chevelu : 406 → 68 (carte-08), 483 → 112 (09), 564 → 130 (10).
Placement 20-45 s au lieu de 60-640 s — le résultat est le même à chaque appel,
donc un seul tirage suffit.

⚠️ **Deux cartes coûtent MOINS cher** : carte-08 sort sur 2 couches au lieu
de 4, carte-10 sur 2 au lieu de 6.

⚠️ **Les finitions défaisaient l'étoile**, et rien ne les surveillait : le
raffinement CMA-ES remontait carte-07 de 101 à 238 croisements. `_proteger_l_etoile`
annule désormais raffinement et halo s'ils remontent les croisements ; la grille
en est exempte (elle déplace de 0,25 mm au plus). Avec cette garde, carte-07 est
passée de 1 manquante à 0 et carte-08 de 3 à 0.

⚠️ **Le routeur reste stochastique** : carte-07 rend 0 puis 1 manquante avec le
MÊME code. Un tirage ne prouve rien, dans un sens comme dans l'autre.

⚠️ **Ce banc ne prouve pas une loi** (avis convergents de Codex et de GLM,
consultés le 2026-09-21) : les dix cartes ont toutes la même topologie, un
centre et ses périphériques. La graine ne porte AUCUNE règle pour un bus
parallèle, le partage de la carte entre plusieurs gros boîtiers, l'analogique,
la puissance, la RF ou le choix de face. Suite proposée par les deux agents :
découper en blocs fonctionnels, placer les blocs par un calcul global, l'étoile
devenant un patron parmi d'autres.

### D'où viennent les croisements — et trois pistes de placement RÉFUTÉES le 2026-09-21

Mesuré sur les dix placements valides de la phase A :

- **72 à 100 % des croisements du chevelu impliquent un net de connecteur** ;
- après routage, les connexions réellement manquantes sont des SIGNAUX
  (`EXT*` des connecteurs, `IO_L*`, `NRST`, `SWDIO`) — jamais le rail +3V3,
  dont le poids dans le compte de croisements est un artefact de la projection
  en étoile.

| piste | mesure | verdict |
|---|---|---|
| `place_hierarchical_from_pcb` (natif, blocs rangés en étagères) | carte-08 406 → 710 croisements, carte-10 564 → 904, jusqu'à 14 composants hors carte | réfutée |
| permuter les connecteurs identiques après placement | 0 à −17 % | trop faible |
| connecteurs recollés face à leurs broches, PUIS placement rejoué autour (seconde passe gardée seulement si elle bat la première) | 8 secondes passes : 2 retenues (19 → 13, 620 → 373), 6 écartées (21 → 25, 126 → 105 avec un conflit en plus, 127 → 234, 211 → 219, 426 → 491, 491 → 544) | réfutée |

⚠️ L'estimation « connecteurs seuls déplacés, le reste figé » annonçait −11 à
−42 % : elle ne tient pas dès qu'on re-place vraiment le reste. ⚠️ La
DISPERSION de l'optimiseur brouille tout : la première passe de carte-10 vaut
564 croisements le matin et 620 l'après-midi, sans qu'une ligne change. Une
seconde passe est d'abord UN AUTRE TIRAGE. Code non conservé.

Taux d'occupation (réglage de banc, un tirage) : à 20 % au lieu de 25 %,
carte-08 passe de 8 à 6 connexions manquantes et carte-09 de 11 à 4, toutes
deux sur 4 couches. Le point à 15 % n'a pas été mesuré (machine en veille).

## Couches : huit cartes sur deux, deux sur quatre

⚠️ **Ce titre disait « Les dix cartes tiennent sur DEUX couches ».** C'était
vrai à l'écriture, faux ensuite : recompté le 2026-09-19, carte-08 routait sur
4 couches, carte-09 sur 5 (6 déclarées) et carte-10 en déclarait 4 pour
2 segments internes.

Les dix boards ont été relivrés le même jour avec la couture corrigée (PR #217 :
elle recousait sans fin des îlots déjà reliés — 678 → 443 vias, rangée de
vias inutiles disparue, 0 erreur et 0 connexion manquante sur les dix). Compte
du cuivre posé dans les boards relivrés :

    carte-01 … carte-07   2 couches
    carte-08              4 couches — mais In2 ne porte que 5 segments, In1 aucun
    carte-09              2 couches (6 avant la relivraison)
    carte-10              4 couches — In1 38 segments, In2 33

Le routage est stochastique : ces couches sont celles d'UN tirage, pas une
propriété de la carte. Le compte se lit dans le board (`mesures.json`,
clé `couture_corrigee.couches`), jamais dans ce fichier : il a déjà menti une fois.

Texte d'origine, conservé pour le raisonnement qui reste juste : la `carte-09`
portait un plafond à quatre couches (`max_layers: 4` dans son schéma), et
elle ne s'en était pas servie au premier banc. C'est le comportement attendu — le plafond ne
PRESCRIT rien, le service part toujours de 2 et n'escalade que sur preuve
d'échec, en gardant toujours le meilleur tirage et jamais le dernier.

Deux couches coûtent moins cher à fabriquer que quatre. Une escalade qui ne se
déclenche pas est donc un succès, pas une capacité inemployée. Le banc des huit
cartes historiques avait fait le même constat le 2026-09-03 : *« aucune escalade
de couches n'a servi »*.

⚠️ Avant le 2026-09-07, **aucun schéma ne déclarait `max_layers`** : les dix
cartes tournaient toutes à deux couches, et la description de la `carte-09`
annonçait pourtant « plafond 4 couches ». La documentation promettait une
capacité que le fichier ne déclarait pas. C'est la faute déjà inscrite dans
`CLAUDE.md` à propos d'une section d'ordre d'exécution laissée périmée, et qui
avait fait conclure à une cascade mal ordonnée.

## Deux tirages ne prouvent rien

Les deux cartes qui ont résisté le montrent, chacune à sa manière.

La `carte-07` a rendu 5, puis 2, puis 3 erreurs, puis 0 % routé, avant
d'atteindre zéro. La `carte-09` a rendu 1 erreur, puis 2 au tirage suivant, puis
zéro — **sur le même schéma**, à ceci près qu'on lui avait ouvert un plafond
qu'elle n'a finalement pas utilisé.

Le placement et le routage sont tous deux stochastiques. Ce dépôt mesure déjà
23 points d'écart entre deux tirages d'une même carte au même placement. Un
résultat isolé ne dit donc rien, ni en bien ni en mal — et c'est exactement sur
deux tirages concordants que j'avais conclu, à tort, à un défaut structurel.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-01-diviseur
python scripts/readme_banc_driver.py --tous
```

⚠️ `examples/` n'est **pas monté** dans le conteneur : il est cuit dans l'image.
Le banc extrait donc chaque board aussitôt — sans quoi l'artefact part au premier
redémarrage, la leçon des worktrees vides transposée.

⚠️ **Un seul routage à la fois.** Deux routages concurrents font tuer le
processus par le noyau (décision `D-2026-09-03-b`), et le verrou du service les
sérialise. Le banc ne lance donc jamais deux cartes en parallèle.

## Resultats mesures

<!-- TABLEAU GENERE -->
| carte | comp. | nets | routage | erreurs | fabricable |
|---|---|---|---|---|---|
| `carte-01-diviseur` | 5 | 4 | 100 % | 0 | **oui** |
| `carte-02-alimentation` | 12 | 5 | 100 % | 0 | **oui** |
| `carte-03-oscillateur` | 15 | 9 | 100 % | 0 | **oui** |
| `carte-04-mcu-minimal` | 15 | 7 | 100 % | 0 | **oui** |
| `carte-05-capteur-i2c` | 26 | 13 | 100 % | 5 | **NON** |
| `carte-06-io-etendu` | 35 | 27 | 100 % | 0 | **oui** |
| `carte-07-multi-io` | 44 | 37 | 100 % | 0 | **oui** |
| `carte-08-dense` | 56 | 49 | 100 % | 0 | **oui** |
| `carte-09-tres-dense` | 62 | 49 | 100 % | 0 | **oui** |
| `carte-10-maximale` | 70 | 49 | 100 % | 0 | **oui** |
| `carte-11-croisements` | 6 | 34 | 3 % | 42 | **NON** |
<!-- FIN TABLEAU GENERE -->

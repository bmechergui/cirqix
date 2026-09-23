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

### BANC DE RÉFÉRENCE du 2026-09-22 — 9 cartes sur 10 parfaites

Premier banc mesuré dans des conditions propres : graine en étoile armée
(réglage de banc), correctif de cadence en place (#235), **machine libre, aucune
autre tâche** — c'est exactement ce qui manquait aux mesures du 2026-09-21.

| carte | erreurs | connexions manquantes | couches de signal |
|---|---|---|---|
| 01 | 0 | 0 | 1 |
| 02 | 0 | 0 | 1 |
| 03 | 0 | 0 | 1 |
| 04 | 0 | 0 | 2 |
| 05 | 0 | 0 | 2 (deux centres) |
| 06 | 0 | 0 | 2 |
| 07 | 0 | 0 | 2 |
| 08 | 0 | 0 | 2 |
| 09 | 0 | 0 | 2 |
| 10 | 0 | **1** (GND) | 2 |

**Plus aucun SIGNAL ne manque sur les dix cartes**, et aucune ne dépasse deux
couches de signal — contre 4 et 6 couches avant la graine. Le seul défaut
restant est un amas de plan de masse isolé sur `carte-10`.

⚠️ **Les DURÉES de ce banc ne veulent rien dire** : la machine se met en veille,
et `route_s` compte le temps écoulé, pas le temps de calcul (carte-01 affiche
14 415 s pour un routage d'une poignée de secondes). Les VERDICTS, eux, sont
valables. Pour des durées exploitables il faut désactiver la veille.

⚠️ Trois faux départs avant ce banc, tous de méthode et non de code : un
`docker exec -d` qui n'a pas survécu, un redémarrage de la VM WSL qui a emporté
le service en pleine exécution (dix « Connection refused » d'affilée), et un
`pgrep` qui se trouvait lui-même et déclarait vivant un script mort. Le schéma
qui tient : un processus Windows caché (`Start-Process wsl.exe`) qui exécute le
banc de façon SYNCHRONE, plus un second qui maintient la VM en vie.

### La DERNIÈRE rupture de plan, mesurée jusqu'au bout (2026-09-22)

Diagnostic complet de l'unique défaut restant, sur le board qui le porte
VRAIMENT. Consultation de Codex et de GLM, puis mesure — et la mesure a
tranché contre l'une des deux propositions.

⚠️ **J'AI D'ABORD MESURÉ LE MAUVAIS BOARD, et il donnait un résultat
encourageant.** `carte-10-maximale/expected/final.kicad_pcb` date du
2026-09-21 et son propre `mesures.json` annonce `non_connectes: 0` ; mon DRC
l'a confirmé. Le défaut du banc du 22 vit dans
`/tmp/livr/carte-10-maximale/route.kicad_pcb`, **resté dans le conteneur** —
la faute que ce dépôt s'interdit pourtant en toutes lettres. Sur le board
versionné j'ai trouvé un îlot orphelin dont 92 points sur 93 faisaient face au
plan principal, et un via y tenait avec 0,29 mm de marge : j'ai failli
annoncer une solution pour un board qui n'a jamais eu le défaut.
**NEVER mesurer un défaut sans avoir vérifié que l'artefact le PORTE** — un
board propre se prête à toutes les démonstrations.

Sur le vrai board (33 violations, 0 erreur, **1 connexion manquante**) :

| | mesure |
|---|---|
| îlots du net GND, deux faces | 23 |
| orphelins | **2**, et ce sont des JUMEAUX |
| îlot F.Cu | 1,30 mm², porte la pastille `C35.2` |
| îlot B.Cu | 0,99 mm², aucune pastille |

**La piste « changer de face par un via » est RÉFUTÉE par la mesure.** GLM
l'avait proposée en relevant, à juste titre, que `routing_pcbnew_runner.py`
refuse toute cible sur l'autre face (`if c2 != couche: continue`) et que son
A* est à deux dimensions. Mais sur ce board, **aucun** point des deux îlots
n'a le plan principal en vis-à-vis : ils se font face L'UN L'AUTRE (9 points
sur 25 et sur 12), ce qui est exactement le motif des jumeaux qui se portent
garants, déjà inscrit le 2026-09-21.

**Et aucun via ne tient de toute façon.** La couture de production, rejouée
sur ce board, visite les deux îlots et refuse la TOTALITÉ de leurs sites :

    ilot F.Cu 1,297 mm2   23 candidats   obstacle 16 · hors_polygone 6 · trou_trop_pres 1
    ilot B.Cu 0,993 mm2   18 candidats   obstacle 10 · hors_polygone 7 · trou_trop_pres 1

Un îlot d'un millimètre carré n'a pas la place d'un via — et le raccord par
courte piste rend `relies: 0`, `sans_chemin: 19`.

**Ce qui enferme l'amas n'est PAS un faisceau : c'est UN segment par face.**

| face | distance au plan principal | ce qui coupe le couloir |
|---|---|---|
| F.Cu | 0,862 mm | **1 segment**, net `EXT2_1` |
| B.Cu | 0,781 mm | **1 segment**, net `EXT4_1` |

⚠️ La description « cerné par un faisceau, jusqu'à 18 segments `+3V3` »
appartient à `carte-07`, pas à ce cas-ci. Reprise sans être re-mesurée, elle
faisait paraître le défaut bien plus coûteux à refermer qu'il ne l'est.

**Conséquence.** Le plan proposé par Codex — ne pas chercher un passage de
masse À TRAVERS l'obstacle, mais DÉPLACER l'obstacle — a ici un ensemble à
arracher de **un seul segment par face**, pas une recherche ouverte. C'est la
seule voie que la mesure laisse debout.

Levier natif VÉRIFIÉ, et jamais appelé : `kicad-tools/src/kicad_tools/drc/
local_rerouter.py::LocalRerouter.reroute_segment()` — A* sur grille locale,
arrache un segment et le recontourne, avec `extra_obstacles` et `dry_run`.
Il est appelé par `drc/repair_clearance.py` en amont et par **AUCUN** code
Cirqix. C'est le septième levier natif que ce projet trouve inutilisé.
⚠️ Il travaille sur le document S-expression de kicad-tools, quand notre code
travaille sur les objets `pcbnew` — et nous avons déjà notre A*
(`_chemin_de_contournement`) et notre dégagement exact (`_couloir_libre`).
Le choix entre « importer le levier » et « étendre le nôtre » reste ouvert.

Avertissements de GLM sur ce plan, à honorer quand il sera décidé : le
rerouteur est AVEUGLE aux zones, donc la masse se coule EN DERNIER ; et un
reroutage raté échange une masse manquante contre une ALIMENTATION manquante,
donc tout en `dry_run`, arbitrage final par le DRC et `_aggrave_le_board`.

### Le dégagement est IMPLÉMENTÉ, et il bute sur une raison géométrique

Livré le 2026-09-22 sur demande explicite de l'utilisateur. Le raccord des amas
orphelins, quand son contournement échoue, arrache désormais le petit nombre de
segments qui ferment le couloir (`_couloir_degageable`, plafond
`_SEGMENTS_ARRACHABLES = 3`), pose le raccord de masse, puis repose ailleurs ce
qu'il a retiré — **tout ou rien**, avec remise en état intégrale si un seul
reroutage échoue.

**Deux défauts RÉELS trouvés en le mesurant, et c'est là qu'est le gain :**

| | avant | après |
|---|---|---|
| amas orphelins vus sur `carte-10` | **21** | **1** |
| erreurs de dégagement introduites | **426** | **0** |

1. **Le raccord jugeait ZONE PAR ZONE.** Notre générateur écrit UNE ZONE PAR
   FACE : juger une zone seule fait passer pour orphelin tout îlot de F.Cu qui
   rejoint le plan par B.Cu. Vingt amas sur vingt et un étaient donc parfaitement
   reliés, et recevaient du cuivre pour rien. `_stitch_zones` jugeait déjà sur le
   net entier — les deux jumelles ne disaient pas la même chose, et c'est la plus
   permissive qui posait le cuivre.
2. **`_couloir_libre` échantillonnait le trajet AU PAS DE LA MARGE.** Un bond
   plus court que la marge n'était donc jugé que par ses deux bouts. Or la
   distance à un cuivre est convexe le long d'un segment : son minimum tombe à
   l'INTÉRIEUR. Mesuré : 426 violations à 0,1993 mm pour 0,2000 exigés — sept
   dixièmes de micromètre, exactement ce qu'un échantillonnage à deux points
   laisse passer. Pas ramené à un huitième de marge.

### Le bord d'un connecteur se choisit par la DIRECTION, pas par la distance (2026-09-23)

`_position_au_bord` classait les quatre bords par distance et prenait le plus
proche. Depuis que le contour se resserre sur le circuit, les quatre bords sont
presque ÉQUIDISTANTS : le critère perd son sens, et les connecteurs sortent du
même côté.

⚠️ **Première tentative, MESURÉE ET RÉFUTÉE le même jour** : resserrer le CADRE
sur la frontière du circuit au lieu de changer le critère. Aucun gain de taille
(58,98 × 45,8 avant comme après) et un aspect nettement pire — tous les
connecteurs entassés sur le bord droit, deux se chevauchant, les trois autres
bords vides. Ce n'était pas le cadre, c'était le critère. Le code est annulé.

Quand l'appelant connaît la direction — la graine connaît l'angle du rayon des
broches — c'est elle qui commande ; à direction égale, le plus proche départe.
Sans direction, rien ne change : `_coller_les_ancrages_au_bord` glisse toujours
par le plus court chemin, et c'est sa règle propre.

⚠️ **Gain visible FAIBLE sur le banc, et il faut le dire.** Les connecteurs
étaient déjà répartis sur trois bords ; le critère est désormais sensé, il ne
dégrade rien, mais il ne transforme pas le rendu. Ce qui reste laid — une zone
vide entre le circuit et les connecteurs du bord, quelques composants sans lien
loin de tout — n'est pas réglé par là.

### ⚠️ DEUX CARTES PERDUES SUR LE CONTRÔLE ÉLECTRIQUE, deux causes (2026-09-23)

`carte-08` puis `carte-10` sont sorties `abouti=False` sur un **HTTP 500 de
`/erc`**, à des moments différents de la journée. Deux causes distinctes, toutes
deux de familles que ce dépôt documente déjà.

**1. L'analyse tenait le GIL dans le worker.**

    Timeout (0:00:04.500000)!
      kicad_tools/sexp/parser.py:1181  _parse_list
      kicad_tools/schematic/models/io_mixin.py:111  load
      tools/erc.py:188  run_kicad_tools_erc

`Schematic.load` est du Python PUR : il tient le GIL pendant toute l'analyse
d'un schéma de 140 à 190 ko, et uvicorn tue par SIGKILL tout worker muet plus
de 5 s. C'est la **sœur** du défaut corrigé le 2026-09-10 sur le journal
Freerouting — le journal avait été traité, le schéma non, alors que `CLAUDE.md`
l'interdit en toutes lettres. `tools/erc_runner.py` rejoint les quatre autres
runners du service.

**2. Le budget de `kicad-cli` était de 30 s à plat**, et son dépassement
remontait en 500 : le routage entier perdu. Famille « le plafond n'était pas UN
endroit, mais QUATRE ». Il se déduit désormais de la taille du schéma, plancher
de 120 s — quatre fois le point d'échec mesuré. **Et une expiration ne tue plus
le run** : kicad-tools a déjà rendu un verdict réel, il est conservé, et le fait
que l'ERC d'autorité n'ait pas tourné est DIT.

### BANC DE RÉFÉRENCE du 2026-09-23 (4e passage) — service corrigé, dix sur dix

| carte | demandée | livrée | erreurs | manquantes |
|---|---|---|---|---|
| `carte-01-diviseur` | 25 × 20 | **20,1 × 14,1** | 0 | 0 |
| `carte-02-alimentation` | 55 × 40 | **32,5 × 25,4** | 0 | 0 |
| `carte-03-oscillateur` | 50 × 35 | **28,1 × 19,9** | 0 | 0 |
| `carte-04-mcu-minimal` | 60 × 45 | **36,6 × 29,8** | 0 | 0 |
| `carte-05-capteur-i2c` | 70 × 50 | **40,0 × 32,6** | 0 | 0 |
| `carte-06-io-etendu` | 80 × 60 | **47,5 × 36,4** | 0 | 0 |
| `carte-07-multi-io` | 110 × 80 | **47,7 × 38,8** | 0 | 0 |
| `carte-08-dense` | 125 × 95 | **57,4 × 44,1** | 0 | 0 |
| `carte-09-tres-dense` | 130 × 100 | **57,8 × 45,2** | 0 | 0 |
| `carte-10-maximale` | 140 × 105 | **59,0 × 45,8** | 0 | 0 |

Dix sur dix, 100 % routé. `carte-02` gagne encore 2,4 mm de largeur.

⚠️ **CE TABLEAU EST UN TIRAGE, PAS UNE PROPRIÉTÉ.** `carte-10` rejouée le soir
même depuis le MÊME placement gelé, machine au repos, par la même voie HTTP :
**98 %, 1 connexion manquante**, en 2432 s au lieu de 1027. Le journal du
service montre les deux issues alternant toute la journée sur cette carte —
« 1 piste posée sur 1 amas » à 13:30, 13:41, 13:46, 13:52, 14:00, 14:25, 18:19,
et « AUCUN raccordé » à 14:14, 18:22, 18:24, 18:25, 21:04 — avant comme après
les correctifs du jour. C'est la dispersion déjà mesurée sur cette carte
(99 · 97 · 77 · 87 · … · 100 %), pas une régression.

Ce que le tableau établit : chaque carte **peut** sortir propre, et son board
l'est dans `expected/`. Ce qu'il n'établit pas : qu'elle le fera à chaque coup.
**NEVER** lire une ligne de ce tableau comme une garantie de tirage.

Le tirage du soir montre aussi que les gardes tiennent quand le tirage est
mauvais : « repli GND REFUSÉ : (0 erreur, 84 manquante) ne fait pas mieux que
(0 erreur, 1 manquante) — board conservé ». Le board rendu est le meilleur vu,
jamais le dernier.

⚠️ **Le raccord par DÉGAGEMENT DU COULOIR s'est déclenché en production** et le
journal le dit : « raccord des amas orphelins : 1 piste(s) posée(s) sur 1 amas
(dont 1 par DEGAGEMENT du couloir) ». Le mécanisme livré cette nuit ne dort pas
dans le code — il travaille.

⚠️ Les DURÉES varient d'un facteur six d'un banc à l'autre sur la même carte
(`carte-06` : 468 s, puis 3204, puis 1140). Freerouting est stochastique et
tourne jusqu'à mille passes sans gain. **Ne jamais conclure d'un écart de durée
entre deux bancs qu'un changement a ralenti la chaîne** — j'ai failli annuler
un correctif sain pour cette raison.

### Les périphériques se RÉPARTISSENT, ils ne s'empilent plus (2026-09-23)

Deuxième défaut visible après le resserrement du contour : les composants
s'entassaient d'un seul côté du boîtier, étiquettes de sérigraphie par-dessus
les unes des autres, pendant que trois quarts de la couronne restaient vides.

**Deux causes, toutes deux dans `_poser_les_peripheriques`, toutes deux la
même faute :** un angle unique pour tout un groupe.

- les périphériques **directs** qui visent la même broche — tous les
  découplages d'un rail, toutes les résistances d'un même signal — recevaient
  le MÊME `angle_vers` et le même rayon de départ ;
- les **suiveurs** d'un même parent recevaient tous `atan2(parent − centre)` ;
- les **isolés** partaient tous de l'angle `0.0`, c'est-à-dire du même point.

`le_long_du_rayon` ne s'écartait qu'une fois la place prise : d'où la file
radiale. Le remède ne déplace RIEN de posé — le premier de chaque groupe garde
exactement la direction calculée, les suivants s'en écartent en éventail
(`_ecart_en_eventail`, pas de `3 × _PAS_ANGLE_DEG`), et `le_long_du_rayon`
reste seul juge de ce qui est libre.

Mesuré sur `carte-10` : amas du circuit 46,5 → **39,5 mm** de large, carte
61,0 → **59,0 mm**, toutes les étiquettes lisibles, routage inchangé.

### BANC du 2026-09-23 (3e passage) — dix cartes, contour resserré ET périphériques répartis

| carte | demandée | livrée | erreurs | manquantes |
|---|---|---|---|---|
| `carte-01-diviseur` | 25 × 20 | **20,1 × 13,6** | 0 | 0 |
| `carte-02-alimentation` | 55 × 40 | **34,9 × 25,2** | 0 | 0 |
| `carte-03-oscillateur` | 50 × 35 | **27,6 × 19,9** | 0 | 0 |
| `carte-04-mcu-minimal` | 60 × 45 | **36,6 × 29,8** | 0 | 0 |
| `carte-05-capteur-i2c` | 70 × 50 | **40,0 × 32,6** | 0 | 0 |
| `carte-06-io-etendu` | 80 × 60 | **46,5 × 36,4** | 0 | 0 |
| `carte-07-multi-io` | 110 × 80 | **47,7 × 38,8** | 0 | 0 |
| `carte-08-dense` | 125 × 95 | **57,4 × 44,1** | 0 | 0 |
| `carte-09-tres-dense` | 130 × 100 | **57,8 × 45,2** | 0 | 0 |
| `carte-10-maximale` | 140 × 105 | **59,0 × 45,8** | 0 | 0 |

Dix sur dix, 100 % routé. `carte-07` gagne encore 5,5 mm de largeur sur le
passage précédent, `carte-06` deux, `carte-10` deux.

⚠️ **J'AI FAUSSÉ CE BANC EN COURS DE ROUTE, et c'est la faute que ce fichier
interdit depuis la veille.** J'ai lancé une revue multi-agents pendant que le
banc tournait. `carte-08` est sortie `abouti=False` sur un **HTTP 500 de
`/erc`** : le lecteur S-expression de `kicad-tools` a tenu le GIL plus de
4,5 s pendant que cinq agents se disputaient le processeur, et le superviseur
uvicorn tue tout worker muet plus de 5 s (leçon du 2026-09-10). Relancée seule,
machine libre : **193 s, 0 erreur, 0 manquante**. Le placement n'était pas en
cause — la charge l'était. **NEVER lancer quoi que ce soit pendant un banc**,
y compris une revue qui ne touche à rien.

⚠️ **Ce qui reste à faire, et qui se voit encore sur le rendu** : une zone vide
subsiste entre le circuit et les connecteurs du bord, et quelques composants
sans lien (`C1`, `C2`, `C3` sur `carte-10`) restent loin de tout. La carte est
à la bonne taille et la couronne est servie ; le RAPPROCHEMENT des connecteurs
vers le circuit ne l'est pas encore.

### ⚠️ LE CONTOUR N'ÉTAIT JAMAIS RESSERRÉ DANS LE BANC (2026-09-23)

Question de l'utilisateur devant les rendus : « tu es satisfait de ce
placement ? ». Non. Mesure sur `carte-10` livrée :

    carte                140 x 105 mm  = 14725 mm2
    circuit               51 x  66 mm  =  3366 mm2
    OCCUPATION                             23 %
    connecteurs, du circuit           56 a 75 mm
    fil de signal                       1230 mm  (VIN a lui seul : 112 mm)

Une carte quatre fois trop grande, les composants entassés au centre, les
connecteurs échoués aux bords lointains, et l'alimentation qui traverse sur
onze centimètres. Le routeur s'en sortait — zéro erreur, zéro manquante — mais
personne ne livrerait cela.

**La cause : `run_pipeline.py` n'envoyait pas `auto_size_board` à
`/place/auto`.** Le resserrement du contour sur le placement existe depuis le
2026-09-13 (D-2026-09-13-c A) et ne s'exécute que si l'appelant l'autorise ; le
défaut du modèle est `False`. **Septième levier de ce projet qui existe et que
personne n'appelle** — après `max_distance_mm`, `anchor_pin`,
`WorkflowConfig.grid`, `constraints`, `move_reference`, `bottom_up_placement`
et `LocalRerouter`.

⚠️ Et le défaut était INVISIBLE : la chaîne de PRODUCTION, elle, passe bien le
drapeau depuis `handlePlacement`. Le banc mesurait donc un comportement que le
produit n'a pas — l'inverse exact de ce à quoi sert un banc.

Mesure après correction, même circuit, même graine :

| | avant | après |
|---|---|---|
| carte | 140 × 105 mm | **61,0 × 45,8 mm** |
| occupation | 23 % | **56 %** |
| fil de signal | 1230 mm | **652 mm** |
| `VIN`, le plus long | 112 mm | **45,5 mm** |
| connecteurs, du circuit | 56-75 mm | **23-35 mm** |
| routage | 100 % · 0 err · 0 manq | **100 % · 0 err · 0 manq** |

**Et le routage ACCÉLÈRE** : `carte-08` passe de 2002 s à 347 s, six fois plus
vite. Ce fichier le disait déjà sans en tirer parti — « l'espace de recherche
d'un routeur croît avec la SURFACE × le nombre de nets ». Une carte quatre fois
trop grande se paie en cases de grille explorées.

⚠️ **Un second mensonge de mesure, corrigé au passage.** Le banc annonçait la
taille DEMANDÉE au schéma, pas celle du board. `carte-10` était rapportée
140 × 105 alors qu'elle mesurait 61,0 × 45,8 — cinq fois faux en surface, et
rien ne permettait de s'en apercevoir. `mesures.json` porte désormais
`board_mm` (lu sur `Edge.Cuts`) ET `board_mm_demande` : l'écart est justement
ce qu'on veut voir.

### BANC DE RÉFÉRENCE du 2026-09-23 (2e passage) — DIX cartes, chacune à la taille de son circuit

| carte | demandée | RÉELLE | erreurs | manquantes |
|---|---|---|---|---|
| `carte-01-diviseur` | 25 × 20 | **20,1 × 14,6** | 0 | 0 |
| `carte-02-alimentation` | 55 × 40 | **34,9 × 25,4** | 0 | 0 |
| `carte-03-oscillateur` | 50 × 35 | **26,1 × 20,1** | 0 | 0 |
| `carte-04-mcu-minimal` | 60 × 45 | **36,6 × 27,2** | 0 | 0 |
| `carte-05-capteur-i2c` | 70 × 50 | **43,6 × 32,6** | 0 | 0 |
| `carte-06-io-etendu` | 80 × 60 | **48,5 × 36,4** | 0 | 0 |
| `carte-07-multi-io` | 110 × 80 | **53,2 × 38,8** | 0 | 0 |
| `carte-08-dense` | 125 × 95 | **56,4 × 44,1** | 0 | 0 |
| `carte-09-tres-dense` | 130 × 100 | **57,3 × 45,2** | 0 | 0 |
| `carte-10-maximale` | 140 × 105 | **61,0 × 45,8** | 0 | 0 |

Dix sur dix, 100 % routé, aucune erreur, aucune connexion manquante — et les
dix cartes divisées par deux à quatre en surface.

⚠️ **Ce qui reste laid, et qui n'est pas réglé** : les composants passifs
s'entassent encore d'un côté du boîtier central, et les étiquettes de
sérigraphie se chevauchent (`R20`/`R21`, `D22`/`D23`). La carte est à la bonne
taille ; la RÉPARTITION à l'intérieur ne l'est pas encore.

### BANC DE RÉFÉRENCE du 2026-09-23 — DIX cartes sur dix, parfaites

Premier banc où **aucune carte ne porte le moindre défaut**. Graine en étoile
armée, correctif du raccord des amas en place, machine libre.

| carte | comp. | erreurs | connexions manquantes | routé |
|---|---|---|---|---|
| `carte-01-diviseur` | 5 | 0 | 0 | 100 % |
| `carte-02-alimentation` | 12 | 0 | 0 | 100 % |
| `carte-03-oscillateur` | 15 | 0 | 0 | 100 % |
| `carte-04-mcu-minimal` | 15 | 0 | 0 | 100 % |
| `carte-05-capteur-i2c` | 26 | 0 | 0 | 100 % |
| `carte-06-io-etendu` | 35 | 0 | 0 | 100 % |
| `carte-07-multi-io` | 44 | 0 | 0 | 100 % |
| `carte-08-dense` | 56 | 0 | 0 | 100 % |
| `carte-09-tres-dense` | 62 | 0 | 0 | 100 % |
| **`carte-10-maximale`** | **70** | **0** | **0** | **100 %** |

`carte-07` et `carte-10`, les deux qui portaient des ruptures de plan de masse,
sortent propres. La veille encore, `carte-10` livrait une connexion manquante.

⚠️ **Deux cartes ont d'abord échoué sur un HTTP 500 que J'AI introduit**, et
c'est le piège que ce dépôt documente depuis le 2026-08-31 : *le diagnostic
qu'on ajoute devient la panne*. Le résumé des raisons d'échec formatait toutes
ses valeurs en `%d`, alors que `motifs_reroutage` porte un DICTIONNAIRE ; le
`TypeError` remontait jusqu'à la route et le routage entier était perdu. Les
huit premières cartes ne l'ont jamais touché — cette ligne ne s'exécute que
lorsque AUCUN amas n'a pu être raccordé. Corrigé (`_resume_des_echecs`),
gardé par trois tests, et les deux cartes relancées sortent à zéro.

⚠️ Les DURÉES restent sans valeur : la machine se met en veille et le compteur
suit l'horloge murale. Les VERDICTS, eux, tiennent.

### ⚠️ LE DÉFAUT EST REFERMÉ — mesuré le 2026-09-22

    board du banc          33 violations · 0 erreur · **1** connexion manquante
    après réparation       33 violations · 0 erreur · **0** connexion manquante

Même compte de violations, zéro erreur, et la rupture de plan a disparu.

**Et il a fallu passer par l'autre face, pour une raison qui se calcule :** le couloir fait 0,862 mm, et le raccord de masse le barre sur toute
sa largeur — 0,25 mm de cuivre plus 0,2 mm de dégagement de chaque côté, soit
0,65 mm, entre un îlot et un plan distants de 0,862 mm. Il ne reste pas la place
d'un second conducteur, quelle que soit sa finesse : un signal de 0,25 mm en
réclame 0,65 à lui seul, et le total exigé est de 1,30 mm. **Sur la même face,
c'est arithmétiquement impossible.** Le reroutage échoue donc, tout est remis en
place, et le board ressort à l'identique — 33 violations, 0 erreur, 1 connexion
manquante, exactement comme avant.

**Le remède : le signal arraché CHANGE DE FACE.** Deux vias, un trajet sur
l'autre face, et les deux tronçons qui rejoignent les extrémités d'origine
(`_detour_par_l_autre_face`). Le site de chaque via est cherché par anneaux
croissants autour de l'extrémité, donc borné et interrompu au premier point
légal ; ses obstacles se prennent sur TOUTES les couches, puisqu'un via
traverse.

⚠️ **IL FAUT RECOULER AVANT DE JUGER, et c'est la mesure qui le dit.** Le
trajet de l'autre face passe à travers le plan coulé : le board intermédiaire
porte **51 erreurs** de dégagement, bien réelles. La coulée les efface en
découpant le cuivre autour de la piste neuve. Juger sans recouler ferait
rejeter un board qui, recoulé, est parfait — c'est exactement la famille de
fautes que ce dépôt traque, un instrument qui condamne un résultat sain.

    sans recoulée    84 violations · 51 erreurs · 0 manquante
    recoulé          33 violations ·  0 erreur  · 0 manquante

Une piste reste ouverte, non mesurée : **empêcher en AMONT que le routeur
enferme la pastille**, en réservant autour de chaque via de masse la largeur
d'un couloir plutôt que son seul dégagement. ⚠️ Cousine de l'« amorce
protégée », RÉFUTÉE le 2026-09-02 (routeur trois fois plus lent).

**Cinq constats de revue, tous traités avant livraison** — aucun n'était
visible en test unitaire, et trois auraient mordu sur un vrai board :

- l'A* recevait des milliers de buts non dédoublonnés, et son heuristique prend
  le minimum sur TOUS les buts À CHAQUE NŒUD : `_NOEUDS_MAX_CONTOURNEMENT`
  borne le nombre de nœuds, jamais le coût de chacun. La famine revenait par la
  porte de derrière. Bornés à `_BUTS_MAX = 64`, dédoublonnés, les plus proches ;
- un amas relié par arrachage était compté À LA FOIS dans `relies` et dans
  `sans_chemin` : le rapport se contredisait. L'échec n'est plus compté qu'après
  l'échec du dégagement ;
- la remise en état retrouvait les pistes posées par la DIFFÉRENCE de longueur
  de `board.GetTracks()`, c'est-à-dire en supposant que pcbnew ajoute toujours
  en fin de liste. Le « tout ou rien » serait devenu silencieusement partiel.
  `_rerouter_un_segment` REND désormais les objets qu'il a posés ;
- la règle d'arrondi de grille n'était écrite que dans le reroutage, pas dans le
  chemin amas → plan qui en a le même besoin. Écrite aux deux endroits ;
- `_couloir_libre` devient plus stricte pour son appelant préexistant. C'est
  voulu — elle refuse ce qui violait le dégagement — et mesuré sur le board
  fautif : verdict et board inchangés.

Gardes : `tests/test_couloir_degage_par_arrachage.py` (13 tests — les fonctions
pures, la borne, ET le câblage) ; 732 tests de routage au vert.

Rien de plus n'est implémenté : la suite est une décision de stratégie de
routage, donc `D-2026-09-22-a`, **en attente**.

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

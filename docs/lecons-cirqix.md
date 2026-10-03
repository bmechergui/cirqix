# Cirqix — leçons datées

Récits d'incidents déplacés de `CLAUDE.md` (sections « Leçons inscrites le … ») le
2026-09-25. Les principes qui en découlent restent dans `CLAUDE.md`, sous « Principes
de mesure et de correction » ; ce fichier garde les mesures, le contexte et les gardes
de test de chaque règle.

### Leçons inscrites le 2026-08-29 — chacune payée par une mesure

**NEVER** conclure qu'un levier natif n'existe pas sans avoir lu les CHAMPS des
objets rendus. `FunctionalCluster.max_distance_mm` et `anchor_pin` étaient
publics, calculés à chaque appel, jamais lus — et leur absence supposée a fondé
deux mois de renoncement (« adjacence serrée = Phase 6 »). Lire la signature
d'une fonction ne suffit pas : ce qu'elle REND porte souvent la réponse.

**NEVER** ajouter un correctif qui déplace des composants sans vérifier ce que
font ceux qui l'entourent. Le snap posé avant le Géomètre est défait par le
CMA-ES ; posé avant le halo d'escape, défait par le halo. Deux correctifs
justes peuvent s'annuler — c'était déjà arrivé le 2026-08-27 entre le clamp et
le centrage des dominants. L'ordre fait partie du correctif, pas de son emballage.

**NEVER** mesurer une distance entre footprints depuis leurs ORIGINES. L'origine
d'un module est sur sa pastille 1 : le courtyard de l'ESP32-WROOM va de -30,74 à
+10,51 en y. « À 3 mm de l'origine » place le voisin DANS le module.
`_boite_locale_fp` porte ce décalage — s'en servir, toujours.

**NEVER** livrer une règle sans une garde qui prouve qu'elle est APPELÉE. Une
règle correcte jamais invoquée est indistinguable d'une règle absente : c'est
exactement ce qui a masqué pendant des semaines le fait que le Géomètre ne
tournait jamais en production. Tester le comportement ET le câblage.

**NEVER** lire un `0 %` comme un verdict de routage. « 0 % (aucun moteur) » est
une panne — moteur injoignable, budget épuisé avant le repli. Escalader
là-dessus revient à payer une couche de cuivre pour un défaut d'infrastructure.
Distinguer toujours « mesuré à zéro » de « jamais mesuré ».

**NEVER** conclure qu'un processus est bloqué en comparant l'horloge à la date
d'un journal. La machine de développement se met en veille : le 2026-08-29,
deux fois, un banc a paru muet pendant 39 minutes alors qu'il avait 8 minutes
de temps d'exécution réel. La seule mesure fiable est `etime` du processus, ou
sa consommation CPU — jamais l'écart entre deux horodatages.

**NEVER** faire tourner une mesure longue dans un conteneur qu'une autre session
peut redémarrer. Deux mesures de `stm32-100` ont été perdues ainsi (redémarrages
à 07:10 et 07:17, `restarts=0` — donc voulus, pas des plantages). Un banc se
lance dans SON conteneur, monté sur les mêmes sources.

**NEVER** faire confiance aux tests présents dans l'image Docker : ils datent du
build. Huit « régressions » lues le 2026-08-29 n'étaient que des tests périmés ;
après copie de ceux du disque, 31/31 vert. Copier `tests/` avant de conclure.

**NEVER** calibrer une règle sur une source VOISINE de celle qu'elle mesure. Le
plancher d'échappement a été calibré sur `circuit.json` alors que le code lit le
board : 43 signaux contre 36, et la règle laissait passer exactement le cas
qu'elle devait attraper — tests unitaires verts des deux côtés.

**NEVER** confondre une pastille avec une liaison. Sur un board, CHAQUE pastille
porte un net, y compris celles qui ne vont nulle part (`Net-(U1-Pad3)`). Un net
présent sur un seul boîtier n'a personne à rejoindre. Sans ce filtre, tout
LQFP-48 comptait ~45 signaux quel que soit son circuit.

**NEVER** livrer une règle numérique sans l'avoir passée sur les DONNÉES RÉELLES
du projet. Les deux défauts ci-dessus ont franchi une suite complète de tests
unitaires ; l'un et l'autre sont tombés au premier passage sur les sept boards
du banc. Une fixture dit ce qu'on a imaginé, un board dit ce qui est.

### Leçons inscrites le 2026-08-31 — la réservation d'échappement

**NEVER** insérer une fonction entre un décorateur et sa cible. `@router.post(
"/route/auto")` a décoré `_armer_abandon` pendant toute sa vie : FastAPI
exposait cette fonction et `route_auto` était injoignable par HTTP. Le banc ne
pouvait pas le voir — il importe `route_auto` directement en Python. Une garde
qui interroge la TABLE DE ROUTES (`router.routes`) répond à la vraie question ;
une garde qui lit le fichier source, non.

**NEVER** écrire une regex qui suppose que deux champs se suivent dans un
board. KiCad intercale `(uuid "…")` entre `(layer)` et `(net)` d'un segment :
231 segments d'un board réel, **0 reconnu**. C'est le dixième piège de forme du
projet. Chercher chaque champ dans son bloc, jamais en une seule expression.

**NEVER** faire confiance à une branche de code qu'aucun appelant de production
n'atteint. La branche qui portait le net de chaque via existait, son commentaire
avertissait du court-circuit, et seule une **fixture de test** y allait — une
fixture qui mettait d'ailleurs un NOM là où le runner met un entier. Compter les
appelants réels fait partie de la revue.

**NEVER** annoncer dans un fichier une référence que le fichier ne déclare pas.
`_confier_au_plan` retire `(net GND …)` du DSN ; on écrivait `(net GND)` dans le
`(wiring)` deux lignes plus bas. Écarter et le DIRE ; et ne jamais transformer
une lecture ratée en verdict — une section `(network)` illisible n'écarte rien.

**NEVER** recalculer ce qui a déjà été mesuré au bon moment. La sortie
d'échappement était calculée avant le routage, quand la place existait, puis
**jetée** : seuls `ref` et `pad` traversaient, et la recherche repartait de zéro
sur le board routé. Rejouer la position — après l'avoir vérifiée — au lieu de la
rechercher. Gardes : `tests/test_wiring_reservation_resoluble.py`,
`tests/test_reprise_des_sorties_reservees.py`.

**NEVER** laisser un échec rendre la même valeur que son cas normal. Le dernier
recours du routage (`_recuperer_jobs_abandonnes`) appelait `_api`, définie
**à l'intérieur** d'une autre fonction : chaque appel levait `NameError`, avalé
par un `except Exception`, et rendait `None` — exactement ce que rend son cas
légitime. Il n'a jamais fonctionné, et `stm32-100` est sortie à zéro alors qu'un
board à 81 % l'attendait dans la JVM. Le défaut est apparu **la minute** où le
diagnostic a été ajouté. Compter les raisons d'un échec n'est pas du confort.

**NEVER** concaténer deux listes calculées séparément sans se demander si elles
se recouvrent. `_vias_a_reserver` (pastilles vues isolées par le DRC) et
`_vias_gnd_preventifs` (toutes les pastilles GND fine-pitch) partagent leurs
cas les plus critiques ; le doublon posait deux vias au même point, donc une
violation `hole_to_hole`, donc le rejet TOUT-OU-RIEN des vingt et un vias.

**NEVER** ancrer une garde sur le NOM de l'appelant. Deux gardes cherchaient
`_api("PUT", …` et se sont mises à lever `ValueError` dès que cette fonction a
été renommée — elles ne mesuraient plus rien, mais leur intention était intacte.
S'ancrer sur ce qui ne bouge pas : ici l'URL du départ de job.

### Leçons inscrites le 2026-09-01 — la mesure qui dormait à côté du code

Les cinq défauts corrigés ce jour-là ont **la même forme** : la mesure juste
existait, au bon endroit, calculée à chaque appel, et personne ne s'en servait.
C'est la famille de `FunctionalCluster.max_distance_mm`.

**NEVER** traiter un TROU comme du CUIVRE. `_obstacles_d_un_autre_net` écarte
volontairement les objets du net courant : correct pour du cuivre — deux pistes
GND peuvent se toucher — et faux pour un perçage. La couture reposait donc à
chaque passe un via au même point : `nucleo-f401` portait **131 vias pour
94 positions**, 7 positions percées ×5, une ×10, et **116 avertissements
`holes_co_located`** — la TOTALITÉ des violations ajoutées par le routage.
Garde : `tests/test_couture_sans_trou_double.py`.

**NEVER** classer deux défauts par ordre lexicographique sans se demander ce
qu'on échange. `_secours_est_meilleur` rendait `apres < avant` sur
`(erreurs, manquantes)` : `(0, 73) < (3, 11)` est VRAI parce que `0 < 3`. Trois
erreurs ont été achetées avec **soixante-deux connexions manquantes**, par un
repli dont le site d'appel dit qu'il existe parce qu'« une carte non connectée
ne part pas en fabrication ». Interdire toute augmentation aurait sur-corrigé —
un test antérieur documente que `(2, 0) → (0, 1)` doit rester accepté. La règle
retenue ne porte aucun seuil : **un échange ne doit pas empirer le total**.

**NEVER** faire taire un DRC en annulant une décision de l'utilisateur. Les
4 `starved_thermal` disparaissaient en passant tout le plan en connexion pleine
— mais le relief thermique de KiCad avait été choisi la veille, capture à
l'appui, et un 0402 noyé dans le cuivre se dresse à la refusion. On promeut
donc les **seules** pastilles mesurées comme affamées. Mesuré :
`4 erreurs → 0`, `75 violations → 71`.

**NEVER** viser une population PROXY quand la population RÉELLE est mesurable.
L'étape ③ ne ciblait que les broches GND des boîtiers fine-pitch. `D3.2` (LED
0603) et `J10.1` (connecteur traversant) finissaient orphelines sans avoir
jamais été visées — et `_pads_isolees_du_plan` les désignait, **une ligne plus
haut dans la même fonction**, pour la seule vérification d'après-coup. La cible
préventive reste (les broches deviennent orphelines PENDANT le routage) ; on lui
AJOUTE la cible mesurée. Union strictement additive.

**NEVER** lire deux compteurs voisins comme s'ils mesuraient la même chose.
« 1 reliée sur **3 visées**, 0 renoncée » à côté de « **1** l'étaient avant la
pose » ressemble à une incohérence comptable : ce sont deux populations
différentes (préventive et mesurée), toutes deux légitimes. J'ai failli
« corriger » une comptabilité saine. Lire les DEUX définitions avant de conclure.

**NEVER** conclure d'un `budget épuisé` que la cascade est mal ordonnée. Après
une veille de la machine, le budget se voyait consommé et le Niveau 1 était
**sauté** (`_budget_suffisant` faux) — la chaîne tombait au Niveau 4,
`kicad-tools`. Le journal montrait donc `kicad-tools A*` en tête alors que
Freerouting est bien Niveau 1. Symptôme d'infrastructure, pas de conception.

**NEVER** laisser un faux `pcbnew` de test plus pauvre que le vrai `BOARD`. Le
faux n'exposait que `Footprints()`, pas `GetFootprints()` — que la production
utilisait déjà ailleurs. Compléter le faux, jamais affaiblir le code pour lui.

**NEVER** ancrer une garde sur une phrase qu'on vient d'écrire ailleurs. Ma
propre garde cherchait `"repli GND retenu"` par `index()` et tombait sur la
docstring de la règle, en amont du site d'appel. `rindex()`, ou un ancrage sur
ce qui ne bouge pas.

### Leçons inscrites le 2026-09-09 — quand l'INSTRUMENT ment

L'utilisateur juge les placements le 2026-09-08, captures à l'appui : « le
placement, c'est un placement d'amateur ». Il avait raison, et la journée a
produit deux familles de leçons — sur le produit, puis sur les outils de mesure
eux-mêmes.

**NEVER corriger un piège de forme sans chercher SES SŒURS.** `_NET_DECL_RE` a
été corrigé le 2026-08-20 pour la double écriture `(net 3 "GND")` /
`(net "GND")`. Trois expressions de `_patch_floating_nets` portaient la même
hypothèse et sont restées fausses **vingt jours de plus**. Or tous nos boards
sortent de pcbnew 10 (`numérotés=0, nus=93..988`) : la réparation ne touchait
RIEN, en silence, et six cartes sur onze livraient des broches
d'**alimentation** sur des nets orphelins — dont la sortie d'un régulateur.
Le DRC ne pouvait pas le voir : un net orphelin n'a aucune connexion manquante.

**NEVER se satisfaire du premier défaut trouvé.** Sous celui-là s'en cachait un
second : le découpage des pastilles s'arrêtait sur UNE tabulation, quand pcbnew
10 en écrit deux — la **dernière pastille de chaque empreinte** n'était jamais
réparée. Et ma première correction fut pire que le mal : s'arrêter au premier
`(` coupait le bloc AVANT le champ `(net …)`. **Une expression trop large et une
trop étroite échouent identiquement, en silence.** On compte les parenthèses.

**NEVER supposer qu'un levier natif est appelé parce qu'il existe.** Quatre de
plus trouvés ce jour-là, publics, documentés, jamais invoqués :
`WorkflowConfig.grid`, `OptimizationWorkflow(constraints=…)`,
`PCB.move_reference()`, `optim/bottom_up_placement.py`. Cela porte à **six** avec
`FunctionalCluster.max_distance_mm` et `anchor_pin`. Mesure : `grid` non passé
donnait **2 composants alignés sur 62**.

**NEVER poser un alignement AVANT les étapes qui déplacent.** `grid=0.5`
correctement transmis n'a rien changé — `2/62` avant, `2/62` après : le natif
aligne en fin d'optimisation, puis le Géomètre, le halo, le snap et l'Inspecteur
défont tout. Reposé EN DERNIER : **2/62 → 62/62, zéro erreur ajoutée**.
« L'ordre fait partie du correctif » vaut aussi pour ce qui ne déplace que de
0,25 mm.

**NEVER ignorer ce que dit une référence EXTERNE.** `astra_piNas` (six couches,
176 empreintes, routée à la main) a révélé une loi qu'aucune mesure interne ne
pouvait montrer : **notre qualité se dégrade avec la TAILLE, la sienne non** —
3,0 mm de serrage à 5 composants, 55,3 mm à 62, quand elle tient 9,8 mm à 176.
Un banc qui ne compare que nos cartes entre elles mesure une dérive, pas un
écart à l'état de l'art. ⚠️ Le dépôt source n'a **aucune licence** : la carte
n'est pas versionnée, un script la récupère.

#### Et trois fois, c'est l'INSTRUMENT qui a menti

Chaque fois en rendant **« aucun effet »** — c'est-à-dire la réponse qu'on
attendait peut-être. C'est la forme la plus coûteuse de la famille que ce dépôt
traque, parce qu'elle est indiscernable d'un résultat légitime.

**NEVER piloter le SERVICE par une variable d'environnement du pipeline.**
`run_pipeline.py` est un client HTTP ; le placement tourne dans le service
FastAPI, un processus séparé. Une campagne A/B entière a comparé deux bras
identiques — `98 %` contre `98 %`. Le remède suit le motif du verrou de routage :
un **fichier** (`tools/reglages_banc.py`), seule ressource que des processus
séparés partagent, **relu à chaque appel** — un réglage figé à l'import ferait
hériter le second bras du premier.

**NEVER mesurer après avoir édité un module que le service a déjà importé.**
Deuxième campagne, échec différent : le service tournait depuis **neuf heures**
avec un `tools/placement.py` antérieur à la règle. `tools/` est monté à chaud —
le FICHIER change, le MODULE importé non. Le dépôt connaissait l'exception (« le
runner ENFANT relit à chaque appel ») ; le workflow de placement, lui, tourne
DANS le worker. **Redémarrer le service avant toute mesure**, et vérifier que le
`mtime` du module précède le démarrage du processus.

**NEVER ancrer une garde sur une phrase de sa propre documentation.** Ma garde
« on ne pousse jamais la référence en `F.Fab` » cherchait `F.Fab` dans le source
et le trouvait… dans la docstring qui l'interdit. Piège déjà inscrit le
2026-09-08 ; `_code_seul()` retire commentaires **et** docstrings.

**NEVER relancer après une mise à mort sans nettoyer le conteneur.** Un pipeline
tué côté Windows **continue** côté conteneur : quatre orphelins accumulés, deux
encore à 380 % de CPU vingt minutes plus tard, consommant la mémoire qui faisait
tuer la suivante. Une spirale alimentée par chaque relance. Lancer **détaché
dans** le conteneur (`docker exec -d`, journal redirigé), et vérifier les
orphelins avant de repartir.

**NEVER généraliser depuis un journal de mise au point.** J'ai lu « les seize
paires refusées, sans exception » et bâti une décision produit dessus. La mesure
l'a réfutée : la garde ne gèle rien — sur les mêmes boards elle déplace déjà 19
à 36 composants. `D-2026-09-08-c` retirée. Une mesure étaye une proposition ;
elle peut aussi la tuer, et c'est son travail.

### Leçons inscrites le 2026-09-20 — la mesure qui rendait « pas de mesure »

**NEVER laisser une mesure rendre la même valeur qu'une mesure impossible
sans l'avoir lue sur un vrai board.** `_longueur_de_fil_mm` — le « second
critère » qui départage deux placements propres depuis le 2026-08-29 — rendait
`None` à CHAQUE appel : `PCB` n'était pas importé dans `tools/placement.py`,
et le `NameError` était avalé par un `except Exception: return None`. Pendant
trois semaines, on a gardé « le premier tirage arrivé » en croyant choisir le
plus court. Trouvé le 2026-09-20 en ajoutant le critère des CROISEMENTS
(`crossing_count`, natif), qui échouait de la même manière — et seulement
parce que je l'ai mesuré sur carte-10 avant de livrer. Garde : les deux
mesures sont lues sur un vrai board du banc
(`tests/test_placement_classe_par_croisements.py`).

**Ce que le classement des placements compare, désormais :** conflits, puis
croisements du chevelu (relatif entre tirages d'une même carte, jamais un
seuil — demande de l'utilisateur : « une solution qui marche sur tout type
de carte »), puis fil. Mesuré : 0,15 s sur stm32-100.

**« Tous les tirages ont figé » est un VERDICT sur le placement, pas une
panne.** Il sortait `skipped` comme un service éteint, et l'orchestrateur
abandonnait au lieu de re-tirer le placement — le seul remède. La réponse
porte `verdict="tirages_figes"` et le pourcentage MESURÉ (jamais un board) ;
`shouldRetryPlacement` s'arme, `shouldRescueRouting` refuse tout échec (le
reasoner aurait écrasé le cache avec le board placé). Gardes :
`tests/test_tirages_figes_verdict.py`, `routing-tirages-figes-verdict.test.ts`.

**NEVER re-placer un board DÉJÀ placé sans avoir DRC-é le board placé, sans
piste.** `restore_pad_angles` recompose `rotation du boîtier + angle RELATIF
de la source`, mais `_pad_angles` rendait l'angle DÉCLARÉ — absolu dans un
`.kicad_pcb`. Source sortie de gen_pcb (boîtier à 0°) : aucun écart. Source
déjà placée, boîtier à 90/270° : rotation comptée DEUX FOIS, pads du LQFP
couchés sur leurs voisins — **205 erreurs sur un board sans une piste**, dont
168 items sur U1. Motif mesuré le 2026-09-20 : 05, 07, 09, 10 (90/270°)
échouent, 04, 06, 08 (0/180°) passent. Et le RE-TIRAGE de l'orchestrateur
renvoie justement au placement le board du cache, déjà placé : la boucle de
sauvetage empoisonnait une carte sur deux. Le symptôme, « ~120 conflits de
placement non résolus », m'a fait chercher dans le génétique pendant deux
jours — le compte vient du DRC kicad-cli, `PlacementAnalyzer` n'en voyait
que 2. Corrigé : relatif = (déclaré − rotation du boîtier source) mod 360 ;
205 → 1. Garde : `tests/test_pad_angles_source_deja_pivotee.py`.

### Leçons inscrites le 2026-09-21 — la boîte qui ne tournait pas

**NEVER ajouter `_boite_locale_fp` à `fp.position` sans la TOURNER.** Elle rend
le courtyard dans le repère du footprint. `_repair_off_board` la posait telle
quelle : un SOT-223 à 90° (8,8 × 7,2) était testé COUCHÉ, la case « libre »
tombait dans son vrai courtyard, et carte-05 comme carte-09 sortaient à UNE
erreur `courtyards_overlap` (U2 ↔ passif). `PlacementAnalyzer`, qui approxime
les courtyards par « pastilles + 0,5 mm », répondait « 0 ERROR ». La règle vit
à UN endroit, `placement._boite_orientee_fp`, et un filet
(`_reparer_chevauchements_du_drc`) répare avec l'instrument qui JUGE —
kicad-cli — sans jamais garder un résultat qui n'améliore pas.

**NEVER supposer le SENS de rotation de KiCad : le lire dans pcbnew.** L'axe y
descend : (x, y) → (x cos a + y sin a, −x sin a + y cos a). Le sens opposé est
INVISIBLE sur un boîtier centré et faux dès que la boîte est décentrée.
`_pastille_partagee` le portait : sur le banc, 312 pastilles de boîtiers
tournés étaient calculées à **7,1 mm** en moyenne de leur vraie place
(0,08 mm dans le bon sens) — la capa de découplage visait une broche absente.
Restent non convertis, à boîte non tournée : `_clamp_fixed_refs_to_outline`,
`_position_libre_pour_ancrage`, `_ecarter_des_dominants`, `contour_et_bords`,
`carte_compacte` (aires seulement). Sans effet tant que les ancrages sont à 0°.

**Un ancrage n'était collé au bord QUE s'il débordait.**
`_clamp_fixed_refs_to_outline` ramène ce qui sort du contour ; un connecteur
que le générateur pose DANS la carte y restait pour toujours (carte-09
compacte : J2 à 15,7 mm de tout bord, les six autres à 2-3 mm). Règle de
l'utilisateur — « toujours les connecteurs à l'extrémité » —
`_coller_les_ancrages_au_bord`, juste après le clamp : glissement vers le bord
LE PLUS PROCHE du corps, puis le long de ce bord s'il est occupé ; dominants
exempts. ⚠️ Ce n'est PAS D-2026-09-13-c (B), réfutée : on ne centre rien.
Mesuré : 08 et 09 compactes, 7 connecteurs sur 7 à 2,0 mm, 0 erreur DRC.
Garde : `tests/test_ancrages_colles_au_bord.py`.

**NEVER mesurer « connecteur au bord » depuis l'ORIGINE.** L'origine d'un
en-tête est sur sa pastille 1 : « J2 à 11,4 mm du bord » était un artefact,
son CORPS était à 2 mm. Gardes : `tests/test_boite_orientee_sens_de_kicad.py`,
`tests/test_chevauchements_vus_par_le_drc.py`.

### Leçons inscrites le 2026-09-22 (soir) — le board propre qui se prêtait à tout

**NEVER mesurer un défaut sans avoir vérifié que l'artefact le PORTE.** J'ai
diagnostiqué la dernière rupture de plan de `carte-10` sur
`expected/final.kicad_pcb`, board VERSIONNÉ du 2026-09-21 dont le propre
`mesures.json` annonce `non_connectes: 0` — et mon DRC le confirmait. Le
défaut du banc du 22 vivait dans `/tmp/livr/…/route.kicad_pcb`, **resté dans
le conteneur**, faute que ce fichier s'interdit pourtant depuis le 2026-09-03.
Sur le board propre, tout marchait : 92 points sur 93 de l'îlot orphelin
faisaient face au plan principal, un via y tenait avec 0,29 mm de marge, et la
couture de production le posait en annonçant `stitched: 1`. J'ai failli
annoncer une solution pour un board qui n'a jamais eu le problème. Sur le VRAI
board, la même sonde rend **zéro** vis-à-vis avec le plan principal.
Un board sain se prête à toutes les démonstrations : vérifier d'abord que
l'instrument voit le défaut.

**NEVER laisser une sonde raisonner ZONE PAR ZONE sur un plan.** Ma première
sonde ne regardait que les îlots d'UNE zone : or `carte-10` porte **deux zones
GND**, une par face, et le vis-à-vis d'un îlot F.Cu vit dans l'AUTRE zone.
Elle rendait donc « aucun cuivre en face » pour la totalité des points, sur une
carte qui porte un plan arrière de 2656 mm². Détectée par l'invraisemblance du
résultat, jamais par le code — c'est la quatrième sonde de ce projet sauvée de
cette façon.

**NEVER reprendre une mesure faite sur une AUTRE carte comme si elle décrivait
le cas courant.** Le brief décrivait l'amas « cerné par un faisceau, jusqu'à
18 segments `+3V3` » : c'était `carte-07`. Sur `carte-10`, la mesure donne
**un seul segment par face** (`EXT2_1` à 0,862 mm sur F.Cu, `EXT4_1` à
0,781 mm sur B.Cu). Le défaut paraissait coûteux à refermer ; il ne l'est pas.

**Consulter les agents coûte de la MÉMOIRE, et cette charge fausse les
mesures.** Codex lit ce fichier, y trouve « Use Graphify by default before
source browsing », et lance `graphify query` — **1,04 Go par requête**. Deux en
parallèle ont fait tomber la mémoire libre à 2,8 Go et tuer mes propres tâches
de fond ; c'est la même charge qui avait faussé un banc entier la veille.
Tout prompt d'agent externe commence désormais par l'interdiction explicite
d'exécuter graphify, et `codex exec` reçoit `< /dev/null` (sans quoi il attend
une saisie au clavier et ne rend jamais la main).

### Leçons inscrites le 2026-09-22 (nuit) — l'arrachage borné, et ses deux sœurs

**NEVER juger un plan ZONE PAR ZONE.** Notre générateur écrit UNE ZONE PAR
FACE. `_relier_les_amas_orphelins` calculait ses orphelins sur la zone
courante : tout îlot de F.Cu qui rejoint le plan par B.Cu passait pour orphelin.
Mesuré sur `carte-10` : **21 amas orphelins annoncés, UN seul en vérité** — et
les vingt autres recevaient du cuivre pour rien. `_stitch_zones` jugeait déjà
sur le net entier (`_ilots_relies_au_principal_du_net`) : deux jumelles, deux
réponses, et c'est la plus permissive qui posait le cuivre. Ma propre sonde
d'analyse avait fait exactement la même faute une heure plus tôt.

**NEVER échantillonner un trajet au pas de sa propre marge.** `_couloir_libre`
prenait `pas = marge` : un bond plus court que la marge n'était jugé que par ses
DEUX BOUTS. Or la distance à un cuivre est convexe le long d'un segment — son
minimum tombe à l'INTÉRIEUR, jamais aux extrémités. Mesuré : **426 violations de
dégagement**, toutes à 0,1993 mm pour 0,2000 exigés. Sept dixièmes de
micromètre, c'est-à-dire précisément ce qu'un échantillonnage à deux points
laisse passer. Pas ramené à `marge / 8`.

**Un remède tout-ou-rien se PROUVE par l'égalité, pas par l'absence de
plainte.** `_degager_le_couloir` arrache, pose, reroute, et remet tout en place
si un seul reroutage échoue. La preuve qu'il ne casse rien n'est pas « aucune
erreur nouvelle » : c'est le board rendu **strictement identique** au board reçu
— 33 violations, 0 erreur, 1 manquante, avant comme après.

**Une impossibilité peut se CALCULER, et elle DÉSIGNE alors le remède.** Le
couloir de `carte-10` fait 0,862 mm ; le raccord de masse le barre sur toute sa
largeur (0,25 de cuivre + 0,2 de dégagement de chaque côté = 0,65). Un signal de
0,25 mm en réclame 0,65 à son tour : il faudrait 1,30 mm. Aucune finesse ne
rattrape 0,44 mm manquants — donc la recherche sur la même face est vaine, et
la seule issue est de CHANGER DE FACE. Le calcul n'a pas dit « abandonne », il a
dit où chercher. Livré (`_detour_par_l_autre_face`) : **1 connexion manquante →
0**, à violations et erreurs inchangées.

**NEVER juger un board qui vient de recevoir du cuivre SANS avoir recoulé ses
plans.** Le détour par l'autre face traverse le plan coulé : le board
intermédiaire porte **51 erreurs** de dégagement, parfaitement réelles, que la
coulée efface en découpant le cuivre autour de la piste neuve. Juger avant de
recouler ferait rejeter un board qui, recoulé, est PARFAIT — 33 violations,
0 erreur, 0 connexion manquante. C'est la famille que ce dépôt traque, prise
dans l'autre sens : non plus un instrument qui absout un board fautif, mais un
instrument qui condamne un board sain.

### Leçons inscrites le 2026-09-24 — l'escalade qui ne pouvait pas monter

Question de l'utilisateur : « si on escalade le nombre de couches, on doit
atteindre 100 % ». Il avait raison en principe ; le code l'en empêchait, de
trois façons indépendantes. Et « je veux une solution générale, tu es en train
de bricoler la carte nucleo » — il avait raison là aussi.

**NEVER laisser une protection s'appliquer au-delà du tirage pour lequel elle a
été posée.** L'escalade incrémentale (D-2026-09-10-b) protège les pistes du
meilleur board au changement de palier. La protection restait posée pour TOUS
les tirages du palier ; comme le premier palier n'a droit qu'à un tirage de
preuve, **après le tout premier tirage, plus aucun n'était libre** — on ne
donnait pas plus de couches à la carte, on en donnait au premier tirage pour
qu'il se rapièce. Mesure sur `nucleo-f401` : 6 couches PIRES que 4. Désormais le
premier tirage d'un palier reste incrémental, les suivants sont libres
(`_tirage_libre`, D-2026-09-24-a). Preuve au banc du même jour, même placement
gelé : **palier 4, tirage protégé → 0 %, tirage libre → 100 %**.

**NEVER compter dans une autre unité que celle que la règle annonce.** « Arrêt
après deux paliers sans gain » comptait des TIRAGES (tolérance `2 × 3`). Le
palier 4 de `nucleo-f401` avait PROGRESSÉ, mais ses tirages bonus et figés ont
rempli le compteur : **8 couches jamais essayées**, et un journal qui disait
« 7 paliers » pour 7 tirages. Les bonus, faits pour aider, fermaient la porte
au palier suivant (`_paliers_sans_gain_apres`, D-2026-09-24-b).

**NEVER mesurer la distance d'une piste depuis ses EXTRÉMITÉS.** La libération
autour d'une pastille non reliée testait les deux bouts de chaque segment. Une
diagonale de 13,7 mm passant à **0,533 mm** de la pastille restait protégée —
ses bouts étaient à 1,9 et 13 mm. Le défaut est structurel : une piste LONGUE a
presque toujours ses bouts loin de la zone, et c'est précisément elle qui la
traverse. Les trois segments gagnés sur `nucleo-f401` font 13, 43 et 44 mm
(`_segment_pres_d_une_zone`).

**NEVER confier un verdict de fabrication à la SÉVÉRITÉ que KiCad attribue.**
`hole_to_hole` et `holes_co_located` sortent en avertissement par défaut ;
tous nos juges ne comptaient que les `error`. `carte-11` a donc été livrée
`drc_clean: true` avec deux vias dont le perçage RECOUPE celui d'une broche de
connecteur (−0,050 mm) — et `drc_clean` ouvre le gate JLCPCB. Le docstring du
juge portait la prémisse fausse en toutes lettres : « une erreur de
fabricabilité fait refuser la carte, un avertissement non ». UNE liste,
`TYPES_BLOQUANTS_FABRICATION`, UN prédicat, `est_bloquante`, lus par le juge de
la commande ET celui du routage (D-2026-09-24-c).

**NEVER oublier de porter un filtre chez les SŒURS — quatrième fois.**
`_pads_plan_a_degager` excluait les pastilles traversantes depuis le
2026-09-02, en toutes lettres. `_pads_gnd_fine_pitch` et
`_pads_signal_fine_pitch` ne l'ont jamais reçu : un connecteur 2×20 au pas de
2,54 mm passait pour un boîtier « fine-pitch » (40 pastilles), et sa broche GND
recevait un via d'échappement **dans son propre perçage**. Le correctif
général a réparé aussi `nucleo-f401`, dont les connecteurs Morpho portaient le
même défaut latent — une carte que personne ne regardait sous cet angle.

**Une escalade qui marche n'est pas un tirage libre qui marche.** Sur
`carte-11`, le banc a sorti 100 % à 4 couches — mais le palier 2 avait figé
sans rendre de board, donc il n'y avait rien à protéger ni à libérer : le
mécanisme corrigé n'a pas joué. Et un 100 % de `nucleo-f401` obtenu DÈS LE
PREMIER PALIER a failli être annoncé comme la preuve du correctif de
libération, qui n'avait pas tourné. **Lire dans le journal QUEL mécanisme a
produit le résultat**, jamais seulement le résultat.

**NEVER écrire « ✅ résolu » sur une preuve qui ne couvre qu'un des cas.**
J'ai annoncé l'escalade « résolue » sur `nucleo-f401`, `carte-10` et `carte-08`,
trois cartes où il manquait un SIGNAL. Quand seule la MASSE manquait, une règle
du 2026-08-31 interdisait toujours de monter — et le BANC plafonnait dix
cartes sur quinze à 2 couches (D-2026-09-24-f). J'ai même « corrigé » à tort
`carte-07` en « escaladée à 4 et 6 » : ces lignes du journal étaient celles
de `carte-08`, démarrée la même minute. **Un journal partagé ne dit pas de
quelle carte parle une ligne : l'attribuer par l'heure, jamais par la
proximité.** L'utilisateur l'a relevé en une question : « si
98 %, il manque 2 %, j'escalade ? ». Toute connexion manquante fait désormais
monter d'un palier (D-2026-09-24-e).

**NEVER arrondir un pourcentage de complétude.** `_percent_verifie` rendait
`round(99,6) = 100` pour un net manquant sur 250 : le cas de SUCCÈS, rendu sur
une carte incomplète, et `route_auto` s'arrêtait là. Plafonné à 99 dès qu'un
net manque — encore un échec qui rendait la valeur du cas normal.

### Leçons inscrites le 2026-09-23 (ter) — l'ERC, et deux réfutations utiles

**NEVER analyser un fichier de plusieurs centaines de kilo-octets DANS le
worker uvicorn.** `run_kicad_tools_erc` appelait `Schematic.load`, du Python
pur, qui tient le GIL pendant toute l'analyse. Deux cartes du banc perdues le
même jour sur un **HTTP 500 de `/erc`** — `carte-08` (190 ko) et `carte-10`
(141 ko) — parce qu'uvicorn tue par SIGKILL tout worker muet plus de 5 s.
C'est la **sœur** du défaut corrigé le 2026-09-10 sur le journal Freerouting :
le journal avait été traité, le schéma non, alors que ce fichier l'interdisait
déjà en toutes lettres. `tools/erc_runner.py` rejoint les quatre autres
runners. **Corriger un défaut dans une fonction sans chercher ses sœurs coûte
toujours une deuxième fois.**

**NEVER laisser une EXPIRATION tuer un run quand un verdict réel existe
déjà.** Le budget de `kicad-cli sch erc` valait 30 s à plat, et son dépassement
remontait en 500 : le routage entier perdu, alors que kicad-tools avait rendu
son verdict quelques lignes plus haut. Le budget se déduit désormais de la
taille du schéma (plancher 120 s, quatre fois le point d'échec), et une
expiration conserve le verdict acquis en le DISANT. Famille « le plafond n'était
pas UN endroit, mais QUATRE ».

**NEVER conclure d'un écart de DURÉE entre deux bancs qu'un changement a
ralenti la chaîne.** `carte-06` a mis 468 s, puis 3204, puis 1140, sans que rien
ne change dans son circuit : Freerouting est stochastique et tourne jusqu'à
mille passes sans gain. J'ai failli annuler un correctif sain sur cette seule
observation. Deux tirages ne prouvent rien — la règle vaut aussi pour le temps.

**Deux propositions mesurées et RÉFUTÉES le même jour, et c'est le travail de
la mesure.** Resserrer le CADRE des connecteurs sur la frontière du circuit :
aucun gain de taille, connecteurs entassés sur un seul bord, deux se
chevauchant — annulé. Et le choix du bord par la DIRECTION, qui le remplace,
ne dégrade rien mais ne transforme pas le rendu : le gain visible est faible,
et il faut le dire plutôt que de le vendre.

### Leçon inscrite le 2026-09-23 (bis) — j'ai faussé mon propre banc, DEUX JOURS après l'avoir écrit

**NEVER lancer QUOI QUE CE SOIT pendant un banc — y compris une revue en
lecture seule.** Le 2026-09-22, ce fichier a reçu « la qualité du routage dépend
de la CHARGE » après qu'une consultation d'agent eut fait échouer 3 tirages sur
3. Le lendemain, j'ai lancé une revue multi-agents pendant le banc, en me disant
qu'elle ne touchait à rien. `carte-08` est sortie `abouti=False` sur un **HTTP
500 de `/erc`** : `kicad_tools/sexp/parser.py` a tenu le GIL **plus de 4,5 s**
sur un schéma de 190 ko pendant que cinq agents se disputaient le processeur, et
uvicorn tue tout worker qui ne répond pas à son ping en 5 s (leçon du
2026-09-10). Relancée seule : **193 s, 0 erreur, 0 manquante.**

Le placement n'était pas en cause. La charge l'était, et c'est moi qui l'avais
mise. Une règle écrite n'est pas une règle appliquée — c'est vrai du code, et
c'est vrai de moi.

**NEVER répartir des composants en déplaçant ce qui est déjà posé.** Le remède
au tas de périphériques ne change QUE l'angle de départ de la recherche : le
premier de chaque groupe garde exactement la direction que la graine a
calculée, les suivants s'en écartent en éventail, et `le_long_du_rayon` reste
seul juge de ce qui est libre. Une répartition qui déplacerait les directs
perdrait la topologie — la broche que chaque périphérique doit viser.

### Leçon inscrite le 2026-09-23 — le banc mesurait ce que le produit ne fait pas

**NEVER laisser le BANC appeler le service autrement que la PRODUCTION.**
`run_pipeline.py` n'envoyait pas `auto_size_board` à `/place/auto` : le
resserrement du contour sur le placement, écrit le 2026-09-13, n'a donc JAMAIS
tourné dans le banc — alors que `handlePlacement`, en production, le passe
depuis toujours. Le banc mesurait un comportement que le produit n'a pas, ce
qui est l'inverse exact de ce à quoi il sert. Mesuré sur `carte-10` : carte de
140 × 105 mm pour un circuit de 51 × 66, **23 % d'occupation**, connecteurs à
56-75 mm, `VIN` long de 112 mm. Une ligne de correctif donne 61,0 × 45,8 mm,
56 % d'occupation, `VIN` à 45,5 mm, et **le routage reste à 100 %, 0 erreur,
0 manquante** sur les dix cartes.

C'est le **septième** levier natif que ce projet trouve écrit et jamais appelé,
après `max_distance_mm`, `anchor_pin`, `WorkflowConfig.grid`, `constraints`,
`move_reference`, `bottom_up_placement` et `LocalRerouter`. Le motif est
toujours le même : la règle existe, elle est juste, et rien ne prouve qu'elle
est INVOQUÉE.

**Une carte trop grande coûte du TEMPS, pas seulement de la place.**
`carte-08` passe de 2002 s à 347 s, six fois plus vite, pour le même circuit.
Ce fichier portait déjà la mesure — « l'espace de recherche d'un routeur croît
avec la SURFACE × le nombre de nets » — sans jamais en tirer la conséquence.

**NEVER rapporter une taille de carte prise dans le SCHÉMA.** Le banc écrivait
`board_mm` d'après ce que la description demandait, pas d'après `Edge.Cuts` :
`carte-10` était annoncée 140 × 105 quand son board mesurait 61,0 × 45,8, cinq
fois faux en surface, et rien ne permettait de s'en apercevoir. La règle de ce
dépôt — un compteur ment, un board non — vaut aussi pour la taille.
`mesures.json` porte désormais les DEUX : `board_mm` mesuré et
`board_mm_demande`.

### Leçon inscrite le 2026-09-22 — la qualité du routage dépend de la CHARGE

**NEVER mesurer un routage pendant qu'autre chose tourne sur la machine.**
Même placement gelé de `carte-10` : machine libre, **4 tirages sur 4 propres**
(139-392 s) ; machine chargée par une consultation d'agent lancée par mes soins,
**3 échecs sur 3** (603-1838 s). J'en avais tiré « défaut intermittent du plan
de masse, 1 tirage sur 8 » — c'était l'artefact de ma propre charge.

**Et c'est un vrai défaut, pas seulement une erreur de mesure** :
`_PLAFOND_ATTENTE_S = 300` est une horloge MURALE. Processeur disputé → moins de
passes par seconde → le plafond tire alors que le routeur progresse encore → le
tirage est déclaré figé et la chaîne garde un board moins bon. Ce fichier
interdit pourtant, depuis le 2026-08-29, de « conclure qu'un processus est
bloqué en comparant l'horloge » : la faute est ici DANS le code, pas dans une
lecture de journal.

**Corrigé le jour même, et c'était une SŒUR OUBLIÉE.** `_faut_couper` a trois
coupures ; `_routeur_muet` suivait déjà la cadence mesurée
(`max(300 s, 3 × cadence)`), le temps sans progrès comparait à 300 s en dur.
Le même fichier savait donc la règle et ne l'appliquait qu'à moitié. L'horloge
ne peut plus couper avant la fenêtre de passes. Preuve sous charge délibérée :
3 échecs sur 3 (603-1838 s) → **2 propres sur 2 (233 et 255 s)**.
Garde : `tests/test_coupure_suit_la_cadence.py`.

### Leçons inscrites le 2026-09-21 (soir) — les jumeaux qui se portent garants

**NEVER laisser DEUX remèdes se valider l'un l'autre sur le même objet.** Un
amas orphelin du plan GND (un îlot par face, cousus entre eux par un via) était
invisible aux deux filets à la fois : `_stitch_zones` comptait ce via comme un
succès — un site avait été trouvé — et `_retirer_ilots_flottants` voyait ce
MÊME via « toucher du cuivre du net en face », donc ne retirait rien. Les
jumeaux se portaient garants l'un de l'autre, et carte-07 sortait à une
connexion manquante GND, une fois sur huit. Diagnostic convergent de Codex, GLM
et OpenCode le même jour, sur un brief qui listait les pistes déjà réfutées.
La couture ORDONNE désormais ses candidats vers le cuivre du PLAN PRINCIPAL
(`_cuivre_principal_en_face`) — on ordonne, on ne filtre pas, « exiger » ayant
été réfuté le 2026-09-01.

**NEVER relayer le message d'un DRC comme une description de la géométrie.**
« Zone [GND] on B.Cu <-> Zone [GND] on F.Cu » se lit « les deux faces ne sont
pas reliées » ; le board portait pourtant 23 vias reliant les deux plans. Le
DRC nomme la ZONE, pas l'îlot. J'ai bâti là-dessus une explication fausse, que
l'utilisateur a relevée en une phrase : « tu comptes faux ? ».

**NEVER raccorder un îlot de plan par une LIGNE DROITE.** Un îlot est isolé PAR
une piste qui le coupe : toute droite vers le plan la retraverse. Mesuré —
« 5 amas vus, AUCUN raccordé ». Et **NEVER partir du BORD de l'îlot** : ce bord
est exactement à la distance de dégagement de la piste fautive, donc il n'y a
jamais la place d'y poser une piste. On part de la PASTILLE (avis de GLM : le
sujet est la connectivité du pad, pas le cuivre de l'îlot), et on contourne
avec `_chemin_de_contournement` (A* borné en distance ET en nombre de nœuds).

**NEVER borner une recherche par la seule géométrie.** Une portée en
millimètres ne borne pas le TRAVAIL : chaque nœud interroge tous les obstacles
du board. `_NOEUDS_MAX_CONTOURNEMENT` plafonne les nœuds visités — sans lui,
`(portée/pas)² × obstacles` fait geler `route_auto`.

**NEVER porter un diagnostic dans un état de MODULE.** `_ILOTS_PERDUS` était
global ; `route_auto` étant un `def` sync, FastAPI l'exécute dans son pool de
threads et deux routages du même worker auraient mélangé leurs diagnostics.
Le constat voyage par la pile.

⚠️ **Ce qui reste OUVERT** : sur carte-07, les îlots orphelins sont
PHYSIQUEMENT ENCERCLÉS — aucun via ne les rejoint, aucun chemin ne les
contourne, et un budget quatre fois plus large ne change rien. Le remède
général est écrit ; ce cas-là ne se referme pas après coup. La suite est en
amont : ne pas laisser le routage enfermer une pastille de masse.

### Leçons inscrites le 2026-09-03 — la garde qui ment sur ce qu'elle couvre

**NEVER laisser une DISPENSE valoir au-delà de ce qu'elle a mesuré.** Le via
posé dans une pastille était exempté de dégagement, au motif juste qu'il
« hérite de l'isolement de sa pastille ». Vrai **sur la couche de la
pastille** : une pastille CMS n'existe que sur une face, le via traverse
jusqu'à l'autre, et y pose du cuivre que rien ne vouche. Mesuré à **0,048 mm**
d'une piste GPIO46 sur B.Cu, pour 0,2 mm exigés. La dispense est désormais
bornée à la couche de la pastille ; les autres sont vérifiées.
Garde : `tests/test_via_in_pad_traverse_les_couches.py`.

**NEVER faire confiance à une docstring qui promet de suivre une autre
fonction.** `_poser_via_dans_pastille` affirmait « réutilise exactement les
règles du fanout ». La phrase était vraie quand elle a été écrite ; le
renforcement du fanout, le matin même, l'a rendue fausse **sans que rien ne le
signale**, et le défaut ci-dessus a survécu une demi-journée de plus dans la
sœur. Quand deux fonctions doivent appliquer la même règle, **extraire la
règle** et poser une garde qui compare les deux — `_via_gene_par` existe pour
ça. Un prédicat inline dans deux fonctions ne peut être testé que par leurs
effets, et c'est ainsi qu'elles divergent.

**NEVER calibrer une règle sur `expected/` quand le code lit `output/`.** Ma
règle de dogbone trouvait 3 à 57 cibles sous Windows et **zéro** dans le
conteneur : `/app/examples` est CUIT DANS L'IMAGE, pas monté, et le banc
accepte une racine explicite (`banc_exemples.py /tmp/ex`) précisément pour ça.
Un banc entier perdu, sept cartes sur huit jamais mesurées. C'est la deuxième
fois que ce dépôt paie « calibrer sur une source voisine de celle que le code
lit » — la première était le plancher d'échappement.

**NEVER bâtir un diagnostic sur une sonde qu'on vient d'écrire sans la
confronter à une vérité connue.** Ma sonde d'îlots annonçait « tous les îlots
non reliés » sur un board que le DRC déclarait à une seule connexion près :
absurde, donc la sonde était fausse — `_touche_le_net_en_face` attend un NOM de
couche, je lui passais un identifiant. Trois sondes fausses dans la même
session, toutes détectées par l'invraisemblance de leur résultat, jamais par
leur code.

**NEVER conclure qu'un défaut de routage est STRUCTUREL sans plusieurs
tirages.** Voir la section routage : 23 points d'écart sur la même carte au même
placement, et deux tirages concordants qui ne prouvaient rien.

**ALWAYS sortir du conteneur ce qu'on veut garder.** `examples/` n'y est pas
monté : un board produit par le banc n'existe QUE dans le conteneur et part au
premier redémarrage — la leçon des worktrees vidés, transposée.

### Leçons inscrites le 2026-09-14 — la broche que personne ne nommait

Question de l'utilisateur : « pourquoi carte-10 n'escalade pas les couches si
elle ne route pas ». Elle escaladait (2 → 4 → 6, arrêt motivé) ; ce qui
manquait était UNE broche GND, U1.8, orpheline du plan à tous les paliers —
et du cuivre en plus ne relie pas une broche que rien ne désigne. Quatre
défauts génériques, chacun vérifié sur le vrai board :

**NEVER prendre les obstacles d'un TRAJET sur toutes les couches.** La piste
d'échappement ne vit que sur la couche de sa pastille ; seul le via traverse.
Une piste IO_L14 sur B.Cu, SOUS la pastille, faisait renoncer le fanout
(« aucune sortie dégagée ») alors que le couloir F.Cu était libre et qu'un via
GND attendait à 1,2 mm. Deux listes désormais (`obstacles` pour la piste,
`obstacles_via` pour le via). Preuve : 7 → 6 manquantes, U1.8 reliée.

**NEVER libérer, à l'escalade, le cuivre d'un net que le routeur ne route
pas.** Les tronçons et vias GND libérés autour d'une pastille non reliée
n'étaient pas rendus au routeur — GND est absent du DSN — ils étaient PERDUS
(« 51 LIBÉRÉ(S) » à chaque palier, puis « Pad 8 [GND] <-> Via [GND] » au DRC
final). Les nets de `_NETS_CONFIES_AU_PLAN` restent protégés.

**NEVER attendre du DRC qu'il NOMME la pastille en cause.** Il décrit une
coupure par ses deux items les plus proches — « Zone [GND] <-> Zone [GND] »,
« Track [GND] 1,2 mm <-> Track [GND] 1,2 mm » — et U1.8 n'apparaissait dans
aucune. Ni le fanout ni le repli GND ciblé ne visaient une broche sans nom.
`_pads_hors_du_cluster_principal` demande à pcbnew, zones coulées, quelles
pastilles du net sont hors de son amas principal : c'est la connectivité qui
désigne l'orpheline. Preuve : « pastilles visées : [] » → « [('U1', '8')] »,
et « repli GND CIBLE : … U1-8 » apparaît enfin dans le journal.

**NEVER laisser un souvenir pris à un palier interdire le suivant.** Le repli
GND ciblé refusé à 2 couches (une seule face de signal) était « DÉJÀ tenté »
à 4, où deux couches internes lui auraient donné un chemin. La signature d'un
échec porte le nombre de couches.

**NEVER reposer un tronçon par-dessus son jumeau.** Neuf tronçons identiques
de 1,2 mm sur un même via, un par repose. `_troncon_deja_la` avant la pose.

Gardes : `test_sortie_ne_voit_que_sa_couche.py`,
`test_liberation_epargne_les_nets_du_plan.py`, `test_orphelines_par_cluster.py`,
`test_repli_gnd_memo_par_palier.py`, `test_via_deja_la_troncon_seul.py`.

### Leçon inscrite le 2026-09-14 — le service tournait sur une image de juillet

**NEVER mesurer sans avoir vérifié que le SERVICE porte le code qu'on croit.**
Trois bancs de carte-10 ont été perdus le 2026-09-14 avant de comprendre :
l'image `cirqix-kicad:latest` datait du **19 juillet**, et
`docker-compose.yml` ne monte à chaud que `routers/`, `tools/`, `main.py`,
`security.py` et `observability.py`. Tout le reste — entrypoint compris —
vient de l'image.

Ce qui manquait, dans le dépôt depuis le 2026-09-12 :

    superviseur qui RELANCE la JVM Freerouting   absent  -> « JVM tuee mais pas revenue en 60 s »
    lancer_service.py (ping uvicorn 5 s)         absent  -> PID 1 = uvicorn nu

Conséquence mesurée : dès qu'un job figé faisait tuer la JVM, elle ne revenait
jamais et TOUT le routage basculait sur `freerouting-cli` — une JVM par job.
carte-10 : **5474 s** au lieu de 2686 s, paliers abandonnés à 86 %.

Le symptôme se lisait dans le journal (`freerouting-cli` au lieu de
`freerouting-api`) et j'ai mis trois bancs à le voir. Le diagnostic tient en
une commande :

    docker exec cirqix-kicad ps -eo pid,args --no-headers | head -1
    #  attendu : python3 /app/lancer_service.py …
    #  trouvé  : /opt/venv/bin/uvicorn …        <- image perimee

**ALWAYS** reconstruire l'image du service après tout commit touchant
`docker-entrypoint.sh`, `lancer_service.py`, le `Dockerfile` ou les
sous-modules — exactement la règle déjà inscrite pour `cirqix-worker` le
2026-09-12, jamais appliquée à `cirqix-kicad`. Vérification après
reconstruction : tuer la JVM et confirmer qu'elle revient.

### Leçon inscrite le 2026-09-10 — le worker que son propre superviseur abat

**NEVER lire deux lignes voisines d'un journal comme une cause et son effet
sans vérifier leur ORDRE.** Les `RemoteDisconnected` (« Child process died »)
ont reçu TROIS diagnostics faux en une journée — mémoire, JVM, plantage natif
`pcbnew` — le dernier parce que l'assert `PROPERTY_ENUM` apparaissait « à côté »
de la mort. Il apparaît 3 à 5 s **après**, imprimé par le worker SUIVANT qui
importe `pcbnew` au démarrage.

La cause, mesurée par une sonde (`faulthandler.dump_traceback_later`, thread C,
sans GIL) : **uvicorn 0.30 tue par SIGKILL tout worker qui ne répond pas à son
ping en 5 s** (`supervisors/multiprocess.py:170 process is hung, kill it`), donc
tout worker dont un appel C tient le GIL 5 s. Ici `read_text()` du journal
Freerouting — **564 Mo**, relu en entier deux fois par tour de sondage —
tenait le GIL 6 à 9 s. Rien de « dense » là-dedans : le symptôme suivait la
taille du journal, `carte-05` (26 composants) perdait 3 essais sur 4.

Correctif : `tools/journal_freerouting.py::LecteurIncremental` — lu par
incréments depuis le départ du job. Mesuré : 0 famine, routage 165 → 77 s.
Garde : `tests/test_journal_lu_par_increments.py`.

**NEVER** tenir le GIL plus de quelques secondes dans un worker uvicorn — un
gros `read_text`, `json.loads`, `re` sur des mégaoctets — ou le faire dans un
processus enfant. Le superviseur ne distingue pas « occupé » de « pendu ».

**NEVER** proposer un correctif sans instrument : « isoler pcbnew dans un
enfant » était en place depuis des semaines et n'aurait rien changé.

### Leçons inscrites le 2026-09-07 — cinq compteurs qui inventaient un succès

Une même faute, trouvée cinq fois en la cherchant volontairement : **un échec
rend la même valeur que son cas normal.** Elle était déjà inscrite ici, corrigée
au cas par cas ; c'est la première fois qu'elle est traquée comme une FAMILLE.

| où | ce qui était rendu | conséquence |
|---|---|---|
| `parse_routed_pct`, sortie illisible | `100` | « 100 % routé » sur 4 segments |
| `parse_routed_pct`, dénominateur nul | `100` | idem |
| `tools/reasoning.py`, `nets_total = 0` | `100` | idem |
| `_rapport_drc` indisponible | `{}` → 0 erreur | **5 gardes acceptaient tout** |
| escalade, palier illisible | 0 erreur | un palier faux gagnait |
| `handleReason`, pas de board | `success` + `ROUTING_DONE` | statut fantôme persisté |

**NEVER laisser un défaut corrigé dans une fonction sans chercher ses SŒURS.**
`_measured_routed_percent` portait déjà, mot pour mot, « un dénominateur nul
n'est pas une victoire — on renvoyait 100 ici ». Deux jumelles vivaient à côté,
intactes. Ce dépôt l'avait déjà payé avec `livrer_boards.py`, puis avec le
`_poser_via_dans_pastille` qui promettait de suivre le fanout.

**NEVER se contenter de JOURNALISER un défaut qu'on a compris.** `_rapport_drc`
avouait le sien en commentaire : « les appelants lisent le dict vide comme "rien
à signaler" — TANT QU'ILS LE FONT, ce journal est le seul endroit où l'absence
de verdict est visible ». Le journal a tenu la place du correctif pendant des
semaines, et cinq gardes « ne peut qu'améliorer » acceptaient n'importe quoi dès
que le DRC était muet — c'est-à-dire quand le board est justement suspect.

**NEVER écrire cinq fois la même comparaison.** Elles étaient identiques, donc
fausses identiquement. Une règle vit à UN endroit : `_aggrave_le_board`, qui
échoue fermé. Corollaire mesuré le jour même : **centraliser une règle ne doit
pas multiplier son coût** — ma première version re-jugeait le board de référence
à chaque tour de boucle, et c'est un test existant qui l'a attrapé.

**NEVER laisser une phrase rassurante tenir lieu d'audit.** L'en-tête de
`handler-reason.test.ts` affirmait que ce handler « n'a PAS été modifié » et
qu'il était « sûr par construction ». C'est exactement ce qui l'a soustrait à
l'examen, alors qu'il était le seul des huit sans garde fail-fast.

**Fermer une branche inatteignable vaut la peine.** Celle de `handleReason` ne
l'était que par une coïncidence entre deux fonctions qui ne se connaissent pas —
`shouldRescueRouting` exige un routage réussi, lequel écrit le cache. « Pas
atteignable aujourd'hui » n'est pas une garantie.

Trois candidats vérifiés SAINS, à ne pas ré-auditer : `_collect_violations`
refuse déjà de lire un rapport inconnu comme zéro violation ; les `return 0` de
`placement.py` comptent des composants DÉPLACÉS (« rien n'a bougé », pas « tout
va bien ») ; `reasoning-service.ts` échoue honnêtement à 0 % avec un warning.

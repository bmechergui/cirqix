# Journal des décisions produit — Cirqix

> Créé le 2026-08-30 après constat que des décisions produit avaient été prises
> et implémentées sans validation de l'utilisateur (voir CLAUDE.md §« Autonomie bornée »).
>
> Règles :
> - Toute décision produit (stratégie placement/routage, seuil chiffré, limite levée,
>   gate de sécurité, droits/facturation) DOIT figurer ici AVANT implémentation.
> - Statut : `en attente` → `validée` UNIQUEMENT sur confirmation explicite de
>   l'utilisateur dans la conversation. Jamais auto-validée par Claude.
> - `annulée` : décision inversée avant ou après livraison (garder la trace + la cause).

---

## En attente de validation

### D-2026-08-29-a — Snap bypass : levée de la limite « adjacence 13-28 mm »
- **Ce qui a été décidé sans validation :** la limite acceptée le 2026-06-18
  (« clusters à 13-28 mm du MCU, routable, adjacence serrée → Phase 6 RL_PCB ») a été
  levée via `tools/placement_bypass.py::snap_cluster_members` (étape ⑤ du placement).
- **Mesure l'appuyant :** 8 règles violées sur 9 avant, 0 après ; écart libre moyen
  7,2 → 4,7 mm (`examples/stm32-validation/output/2_placement`).
- **Ce que l'utilisateur doit arbitrer :** garder le snap bypass (et ratifier la levée),
  ou le retirer et restaurer la décision 2026-06-18.
- **Code concerné :** `services/kicad/tools/placement_bypass.py`, appel dans
  `tools/placement.py::auto_place`, gardes `tests/test_placement_bypass_snap.py`,
  `tests/test_snap_apres_geometre.py`.

### D-2026-09-03-b — Dimensionnement : 4 workers pour une machine qui tient un seul routage
- **Le fait mesuré :** un routage monte à **6,2 Go de mémoire résidente**
  (`stm32-baseline`, le plus petit board du banc). Deux en parallèle dépassent
  les 7,6 Go de la machine et le noyau tue le processus
  (`Out of memory: Killed process ... anon-rss:6247616kB`, crête 7,2 Go).
- **La contradiction :** `docker-entrypoint.sh` lance `uvicorn --workers 4`.
  Quatre workers annoncent quatre requêtes simultanées ; la mémoire n'en
  autorise qu'une. Le service accepte donc des requêtes qu'il ne peut pas
  honorer, et le symptôme (`Child process died`) ne désigne pas sa cause.
- **Ce que l'utilisateur doit arbitrer**, entre autres voies :
  1. ramener le service à 1 worker et sérialiser les routages en amont (la file
     BullMQ le fait déjà, `worker` en concurrence 1) ;
  2. garder 4 workers mais poser un sémaphore sur `/route/auto`, pour refuser
     ou faire attendre plutôt que mourir ;
  3. donner plus de mémoire à la machine et mesurer le vrai plafond.
- **Pourquoi ce n'est pas un correctif technique :** chacune de ces voies
  change le débit annoncé du service et le comportement vu par l'utilisateur
  (attente contre refus), donc la promesse produit.
- **Code concerné :** `services/kicad/docker-entrypoint.sh`,
  `services/kicad/routers/routing.py`.

### D-2026-09-03-a — Seed de placement (rejouabilité du GA)
- **Ce qui était prévu (handoff `2026-08-28-placement-seed-snap`) :** semer `random`
  depuis les octets du board et forcer `EvolutionaryConfig.parallel=False`, pour que
  « même board ⇒ même suite de tirages » (`seed + essai` par tirage).
- **Pourquoi ce n'est pas implémenté :** le GA séquentiel est plus lent que le
  ProcessPool, et un placement rejouable change la stratégie livrée (les re-tirages
  pilotés par le DRC reposent aujourd'hui sur le hasard non semé). Coût de placement
  contre reproductibilité des bancs : choix produit.
- **Ce que l'utilisateur doit arbitrer :** implémenter le seed (au prix d'un placement
  plus lent), ou renoncer et garder le placement non semé.
- **Trace :** le test RED `tests/test_placement_seed.py` a été retiré le 2026-09-03 ;
  `tools/placement_seed.py` n'a jamais existé.

### D-2026-08-21-a — kicad-tools devant Freerouting dans la cascade
- **Ce qui a été décidé sans validation :** « Décision produit du 2026-08-21 » —
  kicad-tools reste le Niveau 1 car seul chemin d'escalade de couches (plans Pro 4/8),
  malgré 58 erreurs de fabricabilité et ~10 min contre 4-5 s / 0 connexion manquante
  pour Freerouting.
- **Ce que l'utilisateur doit arbitrer :** confirmer l'ordre, ou router Freerouting
  d'abord sur les cartes 2 couches et n'appeler kicad-tools qu'à l'escalade.

### D-2026-08-29-b — Seuils chiffrés du routage
- `_SEUIL_REDRAW_PCT = 80` (ne pas re-tirer un palier hors d'atteinte)
- `_CAPACITE_ECHAPPEMENT = 3.0` (plancher de couches déduit du board)
- `_TIRAGES_ROUTAGE_PAR_PALIER = 3`
- Calibrés sur les 7 boards du banc, mais les VALEURS sont des choix produit
  (coût de fabrication vs taux de réussite).

### D-2026-08-11-a — `canView3D` appliqué côté client seulement
- Documenté comme « assumé » sans trace d'arbitrage utilisateur. Différenciateur
  produit : à ratifier ou rendre exécutoire côté serveur (export STEP/GLB).

### D-2026-08-11-b — Mode démo simulation en opt-in (`CIRQIX_SIMULATION_DEMO=1`)
- Choix d'UX/produit : aucune donnée de secours sur erreur, démo locale uniquement.

---

## Validées par l'utilisateur

### D-2026-09-05-a — La retenue de crédit suit le travail réel (fenêtre glissante)
**Tranchée le 2026-09-05 : l'utilisateur a validé cette action précise** (« ok »
sur la recommandation « aligner la retenue de crédits sur la durée réelle »).

- **Le défaut :** `PIPELINE_RESERVATION_TTL_S` valait 360 s, calibré sur la
  route SYNCHRONE plafonnée à 300 s. Le pipeline ASYNCHRONE dure **19 minutes
  mesurées** (run `4290007c`). Passé la sixième, la retenue expirait sous un job
  qui tournait : `available_credits` cessait de la compter, un second projet
  pouvait démarrer sur le même solde, et les deux consommaient Sonnet et le
  service KiCad sans engagement — exactement la fenêtre que la migration `015`
  avait fermée. Le drapeau `CIRQIX_ASYNC_PIPELINE` étant allumé, elle était
  ACTIVE. Relevé par Grok en consultation, vérifié ligne à ligne.
- **Ce que ce n'est pas :** un vol de crédits. La contrainte
  `credits_balance_nonnegative` interdit un solde négatif ; le prix est de la
  ressource brûlée et un second run qui échoue à la facturation après vingt
  minutes de travail.
- **Ce qui est retenu :** la retenue devient une **fenêtre glissante**. Chaque
  battement de cœur du run (30 s) repousse son échéance de 600 s
  (`extend_pipeline_reservation`, migration `021`). Un run vivant garde son
  crédit engagé aussi longtemps qu'il travaille ; un run mort cesse d'être
  rafraîchi et sa retenue expire d'elle-même.
- **Pourquoi pas une simple valeur plus grande**, ce qui était mon premier
  correctif : `reserve_pipeline_credits` refuse au-delà de 3600 s, et surtout
  rien ne libérait la retenue d'un run ÉCHOUÉ — un seul échec aurait gelé le
  solde une heure. La revue de sécurité l'a relevé. La libération à la clôture
  est livrée dans le même lot (`services/worker/src/reservations.ts`).
- ⚠️ **Découverte au passage :** `pcb_runs.heartbeat_at` était écrit toutes les
  30 s depuis la migration `019`, index compris, et **aucun code ne le lisait**.
  Les commentaires de `run-job.ts` et `run-repository.ts` annonçaient un
  réconciliateur des runs muets qui **n'a jamais été écrit**. C'est son premier
  usage réel.
- ⚠️ **La migration `021` n'est PAS appliquée.** Le code est fail-safe : sans
  elle, la prolongation échoue en silence et le comportement retombe sur
  l'échéance fixe (3600 s), qui couvre déjà les 19 minutes mesurées. À appliquer
  pour obtenir la fenêtre glissante.
- **Code :** `apps/web/src/app/api/agent/lib/credits.ts`,
  `services/worker/src/reservations.ts`, `services/worker/src/adapters.ts`,
  `packages/db/supabase/migrations/021_extend_pipeline_reservation.sql`.
  Gardes : `apps/web/src/test/credits-reservation.test.ts`,
  `services/worker/src/tests/liberation-reservation.test.ts`.


### D-2026-08-29-v1 — Séquence intérieure d'un palier de routage
Plan de masse coulé ET rempli avant routage (mesuré : 68-71 % → 94 % sur Nucleo),
vias d'échappement réservés, signaux routés, vias replacés, plans re-coulés,
couture répétée. *« demandée par l'utilisateur »* — CLAUDE.md.

### D-2026-08-29-v2 — Escalade des couches en gardant toujours le meilleur
Tirages multiples par palier (Freerouting stochastique), classement
(pourcentage, erreurs DRC), jamais le dernier. *« demandée par l'utilisateur »*.

---

## Annulées (trace conservée)

### D-2026-09-02-a — ⚠️ RETIRÉE : le diagnostic qui la fondait était FAUX

- **Statut : SANS OBJET. Aucune décision produit n'était nécessaire.**
- **Ce que j'avais écrit**, le 2026-09-02 au matin : le plafond POWER (3 mm) et
  la marge du halo d'escape (5 mm) seraient contradictoires, « le snap cherche
  un point à la fois à moins de 3 et à plus de 5 mm du corps de l'ancre,
  impossible par construction ». J'en concluais qu'il fallait trancher entre
  trois voies, toutes touchant à la stratégie de placement.

- **C'était faux.** Le plafond ne décide que s'il faut **ESSAYER** :

  ```python
  if dist - portee <= cluster.max_distance_mm:
      continue          # déjà assez près : on ne tente rien
  ```

  Le déplacement, lui, est accepté dès qu'il **AMÉLIORE** l'écart libre. Un
  point à 5 mm remplaçait donc parfaitement un point à 58 mm. Les deux règles
  ne se contredisaient pas — je les avais lues comme une conjonction alors
  qu'elles agissent à deux moments différents.

- **La vraie cause était banale, et purement technique** : la fenêtre de
  recherche.

  ```
  _ESSAIS_RADIAUX = 4  ·  _PAS_RADIAL_MM = 1,5   ->  4,5 mm au-delà de la marge
  ```

  Sur une ancre dense (marge 5 mm), `_cible_libre` n'explorait que l'anneau
  d'écart libre **5,0 à 9,5 mm** — précisément celui qu'occupent les
  résistances de `nucleo-f401` (13,7 mm d'entraxe, ~6,2 mm d'écart libre au
  corps du LQFP-64). L'anneau était plein, la recherche rendait `None`, le snap
  renonçait pour les huit condensateurs.

- **Corrigé sans aucun seuil choisi** (commit `f037d29`). La portée est
  **déduite** de l'écart où le membre se trouve déjà : au-delà, la garde « ne
  peut qu'améliorer » refuserait le point de toute façon. Un second défaut,
  **latent**, a été réveillé au passage — le contour de la carte n'était pas
  un obstacle, et `D26` s'est retrouvé à 0,4474 mm du bord pour 0,5 exigés. Il
  est traité, nativement, par `extract_board_outline`.

- **Mesure sur le chemin réel**, `nucleo-f401`, depuis la grille du générateur :

  ```
  grille              médiane  90,4 mm   max 129,0 mm
  placement corrigé   médiane  14,4 mm   max  15,3 mm   0 erreur DRC
  ancien board        médiane  58,5 mm   max  68,7 mm
  ```

- ⚠️ **La leçon, et elle est déjà écrite ailleurs dans ce dépôt** : j'ai
  transformé une limite technique en décision produit, et j'ai bloqué le
  travail plusieurs échanges durant en attendant un arbitrage qui n'avait pas
  lieu d'être. **NEVER** ériger un défaut non diagnostiqué en dilemme à
  arbitrer : chercher la cause d'abord, et ne remonter une décision que
  lorsqu'il reste un vrai choix.


### D-2026-08-28-x — Budget GA divisé par 3 (commit 2744899)
Réduire `generations/population/iterations` du GA pour la vitesse. **Reverté**
au commit c312c07 : le budget réduit livrait une carte NON fabricable
(filtre anti-aberration en contrepartie insuffisant). État final = budget d'origine.

### D-2026-06-18-a — Limite « 13-28 mm » ACCEPTÉE
Limitation de `detect_functional_clusters` acceptée faute de levier. **Levée sans
validation** le 2026-08-29 → voir D-2026-08-29-a ci-dessus (à ratifier ou non).

## D-2026-09-07-a — Arreter Freerouting sur absence de progression

**Statut : en attente de validation.**

**Constat mesure.** Comptage sur le journal du service KiCad, cinq travaux
Freerouting distincts :

    996 passes  score 815.45  (40 non routes)
    996 passes  score 701.71  (50 non routes)
    996 passes  score 685.09  (42 non routes)
    996 passes  score 650.03  (43 non routes)
    992 passes  score 770.97  (34 non routes)

Le score ET le nombre de connexions manquantes sont identiques sur toute la
serie. Ces travaux n'ont rien ameliore apres leurs premieres passes et ont
consomme environ 1,2 s par passe jusqu'au plafond de mille, soit ~20 minutes
chacun. Avec `_TIRAGES_ROUTAGE_PAR_PALIER = 3`, un palier peut donc bruler une
heure sans produire un seul segment de plus.

**Proposition.** Arreter un travail apres N passes consecutives sans
amelioration du score, au lieu d'attendre le plafond de passes.

**Pourquoi ce n'est PAS applique.** C'est un seuil chiffre qui change le
comportement livre — categorie qui exige une validation explicite selon
`CLAUDE.md`. Une carte difficile peut rester longtemps sur un palier avant de
debloquer : couper trop tot rendrait des cartes moins bien routees, et ce depot
a deja paye ce genre d'arbitrage (« NEVER partager le budget entre les
essais », qui avait mis tous les paliers a 0 %).

**Ce qui manque pour trancher.** Une mesure de la duree typique d'un plateau qui
finit par ceder, sur plusieurs tirages — exactement la prudence deja inscrite :
deux tirages concordants ne prouvent rien.

**Une mesure etaye une proposition ; elle ne la valide pas.**

---

## D-2026-09-08-a — Pas de grille du placement (`_GRILLE_MM = 0.5`)

**Statut : en attente.**

**Constat mesure.** Aucune carte livree n'a ses composants sur une grille :

    carte-04    1 / 15        nucleo-f401    0 / 55
    carte-07    2 / 44        stm32-100      1 / 100
    carte-10    2 / 70

Les orientations, elles, sont toutes cardinales (55/55 sur `nucleo-f401`). Ce
sont les POSITIONS qui tombent au centieme de millimetre, la ou le GA les a
laissees. C'est la signature visuelle que l'utilisateur designe le 2026-09-08 :
« le placement, c'est un placement d'amateur ».

**Le levier est natif et n'etait pas passe.** `WorkflowConfig.grid`
(`optim/workflow.py:187`, defaut `0.0` = aucun snap) declenche
`optimizer.snap_to_grid(grid, 90.0)` (ligne 348).

⚠️ Le transmettre ne suffit PAS : le natif aligne en fin d'optimisation, puis le
Geometre, le halo, le snap et l'Inspecteur deplacent tout. Mesure avec
`grid=0.5` bien transmis : **2/62 avant, 2/62 apres**. L'alignement doit etre
repose EN DERNIER (`aligner_sur_grille`).

**Mesure du remede**, board place reel de `carte-09` :

    grille 0,5 mm    2 / 62  ->  62 / 62
    erreurs DRC      0       ->  0

**Proposition.** `_GRILLE_MM = 0.5` — pas usuel d'un placement manuel en CMS.
Une valeur nulle desactive le snap et rend le comportement d'avant.

**Pourquoi ce n'est PAS acquis.** Seuil chiffre qui change le comportement
livre. La mesure ci-dessus etaye la proposition ; elle ne la valide pas.

---

## D-2026-09-08-b — Rayon d'adjacence d'une paire en serie (`_RAYON_PAIRE_MM = 5.0`)

**Statut : en attente.**

**Constat mesure.** Une LED et sa resistance serie partagent un net qui ne
touche qu'ELLES DEUX — la paire la plus serrable qui existe sur une carte :

    carte-09   D12 ↔ R13   100,9 mm      carte-08   D14 ↔ R15   76,7 mm
    carte-10   D9  ↔ R10    86,8 mm      carte-07   D2  ↔ R3    40,8 mm

Moyenne par carte : 3 mm a 5 composants, **55 mm a 62**. La dispersion suit la
taille de la carte.

**Proposition.** Contraindre ces paires a 5 mm entre origines — ce qu'un
ingenieur fait a la main, en laissant au routeur de quoi passer entre les deux.

⚠️ Ce n'est PAS une distance de courtyard : `max_distance` se mesure entre
positions, le snap dur entre CORPS. Confondre les deux est une erreur deja
commise dans ce depot.

**Effet mesure des contraintes natives seules** (avant serrage dur) :

    paires   moyenne 55,3 -> 35,7 mm      max 100,9 -> 62,7 mm

**Pourquoi ce n'est PAS acquis.** Seuil chiffre qui change le comportement
livre.

---

## D-2026-09-08-c — Abandonner les attaches PROUVABLEMENT insatisfiables

**Statut : en attente.** ⚠️ C'est la decision la plus lourde des trois : elle
touche la STRATEGIE de placement, pas un reglage.

**Constat mesure.** `detect_functional_clusters` attache un meme composant a
PLUSIEURS ancres, et ces ancres sont incompatibles entre elles :

    carte-07   15 composants a plusieurs ancres — les 15 insatisfiables
    carte-09   19 sur 19        carte-10   19 sur 19        carte-04   3 sur 3

    D10 (carte-09) appartient a SEPT clusters : J1, J10..J14 et U1
    D6  tenu par J7 et J1, distants de 123 mm pour 16 mm de plafonds cumules

Aucune position ne satisfait « a 8 mm de J1 » ET « a 8 mm de J7 » quand les deux
sont a 123 mm l'un de l'autre.

**Consequence : le gel complet.** La garde « ne peut qu'ameliorer » refuse tout
mouvement, puisque se rapprocher d'une ancre eloigne d'une autre. Elle fait
exactement son travail — et le resultat est que RIEN ne bouge :

    snap R10 -> D10 : eloignerait une autre ancre, ignore
    snap R11 -> D11 : eloignerait une autre ancre, ignore   ← les 16, sans exception

C'est l'explication de fond du reproche « placement d'amateur » : le serrage ne
manque pas, il est systematiquement refuse par des contraintes qu'aucune
position ne peut honorer.

⚠️ Corriger le choix d'ancre ne suffit pas — essaye et mesure le 2026-09-08 :
35,7 -> 32,5 mm seulement, parce que la contradiction demeure des deux cotes.

**Proposition.** Quand les ancres d'un composant sont plus eloignees entre elles
que la somme de leurs plafonds, l'ensemble est PROUVABLEMENT insatisfiable : ne
garder que l'attache la plus proche, et journaliser explicitement les abandons.

**Pourquoi ce n'est PAS applique.** Decision de strategie de placement, la
categorie qui exige une validation explicite. Et le risque est reel :
abandonner une attache peut degrader une adjacence que le routage utilisait.

**Une mesure etaye une proposition ; elle ne la valide pas.**

### D-2026-09-08-c — MESURE DU 2026-09-09 : la proposition est RÉFUTÉE

Statut : **retirée**. Le drapeau reste en place, désarmé
(`CIRQIX_ABANDON_ATTACHES_IMPOSSIBLES`), pour que la mesure soit rejouable.

Deux bras sur les onze boards livrés, snap seul, sans router :

| carte | garde actuelle | avec abandon |
|---|---|---|
| carte-02 | 10,2 → **10,2** mm | 10,2 → **4,8** mm |
| carte-05 | 10,4 → 4,8 | 10,4 → 4,8 |
| carte-06 | 17,5 → 14,2 | 17,5 → 13,7 |
| carte-07 | 15,7 → **15,1** | 15,7 → **15,9** ← pire |
| carte-08 | 39,2 → 29,6 | 39,2 → **23,9** |
| carte-09 | 55,3 → 42,6 | 55,3 → 42,8 ← pire |
| carte-10 | 49,5 → **32,7** | 49,5 → **35,8** ← pire |
| **moyenne** | **17,7 mm** | **16,9 mm** |

**0,8 mm de gain moyen, et trois cartes sur sept DÉGRADÉES**, pour 10 à 30 %
de composants déplacés en plus. Ce n'est pas un compromis acceptable : on
paierait un risque réel de routage pour un gain dans le bruit.

⚠️ **MA PRÉMISSE ÉTAIT FAUSSE.** J'avais lu « les seize paires refusées, sans
exception » et conclu que la garde gelait tout. Elle ne gèle pas : sur les mêmes
boards, la garde actuelle déplace déjà 19 à 36 composants et ramène `carte-09`
de 55,3 à 42,6 mm. Ce que j'avais observé était le refus des paires *LED-
résistance en particulier*, sur un board intermédiaire — pas un gel général.

**Généraliser depuis un journal de mise au point est exactement ce que ce dépôt
s'interdit** (« NEVER relayer le message d'une garde comme un diagnostic »).
J'ai bâti une décision produit sur une lecture partielle, et c'est la mesure qui
l'a arrêtée.

**Ce que la mesure désigne à la place.** L'écart à la référence humaine
(9,8 mm) ne se joue pas dans le snap de fin de chaîne : celui-ci fait déjà le
plus gros du travail. Il se joue **en amont**, dans la dispersion du GA — que
les contraintes natives réduisent déjà de 55,3 à 35,7 mm. Le levier suivant est
donc `optim/bottom_up_placement.py`, la méthode non génétique jamais appelée.

---

## D-2026-09-09-a — Placement hiérarchique en amont du snap, sur les grandes cartes

**Statut : en attente.** ⚠️ Stratégie de placement — catégorie qui exige une
validation explicite.

**Constat.** `optim/bottom_up_placement.py` est une méthode **non génétique**,
présente dans `kicad-tools` et **jamais appelée**. Elle groupe par motif
fonctionnel, dispose *dans* chaque groupe, puis pose les groupes comme des
blocs — la méthode d'un ingénieur. Son en-tête cite l'hypothèse d'origine :
« 80 % du chemin rien qu'en procédant du bas vers le haut ».

**Mesure du 2026-09-09**, distance moyenne des paires en série, placement seul,
sans router :

| carte | livré | hiérarchique seul | hiérarchique + notre snap |
|---|---|---|---|
| carte-01 | **3,0** | 10,2 | 3,5 |
| carte-03 | **7,1** | 14,0 | 10,4 |
| carte-05 | **10,4** | 34,3 | 13,9 |
| carte-07 | **15,7** | 38,8 | 22,5 |
| carte-08 | 39,2 | 35,8 | **24,3** (−38 %) |
| carte-09 | 55,3 | 34,5 | **26,0** (−53 %) |
| carte-10 | 49,5 | 39,0 | **32,1** (−35 %) |
| **moyenne** | 23,1 | 26,7 | **18,1** |

**La coupure est nette et elle est de TAILLE.** Notre GA gagne jusqu'à une
trentaine de composants ; le hiérarchique gagne au-delà. C'est exactement la loi
mesurée la veille — notre qualité se dégrade avec la taille, celle de la
référence humaine non.

⚠️ **Le hiérarchique SEUL est le pire des trois** (26,7 mm). Ce n'est pas un
remplaçant du snap, c'est une meilleure GRAINE. Les deux mesures séparées
auraient conduit à l'écarter.

**Proposition.** Sur les cartes au-delà d'un seuil de composants, remplacer la
graine du GA par `place_hierarchical_from_pcb`, puis dérouler la chaîne
existante inchangée (Géomètre, halo, snap, grille, Inspecteur).

**Pourquoi ce n'est PAS appliqué.**
1. Stratégie de placement — validation explicite requise.
2. Le seuil de bascule est un seuil chiffré.
3. ⚠️ **La mesure porte sur le PLACEMENT, jamais sur le routage.** Un placement
   plus serré peut router MOINS bien : `carte-08`, `09` et `10` routent
   aujourd'hui à 100 %, et c'est ce qu'on risquerait. Aucune campagne de routage
   n'a été faite — elle coûte plusieurs heures sur cette machine.

**Une mesure étaye une proposition ; elle ne la valide pas.**

---

## D-2026-09-10-a — Borner la memoire de la JVM Freerouting (`-Xmx`)

**Statut : en attente.**

**Constat mesure**, journal du service, `carte-08` :

    pass #85  score 964.42  (8 non routes)  6201 CPU s  55668 MB memoire
    pass #86  score 964.42  (8 non routes)              55879 MB
    pass #87  score 964.42  (8 non routes)              56223 MB
    INFO: Child process [103] died

**La JVM annonce 55 Go sur une machine qui en a 7,6.** Le worker uvicorn meurt
juste apres. Ligne de commande actuelle, sans aucun plafond :

    java -jar /opt/freerouting/freerouting.jar --api_server.enabled=true ...

⚠️ **CE N EST PAS UNE PENURIE DE MEMOIRE SYSTEME**, et je l ai cru toute la
journee. Le cgroup du conteneur dit `oom_kill = 0`, crete a 3,4 Go sur 7,6
disponibles — le noyau n a tue personne. J ai arrete Supabase, surveille
`free -m`, relance six fois : je traitais un symptome que la mesure dementait.
Le message « stopped because the system is running low on memory » venait de
l outil qui tuait mes processus WINDOWS, pas du conteneur.

**Proposition.** Poser `-Xmx` au demarrage de la JVM, a une valeur compatible
avec la machine (2 a 3 Go), pour qu un travail trop gourmand echoue proprement
au lieu d emporter le worker.

**Pourquoi ce n est PAS applique.** Seuil chiffre qui change le comportement
livre, et le risque est reel dans l autre sens : une JVM trop bornee refusera de
router une carte que la machine pourrait traiter. Il faut mesurer la
consommation reelle d un routage qui ABOUTIT avant de choisir la valeur.

**Lie a `D-2026-09-XX` (couper sur stagnation).** Les deux faces du meme
constat : 87 passes pour ZERO gain de score. Un travail qui n ameliore plus rien
consomme du CPU et de la memoire jusqu a tuer son hote.

---

## D-2026-09-10-b — Escalade de couches INCREMENTALE

**Statut : en attente.** Souleve par l utilisateur le 2026-09-10.

**Son argument, et il est juste :** ajouter des couches ne peut que donner PLUS
de ressources. On devrait garder les pistes des 2 couches et ne router que ce
qui manque sur les nouvelles. Le resultat serait alors MONOTONE — jamais pire.

**Ce que le code fait aujourd hui :**

    etendu = _expand_stackup(pcb_bytes, palier)

`pcb_bytes` est le board PLACE, NON ROUTE. Chaque palier repart donc de zero :
le routage a 4 couches ne conserve rien de celui a 2. Il refait tout, avec plus
de place mais un autre tirage — donc il peut faire MOINS BIEN. Mesure du depot :
`stm32-100`, 2 couches 99 %, puis 4 couches **87 %**.

On garde le MEILLEUR palier, donc on ne livre jamais moins bon. Mais on ne
CUMULE pas, et c est exactement l ecart que l utilisateur pointe.

⚠️ **La piste a ete essayee et fermee** : `--preserve-existing` de Freerouting
perdait la moitie du cuivre recu, et l escalade incrementale rendait le meme
resultat que l escalade libre pour trois fois le temps.

⚠️ **Mais cette mesure est ANTERIEURE** aux correctifs du round-trip Specctra et
aux pieges de forme corriges depuis. Elle merite d etre refaite avant d etre
opposee a l argument.

**Une mesure etaye une proposition ; une mesure perimee n en refute aucune.**

### D-2026-09-10-a — RECTIFICATION : le chiffre de 55 Go ne mesurait pas la memoire

**Statut : retiree.** La proposition reposait sur une lecture fausse.

Le journal Freerouting annonce « 55668 MB memory », puis 133 Go, 307 Go, et
jusqu a **3 To** sur la nuit. Mesure du RSS reel, au meme moment :

    java       1 426 712 ko  =  1,4 Go
    conteneur              2,8 Go / 7,6

⚠️ **C EST UN COMPTEUR CUMULE, PAS UNE OCCUPATION.** Une JVM ne detient pas
3 To sur une machine de 7,6 Go — l invraisemblance du chiffre aurait du
m arreter avant que j en fasse une decision produit.

C est la faute deja inscrite pour les gardes : **relayer un nombre sans verifier
ce qu il compte**. Et c est la seconde fois de la journee sur le meme sujet,
apres le message « stopped because the system is running low on memory » qui
venait de l outil tuant mes processus WINDOWS, alors que le cgroup du conteneur
disait `oom_kill = 0`.

**La cause des `RemoteDisconnected` reste donc INCONNUE.** Ce qui est etabli :

    le cgroup du conteneur         oom_kill = 0, crete 3,4 Go sur 7,6
    la JVM                          1,4 Go reels
    le routeur, lui, STAGNE         87 passes puis 242 passes sans gain de score

La stagnation est mesuree et reelle ; l explication par la memoire ne l est pas.
Piste a explorer a froid : l assertion `wxWidgets PROPERTY_ENUM` visible dans
les journaux, qui est un plantage NATIF de `pcbnew` — celui pour lequel
`PYTHONFAULTHANDLER` a ete active.

**Ne pas borner `-Xmx` sur la foi de ce chiffre.**

---

## Diagnostic du 2026-09-10, RECTIFIE le jour meme — la cause PROUVEE des `RemoteDisconnected`

⚠️ La section qui suit celle-ci (« la cause reelle », pcbnew) est **FAUSSE**,
troisieme diagnostic errone sur le meme symptome. Elle est conservee telle
quelle : elle montre la faute — lire deux lignes voisines d un journal comme
une cause et son effet, sans regarder leur ORDRE. Les asserts `PROPERTY_ENUM`
sont imprimes 3 a 5 s **APRES** « Child process died », par le worker SUIVANT
qui importe `pcbnew` au demarrage. Ils suivent la mort, ils ne la causent pas.

**La cause, mesuree par une sonde et non lue dans un message :**

    uvicorn 0.30.0, supervisors/multiprocess.py
      :37   def ping(self, timeout: float = 5)
      :170  process.kill()   # process is hung, kill it
      :176  logger.info(f"Child process [{process.pid}] died")

Le superviseur envoie un ping a chaque worker ; sans reponse en **5 s**, il
l abat par SIGKILL — donc sans trace, `PYTHONFAULTHANDLER` compris. Le worker
ne repond pas quand un appel C tient le GIL. Sonde
(`faulthandler.dump_traceback_later` depuis un thread C, sans GIL) sur
`carte-05`, 26 composants, appel direct de `route_auto` :

    famines du thread de ping : 9,1 s · 6,0 s · 3,0 s · 3,0 s · 2,6 s
    pile a cet instant        : <frozen codecs>.decode <- read_text
                                <- routers/routing.py:850 _route_with_freerouting_api

La boucle de sondage relisait le journal Freerouting ENTIER, deux fois par
tour. Ce journal grossit toute la vie de la JVM : **564 Mo** ce jour-la. Le
decodage UTF-8 tient le GIL 6 a 9 s. Le worker mourait 2 s apres la fin du
routage — a la reprise de la sonde — et la carte n avait rien de dense :
`carte-05` a perdu 3 essais sur 4 dans la campagne du matin.

Pourquoi « seulement les cartes denses » : elles ecrivent plus de lignes ;
le journal franchit plus vite la taille qui depasse 5 s. Le symptome
suivait la TAILLE DU JOURNAL, pas la carte — d ou trois diagnostics faux
(memoire, JVM, pcbnew), tous plausibles, aucun mesure.

**Correctif** (`tools/journal_freerouting.py`, `LecteurIncremental`) : le
journal est lu par increments depuis le depart du job, jamais relu. Mesure
apres correctif, meme carte, meme sonde : **0 famine**, et le routage passe de
165 s a 77 s — les relectures mangeaient aussi la moitie du temps.
Gardes : `tests/test_journal_lu_par_increments.py` (comportement + cablage).

**Trois lecons, toutes deja inscrites ailleurs et payees une fois de plus :**
ne jamais relayer un message comme un diagnostic ; verifier l ORDRE de deux
evenements avant d en faire une causalite ; **mesurer avec un instrument**
(ici la sonde) avant de proposer un correctif — la piste « isoler pcbnew dans
un enfant » etait deja en place depuis des semaines et n aurait rien change.

---

## Diagnostic du 2026-09-10 — « la cause reelle », REFUTE : ce n etait pas pcbnew

**Ce n est PAS la memoire.** Je l ai cru toute la journee et j ai agi dessus :
arret de Supabase, surveillance de `free -m`, recreation du conteneur, six
campagnes relancees. Deux mesures le dementent :

    cgroup du conteneur    oom_kill = 0, crete 3,4 Go sur 7,6
    RSS reel de la JVM     1,4 Go  (le journal Freerouting annonce 495 Go —
                                    c est un compteur CUMULE, pas une occupation)

**La vraie cause**, visible en lisant ce qui PRECEDE la mort, trois fois a
l identique :

    Restoring an earlier board that has the score of 964.42 (8 unrouted)
    INFO:     Waiting for child process [103]
    INFO:     Child process [103] died

Le worker meurt **apres** que le routage a rendu son resultat, pendant le
POST-TRAITEMENT — replacement des vias, coulee des plans, fanout, couture des
ilots. Toutes ces etapes passent par `pcbnew`. Et le conteneur journalise
**neuf assertions natives en quarante minutes** :

    property.h(607): assert "m_choices.GetCount() > 0" failed in PROPERTY_ENUM()

C est le plantage que ce depot documente deja, celui pour lequel
`PYTHONFAULTHANDLER` avait ete active — et qui n ecrit aucune trace, le signal
n etant pas detournable.

⚠️ **POURQUOI SEULEMENT LES CARTES DENSES.** Plus de zones, de vias et d ilots
a post-traiter, donc plus d occasions de declencher l assertion. `carte-01` a
`carte-07` passent ; `carte-08`, `09` et `10` echouent trois fois sur trois.

**Consequence pour le banc :** ces trois cartes ne peuvent pas aboutir tant que
ce plantage n est pas contourne. Ce n est ni le placement, ni le nombre de
couches, ni le nombre de tirages.

**Piste, non appliquee :** isoler le post-traitement `pcbnew` dans un processus
ENFANT, comme `cmaes_runner.py` et `drc_pcbnew_runner.py` le font deja. Un
plantage natif tuerait alors l enfant, pas le worker — et la requete rendrait
une erreur au lieu de couper la connexion. Le depot documente deja cette regle :
« toute nouvelle route appelant `pcbnew` doit suivre ce schema ».

⚠️ **DEUX FAUSSES PISTES SUIVIES AVANT CELLE-CI**, toutes deux par relais d un
message sans verification : « low on memory » venait de l outil tuant mes
processus WINDOWS, et « 495299 MB memory » d un compteur cumule. **Verifier ce
qu un nombre COMPTE avant d en tirer une decision.**

---

## D-2026-09-10-e — un job Freerouting abandonné est un job TUÉ (JVM relancée)

**Statut : validée sous délégation** (levier de temps, l'utilisateur demandait
pourquoi carte-08 prenait des heures).

`cancel` répond 501 : un job que l'on cesse d'attendre continue jusqu'à sa
passe 999. Journal Freerouting du 2026-09-10, 19:51-19:58 : **huit jobs
abandonnés lancés à une minute d'intervalle, 999 passes chacun, tous vivants
en même temps dans la JVM** — chaque nouveau job partageait la JVM avec eux.
A/B esp32-baseline sur le même placement : 100 % en 61 s quand la JVM est
seule, contre trois tirages figés à 63-86 % puis escalade à 6 couches pendant
la campagne. Le halo des capas, soupçonné, est hors de cause (contrôle 23 s,
A 61 s, B 237 s — tous 100 % sur 2 couches).

Règle : `_tuer_la_jvm()` à chaque abandon (`pkill -f freerouting.jar`, attente
de `/system/status`) ; l'entrypoint relance la JVM en boucle, journal vidé.
Perte assumée : la récupération d'un job abandonné (`_recuperer_jobs_abandonnes`)
ne trouve plus rien — elle rendait des boards à 31-69 %, jamais livrables.
Réglage `tuer_jvm_sur_abandon`. Gardes : `tests/test_job_abandonne_est_tue.py`.

**Repli GND borné** (même jour) : il ne se paie que si ≤ 8 connexions manquent
(`_REPLI_GND_MAX_MANQUANTES`, réglage `repli_gnd_max_manquantes`). carte-08 :
17 min pour passer de 36 à 33 manquantes, 11 min pour un repli refusé.
Gardes : `tests/test_repli_gnd_borne.py`.

## D-2026-09-10-d — un placement CONDAMNÉ n'est pas routé jusqu'au bout

**Statut : validée** (utilisateur : « go » sur le levier « ne pas router un
placement condamné », 2026-09-10). Le seuil chiffré est le mien.

Mesure sur `carte-05`, essai 1 du pipeline : tirages figés à 62 / 23 / 0 %,
puis « dernière chance » (10 min) et repli GND (8 min) — **21 min pour un
board à 0 %**. L'essai suivant, autre placement, a routé à **100 % en 30 s**.
Vingt minutes de routage ne rachètent pas un placement inroutable ; trois
minutes de re-placement, si.

Règle (`_placement_condamne`, `_CONDAMNE_PCT = 50`) : quand TOUS les tirages
d'un appel ont figé et que le meilleur reste sous 50 %, `route_auto` rend la
main sans dernière chance ni repli GND. Au-dessus, rien ne change — la
dernière chance a sauvé `nucleo-f401` (tirages figés à 43-79 %). Réglage
`condamne_pct` pour l'A/B. Gardes : `tests/test_placement_condamne.py`.

## Superviseur uvicorn tolérant (même jour, technique)

Second worker abattu à 15:28, sonde armée : pile dans un parseur pur Python
de 0,15 s. Pas de GIL tenu, pas de throttling CPU (12 cœurs, charge 2,4) —
**la VM WSL paginait** (234 Mo en swap, 570 000 pages écrites, pression
mémoire `full` 5,8 h cumulées ; Supabase seul pèse 1,7 Go). `lancer_service.py`
porte la tolérance du ping de 5 s (codée en dur dans uvicorn 0.30) à 30 s ;
Supabase est arrêté pendant les campagnes. Gardes :
`tests/test_superviseur_tolerant.py`.

---

## D-2026-09-10-c — GND revient au PLAN par défaut (prise sous délégation)

**Statut : validée sous la délégation de validation** confiée par l'utilisateur
(« c'est toi qui valides avec la dernière recherche »). Elle RETIRE la mise en
œuvre du matin « GND routé en pistes comme la référence STM32 d'Astra », qui
n'avait jamais été mesurée sur le même board.

A/B sur le MÊME board placé (`carte-05`, 26 composants, 2 couches), appel
direct de `route_auto`, deux tirages par bras :

    GND en pistes    92 %   92 %    154 s · 119 s   vias 34 · 19
    GND au plan     100 %  100 %     31 s ·  27 s   vias 38 · 40

Même différence dans la campagne du matin : `carte-05` livrée hier à 100 % en
41 s (plan) contre 92 % avec 8 erreurs DRC et un essai à 69 % aujourd'hui
(pistes). Sur deux couches, chaque piste de masse découpe le plan et occupe le
canal des signaux ; Astra route GND en pistes sur SIX couches avec deux plans
dédiés — ce n'est pas notre empilage.

Ce que dit la recherche (`docs/methodologie-routage.md`) : sur 2 couches, plan
de masse coulé sur la face libre, dogbones sur chaque pastille CMS de masse,
couture des îlots. C'est la séquence déjà en place. « GND en pistes » reste
disponible par réglage (`{"gnd_route": true}`) pour un futur A/B sur 4 ou 6
couches, où la mesure pourrait s'inverser.

Leçon : une décision validée SUR UNE RÉFÉRENCE n'est pas validée sur nos
cartes tant que l'A/B n'est pas fait sur le même board. Elle a coûté une
matinée de campagne.

---

## Délégation du 2026-09-10 — méthodologie de routage

L'utilisateur a fourni une synthèse des pratiques de l'industrie (Hartley,
Bogatin, Phil's Lab, Feranec, Peterson, IPC-2221/7351/4761) et a délégué :
« si tu as besoin de ces recommandations, c'est toi qui les valides ».

**Portée :** les choix de MÉTHODE de routage conformes à ces sources peuvent
être validés par l'assistant sans retour à l'utilisateur. Les seuils chiffrés
et les choix commerciaux (plafond de couches vendu, coût) restent siens.

**Validé au titre de cette délégation :**
- GND routé en pistes + plan coulé sur Bottom (2 couches) — déjà appliqué,
  confirmé par « grille de masse / ground pour ».

**À faire, validé d'avance :**
- Routage orthogonal H/V par couche (préférence de direction Freerouting).
- Ordre de routage par priorité (fanout → critiques → alimentation → GPIO) —
  plus lourd, à mesurer avant.

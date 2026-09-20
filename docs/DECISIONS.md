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
> ⚠️ **CETTE DÉCISION EST APPLIQUÉE EN PRODUCTION DEPUIS LE 2026-08-29**, alors
> qu'elle figure ici « en attente ». Le snap tourne à chaque placement
> (`tools/placement.py::auto_place`, étape ⑤) et a été fusionné dans `main`
> par la PR #143. Relevé par GLM en consultation le 2026-09-05.
>
> Ce n'est PAS une validation : seul l'utilisateur peut la donner. C'est le
> constat, écrit ici pour qu'un lecteur ne croie plus qu'il suffit de trancher
> AVANT d'implémenter — l'implémentation a précédé, contrairement à la règle
> d'autonomie bornée de `CLAUDE.md`. Arbitrer revient donc à **garder ou
> retirer** du code livré, pas à autoriser ou refuser un travail à venir.
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

### D-2026-09-20-a — Carte de départ dimensionnée sur les composants : 25 % d'occupation
**Statut : validée** par l'utilisateur le 2026-09-20 (« Oj »), après proposition chiffrée.
- **Constat (relecture du banc, 2026-09-19) :** les courtyards couvrent 5 % de carte-09
  (130 × 100 mm pour 62 composants), 4,7 % de carte-10. Le placement étale sur la surface
  reçue ; le resserrage final (D-2026-09-13-c A) ne rattrape rien — la surface de DÉPART est
  trop grande. Les connecteurs restent toujours en bordure (règle posée par l'utilisateur).
- **Règle :** quand la taille n'est pas imposée, la carte de départ vaut
  `somme des courtyards / 0,25`, aux proportions demandées ; les mobiles sont rapatriés par
  `place_unplaced`, les connecteurs ancrés sont ramenés dans le contour par le clamp.
  `tools/carte_compacte.py`, `OCCUPATION_DEFAUT = 0.25`, débrayable par le réglage de banc
  `occupation_cible`.
- **Mesure A/B (2026-09-19, dix cartes, témoin contre 0,25) :** surface −18 à −63 % sur les
  cinq cartes comparables, 0 erreur et 0 connexion manquante dans les deux bras ; carte-08
  entièrement connectée (58 × 44 mm, 4 couches, 1 erreur) là où le témoin laissait
  10 manquantes ; 03/07/09/10 sans board **dans les deux bras** (tirages figés, jetés —
  corrigé par le rejeu CLI `_board_partiel_par_cli`).
- **Pourquoi 25 % et pas plus :** aucune mesure au-delà. Ce dépôt a mesuré que la surface
  aide le routage (carte-08, 216 → 0 manquantes en l'agrandissant, 2026-09-07) ; on ne serre
  pas plus sans mesure.

### D-2026-09-19-b — Production : option 2 (Vercel + Cloudflare Tunnel), déploiement différé
**Statut : validée** par l'utilisateur le 2026-09-19 : « normalement option 2, mais pour le
moment on valide en local que tout fonctionne ». Proposition complète :
`docs/architecture/deploiement-production.md`.
- **Cible retenue — option 2 :** l'app web sur Vercel ; le service KiCad et le worker sur un
  serveur SANS port entrant, joint par Cloudflare Tunnel + Access (jeton de service
  Cloudflare, en plus du Bearer `KICAD_SERVICE_TOKEN`) ; la file sur un **Redis managé à prix
  fixe** (TLS + mot de passe), joint par Vercel ET le worker. Écartées : option 1 (service
  public, jeton seul) et option 3 (tout sur le serveur, recommandée par l'assistant).
- **Pour l'instant — rien n'est déployé :** la priorité est de valider en LOCAL que la chaîne
  complète fonctionne. Aucun code de déploiement n'est écrit avant cette validation.
- **Ce que l'option 2 impose, à ne pas oublier au moment du déploiement :**
  - `/api/agent` enfile lui-même dans Redis (`route.ts` l. 201 et 239) : Redis managé
    obligatoire, un tunnel HTTP ne transporte pas le protocole Redis ;
  - délai maximal du proxy Cloudflare (~100 s, à vérifier) : garder
    `CIRQIX_ASYNC_PIPELINE=1`, le SSE synchrone y serait fragile ;
  - limite de taille des corps côté Cloudflare, face aux boards en base64 (à vérifier) ;
  - en-têtes Access dans chaque client qui appelle le service (routes `render`, `model`,
    `/api/agent`, clients de `packages/agents`) ;
  - Vercel Pro (Hobby interdit l'usage commercial) ; le schéma vient de l'API Anthropic,
    `CIRQIX_SCHEMA_PROVIDER=claude-code` n'existant que sur l'hôte de dev.
- **Restent à trancher au déploiement :** fournisseur et taille du serveur (16 Go minimum
  estimés), fournisseur du Redis managé.

### D-2026-09-19-a — À 4, 6 et 8 couches, la masse reste sur les faces extérieures
**Statut : validée** par l'utilisateur le 2026-09-19, par choix explicite
(« Garder l'actuel (A) »), parmi trois options : A garder l'actuel, mesurer
A/B/C d'abord (recommandée), B plan de masse sur une couche interne.
- **La règle :** à tout palier (4, 6, 8 couches), le plan GND est coulé sur
  les deux faces extérieures seulement ; les couches internes ne portent que
  des signaux. GND reste confié au plan (`_NETS_CONFIES_AU_PLAN = ("GND",)`),
  jamais routé en pistes. Aucun changement de code : c'est le comportement
  en place.
- **Décidée en connaissance de cause :** elle n'est MESURÉE qu'à 2 couches
  (D-2026-09-10-c, carte-05). Au-dessus, la seule mesure est carte-08
  (D-2026-09-12-b : faces seules 100 % à 4 couches, faces + In1 88-96 %), une
  carte conçue pour 2 couches. Aucune carte du dépôt n'exige 8 couches ou plus.
- **Ce qui la remettrait en cause :** une carte qui a réellement BESOIN de
  6-8 couches et plafonne sous 100 % avec des broches GND orphelines. Les
  leviers pour un A/B restent en place, en réglages de banc :
  `plan_gnd_interne` (plan sur In1) et `gnd_route` (GND en pistes).
- **Hors de son périmètre :** 10 couches et plus. Le code les accepte
  (`_layer_ladder` sans maximum), les plans plafonnent à 8 (`PLAN_ENTITLEMENTS`,
  Enterprise compris) ; relever ce plafond est une décision commerciale distincte.

### D-2026-09-15-a — Marge entre un composant et le bord, pour que sa référence y tienne
**Statut : validée sous délégation** le 2026-09-15 — l'utilisateur a répondu
« go », puis explicitement « c'est toi de choisir ». Option **A** retenue :
elle supprime la cause (aucune place pour la référence) au lieu d'accepter
l'avertissement, et son coût (carte parfois un peu plus grande) est mesurable
avant livraison. Implémentation et mesure : voir la PR qui la livre.
- **Le fait mesuré :** 5 runs du prompt « diviseur de tension 5 V vers 3,3 V »
  par la file (après #201) : 5 livrés, dont **2 avec `silk_edge_clearance`**
  (« Silkscreen clipped by board edge »), même cause sur les deux — la
  référence de R2 (texte y 92,22..93,92) coupée par le bord haut (y 92,45).
- **Ce qui est déjà corrigé sans décision (#202) :** `degager_references`
  refuse désormais toute place hors carte. Mais rejoué sur les boards des runs
  3 et 4, **aucune place libre n'existe** : carte de 9,8 mm de large, R2 à
  1,2 mm du bord, ses pastilles dessous. L'avertissement reste (1 → 1).
- **Pourquoi c'est un seuil :** le contrôle de bord de #201 exige 0,75 mm
  entre les PASTILLES et le bord (le dégagement cuivre du DRC, 0,5 mm, + 0,25
  de marge de mesure). Rien ne réserve la place d'un texte de 1 mm.
- **Options :**
  - **A (recommandée)** — la COURTYARD de chaque composant non ancré à au moins
    **2 mm** du bord, dans `_trop_pres_du_bord` (`tools/placement.py`). Coût
    possible : cartes resserrées automatiquement un peu plus grandes.
    À mesurer sur les 11 cartes du banc et 5 runs du prompt.
  - **B** — accepter l'avertissement : cosmétique, non bloquant, sans effet
    électrique ni de fabrication.
- **Ce que l'utilisateur doit arbitrer :** A ou B. Rien n'est implémenté.

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

### D-2026-09-03-b — Un seul routage a la fois (verrou), 4 workers conserves
**Tranchee le 2026-09-04 par DELEGATION EXPLICITE de l'utilisateur** (« ok decide toi »).
Claude a choisi ; l'utilisateur peut inverser a tout moment.

- **Le fait qui force la main :** deux routages SIMULTANES dans un meme
  processus le font tuer par le noyau (`Out of memory: Killed process ...
  anon-rss:6247616kB`, crete 7,2 Go pour 7,6 disponibles).
- ⚠️ **RECTIFICATION DU 2026-09-05 :** cette entree affirmait qu'« un routage
  monte a 6,2 Go ». C'etait une generalisation depuis cette seule mesure, faite
  sur un cas pathologique. Echantillonne au cgroup pendant trois routages
  reussis, le conteneur ENTIER crete a **1,84 Go** contre 1,67 au repos, soit
  **~0,2 Go par routage**. La decision reste valide — la concurrence emballe
  bien la memoire — mais son motif chiffre etait faux.
  Le service tournait avec `--workers 4` : il annoncait quatre requetes
  simultanees quand la memoire n'en autorise qu'une.
- **Choix retenu :** garder les 4 workers, serialiser le SEUL point couteux par
  un verrou de fichier (`tools/verrou_routage.py`), decorateur sur
  `POST /route/auto`. Un service occupe repond **503**, jamais un faux succes.
- **Pourquoi pas 1 worker**, qui reglerait la memoire d'un mot : `GET
  /route/progress` — la progression livree la veille — et `GET /health`, dont
  Docker se sert pour juger le conteneur, attendraient alors la fin d'un
  routage de vingt minutes. Le conteneur serait declare malade a chaque routage.
- **Pourquoi pas plus de RAM :** hors du depot, et ne rend pas le service
  robuste ailleurs. Reste possible en complement.
- **Ce qui est PROUVE :** le verrou serialise deux processus reels du conteneur
  (le second attend 5,7 s que le premier libere) ; 16 tests, dont la
  concurrence ; aucune regression (temoin avec/sans verrou : 100 % routes dans
  les deux cas).
- ⚠️ **Ce qui n'est PAS prouve :** que la serialisation supprime les morts de
  worker observees. Le service reste instable par intermittence pour une cause
  NON identifiee, et cette instabilite empeche une mesure fiable. Le verrou
  borne la memoire par construction ; il ne se presente pas comme le remede a
  l'instabilite.
- **Code :** `services/kicad/tools/verrou_routage.py`,
  `services/kicad/routers/routing.py::_un_seul_routage_a_la_fois`.
  Garde : `tests/test_verrou_routage.py`.


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

**Statut : validée** par l'utilisateur le 2026-09-11 (« normalement on garde
le routage et on augmente, on ne répète pas de zéro »). Implémentée : au
changement de palier, les pistes du meilleur board du palier quitté sont
ajoutées à `_PISTES_A_PROTEGER` (même mécanisme que le repli GND, `(type
protect)` dans le DSN) ; le palier suivant ne route que ce qui manque.
Réglage `escalade_incrementale` (défaut : vrai). Garde :
`tests/test_escalade_incrementale.py`. Mesure à faire sur carte-08/10 (98 %
à 2 couches) : le 4 couches doit rendre ≥ 98 %, jamais moins.

Historique (avant validation) : souleve par l utilisateur le 2026-09-10.

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

## D-2026-09-14-b — ne pas arrêter l'escalade sur un manque GND tant qu'une orpheline NOMMÉE n'a pas eu son repli au palier suivant

**Statut : validée** par l'utilisateur le 2026-09-14 (« ok »). Implémentée :
`_escalade_peut_aider(..., orpheline_sans_issue=)`, drapeau
`palier_orpheline_accorde` dans `route_auto` (un seul palier de plus). Garde :
`tests/test_escalade_orpheline_nommee.py`.

⚠️ **LIVRÉE SANS MESURE, et il faut le dire.** Trois bancs sur carte-10 le
2026-09-14 ; aucun n'a exercé la règle :

| banc | ce qui s'est passé | exploitable ? |
|---|---|---|
| 1er | JVM Freerouting morte, tout au CLI, 5474 s | non |
| 2e | idem, budget épuisé | non |
| 3e (service reconstruit) | 6 couches, 97 %, 1 manquante, 2686 s | oui, mais… |

Le troisième tourne sur un service sain — et la règle **ne s'est pas
déclenchée** : aucune ligne « un palier de plus », aucun repli GND ciblé. La
raison est légitime : à chaque palier il manquait aussi des **signaux**, pas
seulement de la masse, donc l'escalade 2 → 4 → 6 s'est faite par la voie
normale et la règle n'avait rien à trancher.

Elle est donc **dormante** : elle ne peut agir que sur une carte dont le seul
net incomplet est un net de plan, avec une orpheline nommée dont le repli
ciblé vient d'échouer. Le code est borné (un seul palier supplémentaire, un
drapeau posé une fois) et gardé par ses tests, mais **aucune mesure ne montre
qu'elle apporte quelque chose**. La première carte qui tombera dans ce cas
devra être mesurée avant d'en tirer la moindre conclusion.

⚠️ Cause des deux premiers bancs, trouvée le même jour : **l'image du service
datait du 19 juillet** et ne contenait ni le superviseur qui relance la JVM
Freerouting (ajouté le 2026-09-12) ni `lancer_service.py`. Toutes les mesures
antérieures à sa reconstruction sont inexploitables — y compris le
« 98 % en 192 s » qui avait servi de référence dans cette même entrée.

**La règle actuelle** (règle de l'utilisateur, `_escalade_peut_aider`) :
« un net confié au PLAN ne se relie pas avec du cuivre en plus » — quand le
seul net incomplet est GND, l'escalade s'arrête. Elle était juste tant que
personne ne savait QUELLE broche manquait : monter d'une couche ne change
rien à un via qui tombe dans un îlot.

**Ce qui a changé le 2026-09-14** (PR #182) : l'orpheline est désormais
désignée par la connectivité (U1.8 sur carte-10), et le repli GND CIBLÉ —
qui rend au routeur cette broche et ses deux voisines GND, pistes existantes
protégées — se déclenche enfin. Mais il est tenté au palier COURANT, puis
l'escalade s'arrête sur la règle ci-dessus. Mesuré, placement gelé du verdict
par broches, carte-10 :

    palier 2 : repli ciblé U1-8 + C68-2 + C65-2 refusé (1 → 1 manquante)
               Freerouting n'a qu'UNE face de signal entre les sorties du LQFP
    palier 4 : jamais tenté — « escalade arrêtée avant 4 couches »
    verdict  : 98 %, 1 manquante, 192 s (vs 98 % / 1165 s / 2542 s avant)

**Proposition.** Quand une orpheline est nommée et que son repli ciblé a
échoué au palier courant, l'escalade CONTINUE d'un palier (deux couches
internes = un chemin pour une piste de masse courte), et le repli ciblé y est
rejoué (la mémoire des échecs porte déjà le palier). Si ce repli échoue aussi,
la règle actuelle s'applique. Coût : un palier de plus (≈ 5-10 min) sur les
seules cartes dont une broche de masse reste orpheline ; aucun changement sur
les cartes qui sortent à 100 % au premier palier.

**Ce que ça ne promet pas** : que Freerouting réussisse à 4 couches. La mesure
tranchera ; si elle réfute, la règle de l'utilisateur reste telle quelle.

## D-2026-09-14-a — le verdict « pro » du banc doit juger les broches, pas la moyenne des capas

**Statut : validée** par l'utilisateur le 2026-09-14 (« Ok »).

**Le fait.** `scripts/valider_placements.py` refuse un placement quand la
moyenne des écarts capa → broche VDD dépasse 5 mm. carte-10 est refusée à
CHAQUE tirage (5,4 · 5,5 · 5,6 · 5,7 · 5,8 mm sur cinq campagnes) alors que sa
**couverture** — chaque broche VDD a une capa à ≤ 3,5 mm — est à 2,1 mm.

**La cause, mesurée le 2026-09-14** (diagnostic capa par capa sur le
placement livré) : carte-10 met **22 condensateurs de découplage sur le seul
U1**, un LQFP à quatre broches VDD. Quatre capas peuvent être contre une
broche ; les dix-huit autres sont, au mieux, en deuxième rang — 5 à 8 mm. La
moyenne ne peut PAS descendre sous 5 mm sur cette carte, quel que soit le
moteur. Rejouer le snap seul sur le board livré ne gagne que 0,7 mm (5,5 →
4,8), ce qui mesure ce que l'Inspecteur et l'alignement sur grille défont
après lui — un second sujet, mineur.

Ce n'est donc pas un défaut de placement : c'est le critère qui juge des
capas surnuméraires comme si chacune devait être contre une broche.

**Proposition.** Le verdict du banc juge (1) la couverture — chaque broche
d'alimentation de chaque CI a une capa à ≤ 3,5 mm d'écart libre — et (2) la
moyenne des SEULES capas qui servent une broche (la plus proche par
pastille). Les capas au-delà (réservoir, deuxième rang) sont journalisées,
pas jugées. Aucun seuil ne change ; seule la population mesurée. Sur
carte-10 : couverture 2,1 mm, moyenne des servantes ≈ 2 mm → VALIDE ; sur les
dix autres cartes, verdict inchangé (une capa par broche, ou moins).

**Ce que ça ne fait pas.** Ça ne touche ni au placement livré ni au snap.
Le levier « `anchor_pin` jamais lu » annoncé le 2026-09-13 en prochaine
étape était PÉRIMÉ : le snap vise la pastille VDD depuis le 2026-09-10
(`_pastille_partagee`). Une prochaine étape se vérifie dans le code avant
d'être annoncée.

## D-2026-09-13-c — occupation de la surface : la carte livrée a la moitié basse vide

**Statut : validée** par l'utilisateur le 2026-09-13 (« C », les deux options) — **B ensuite RÉFUTÉE par la mesure le jour même, retirée ; A livrée.**

**La mesure qui a tué B** (banc des onze cartes, phase 1, deux variantes de la
règle — « tout au bord gauche puis droit », puis « bord le plus proche,
réparti ») contre les placements déjà livrés :

| carte | centrage av → ap (dx,dy %) | découplage av → ap (moy/max mm) | vide max av → ap (mm) |
|---|---|---|---|
| carte-01 | +1,−11 → +1,+1 | 0/0 | 7,8 → 6,8 |
| carte-03 | +1,+2 → 0,+5 | 2,3/2,3 → 1,8/1,9 | 3,2 → 6,8 |
| carte-05 | +1,+1 → −11,0 | 1,9/3,3 → 2,1/3,5 | 3,2 → 17,3 |
| carte-08 | +1,+1 → +3,0 | 2,6/4,2 → 3,9/7,0 | 5,5 → 10,5 |
| carte-09 | +1,0 → +7,0 | 3,2/5,2 → 4,4/6,4 | 4,8 → 19,6 |
| carte-10 | +1,+1 → +2,0 | 4,1/9,6 → 5,6/9,5 (non valide) | 6,5 → 8,3 |

Le centrage était déjà à ±1 % sur huit cartes ; la règle **dégrade le
découplage sur sept** et agrandit le plus grand vide. Elle n'aide que le cas
« petit circuit + connecteur au coin » (carte-01 ; la v2 du dashboard). On ne
livre pas une règle qui empire sept cartes pour en aider deux : B est retirée
du pipeline (`auto_place`), la fonction reste dans `tools/contour_et_bords.py`,
testée, pour un usage ciblé à décider.

**Trouvé en chemin, gardé :** le clamp des ancrages « reposait » presque
chaque connecteur loin du bord (collision jugée contre la grille initiale que
le génétique déplace) et jusqu'à 4,6 mm HORS carte (bornes testées sur
l'origine, pas sur le corps — carte-06 J10, `copper_edge_clearance`). Corrigé,
`tests/test_ancrage_reste_au_bord.py`.

**A, mesurée sur le banc le 2026-09-14** (onze cartes en taille heuristique,
phase 1 puis phase 2 à placement gelé, 2 tirages) :

| carte | contour av → ap (mm) | surface | routage (A) | livrée ? |
|---|---|---|---|---|
| carte-01 | 25×20 → 24,8×17,0 | 84 % | 100 %, 0 err | **oui** |
| carte-03 | 50×35 → 49,8×34,8 | 99 % | 100 %, 0 err | non (gain nul) |
| carte-04 | 60×45 → 45,0×44,8 | 75 % | 100 %, 0 err, 3 warn | **oui** |
| carte-05 | 70×50 → 69,8×49,8 | 99 % | 100 %, 0 err | non (gain nul) |
| carte-06 | 80×60 → 65,2×59,8 | 81 % | 100 %, 0 err | **oui** |
| carte-07 | 110×80 → 99,5×79,8 | 90 % | 100 %, 0 err | **oui** |
| carte-08 | 125×95 → 125×94,8 | 100 % | 94 %, 3 manq (4 couches) | non |
| carte-09 | 130×100 → 128×99,8 | 98 % | 96 %, 2 manq | non |
| carte-11 | 140×120 → 47,2×69,0 | 19 % | 100 %, 0 err | non (carte d'escalade, « ne pas la réparer ») |

carte-02 et carte-10 : placement sous le seuil de découplage, non routées.
Le contour ne resserre que ce que le génétique n'a pas rempli : gain réel sur
les circuits petits devant leur carte (−16 à −25 %), nul sur les cartes
denses. Les échecs de routage de 08 et 09 sont la dispersion connue (surface
inchangée), pas l'effet de A. Quatre cartes livrées plus petites, DRC local
0 erreur, rendus 3D régénérés.

**A, précisée :** une taille n'est *imposée* que si la description la donne
— le driver le dit par `board_size_imposed` dans le contrat du schéma ; des
dimensions choisies par le modèle sans ce drapeau sont une heuristique et le
contour suit le placement.

**Livré :** `tools/contour_et_bords.py` — B `ancrer_connecteurs_au_bord` (avant les tirages, dans `auto_place`), A `ajuster_contour_au_placement` (après le placement retenu, sur `auto_size_board`, posé par le client quand ni l'appelant ni la description n'imposent de taille). Gardes : `tests/test_contour_et_bords.py`, `handler-placement.test.ts`.

**La mesure** (projet « Thermometre I2C TMP102 (driver) » v2, clignotant NE555,
9 composants, carte 40 × 35 mm demandée « environ 40 × 30 » par l'utilisateur) :
les composants occupent y = 5 à 22,5 mm sur 35 — **la moitié basse est vide**.
Sérigraphie propre (0 référence sur du cuivre, 0 chevauchement), 100 % routé,
0 erreur : rien de faux, mais c'est la première chose qu'un relecteur voit.

**La cause** : `gen_pcb` ancre le connecteur J1 dans le coin haut-gauche
(5, 5) et le GA groupe le reste autour de lui ; la surface demandée n'est
pas un objectif du placement.

**Options, à trancher par l'utilisateur :**

- **A — auto-dimensionner la carte** au placement : contour = boîte des
  composants + marge (par exemple 3 mm), SAUF quand la description impose une
  taille. Carte moins chère, aspect « fait exprès » ; ne change rien à la v2,
  dont la taille était imposée.
- **B — ancrer les connecteurs au MILIEU d'un bord** plutôt qu'au coin, puis
  laisser le GA équilibrer autour. Traite la v2 ; change le placement de
  TOUTES les cartes à connecteur (banc à rejouer, 11 cartes, ~1 h).
- **C — les deux**, A puis B.

Recommandation : **C**. A est la pratique standard, B corrige l'asymétrie
visible ; l'un sans l'autre laisse un cas.

## D-2026-09-13-b — `CIRQIX_AGENT_MODE=driver` : la route enfile des runs de provenance `driver`

**Statut : validée** par l'utilisateur le 2026-09-13 (« Oui » sur l'option A
recommandée, contre B « recharger le crédit Anthropic »).

**Le fait :** une soumission depuis le dashboard crée un run `orchestrator`, et
le worker lance alors l'orchestrateur **Sonnet par l'API** avant même le
schéma. Remplacer Haiku par Claude Code (D-2026-09-13-a) ne suffit donc pas :
sans crédit, le run échoue au premier appel.

**Ce qui est fait :** `CIRQIX_AGENT_MODE=driver` fait créer par la route des
runs de provenance `driver`, **sans retenue de crédit** (rien ne tourne sur
l'API), enfilés dans la file ; le worker emprunte le porteur du driver et le
schéma vient du fournisseur configuré. Sans file (`CIRQIX_ASYNC_PIPELINE`,
`REDIS_URL`), la route répond 503 plutôt que de retomber sur le simulateur.

**Ce que ça ne change pas :** la commandabilité. `POST /api/jlcpcb/order`
exige `orchestrator` ; un board du mode driver reste non commandable. C'est un
mode d'exploitation le temps que le crédit revienne, pas le produit vendu.

## D-2026-09-13-a — Claude Code écrit le schéma à la place de Haiku (`CIRQIX_SCHEMA_PROVIDER=claude-code`)

**Statut : validée** par l'utilisateur le 2026-09-13 (choix explicite « Remplacer
Haiku par Claude Code dans call_agent_schema » parmi trois options proposées).

**Le fait :** le solde de l'API Anthropic est à zéro (400 « credit balance too
low », vérifié le 2026-09-13) ; l'abonnement Claude Code ne l'est pas. Claude Code
a déjà écrit deux schémas livrés à 100 % par la file (`examples/driver-clignotant-
ne555`, `examples/driver-stm32-minimal`), mais à la main, par un fichier JSON.

**Ce qui est fait :**
- un seul contrat de schéma, partagé (`tools/handlers/schema-prompt.ts` :
  prompt système + `parseSchemaText`) — Haiku et Claude Code ne peuvent plus
  diverger ;
- `tools/handlers/schema-claude-code.ts` : `claude -p --output-format json`,
  prompt par **stdin** (jamais en argument : `.cmd` sous Windows, injection),
  répertoire de travail **temporaire** (depuis le dépôt, le CLI charge
  `CLAUDE.md` : 130 000 jetons et 2,6 $ pour répondre `{"ok":true}`, contre
  0,96 $ depuis un dossier neutre), délai 5 min, `null` sur toute panne ;
- `call_agent_schema` choisit par `CIRQIX_SCHEMA_PROVIDER` (`haiku` défaut,
  échec fermé sur toute autre valeur) et annonce `engine: 'claude-code'` ;
- le porteur du driver accepte une **description** sans schéma
  (`runDriver({ prompt })`), le worker l'emprunte pour un run de provenance
  `driver` sans schéma, et `enfiler-driver.mjs --prompt "…"` l'enfile.

**Ce que ça ne change pas :** la provenance. Un run `driver` reste non
commandable (`POST /api/jlcpcb/order` exige `orchestrator`). Faire écrire le
schéma par Claude Code dans un run `orchestrator` n'est pas décidé ici : le
gate JLCPCB n'a pas été touché.

**Contrainte de déploiement :** le conteneur `cirqix-worker` n'a pas de `claude`
ni de session. Le fournisseur `claude-code` ne fonctionne que là où le CLI est
connecté — le worker lancé sur l'hôte (`node services/worker/dist/worker.cjs`).

## D-2026-09-12-b — à partir de 4 couches, le plan GND vit aussi sur une couche INTERNE

**Statut : validée** par l'utilisateur le 2026-09-12 (« Gi », lu comme « go »
sur l'option recommandée A), **puis réfutée par la mesure** une heure plus
tard. Banc 2d, carte-08, placement gelé identique :

| plan GND | 2 c. | 4 c. | 6 c. | 8 c. |
|---|---|---|---|---|
| faces seules (matin) | 67 % | **100 %** | — | — |
| faces + In1 | 67 % | 96 / 88 % | 96 / 96 / 94 % | 96 % |

Le plan In1 retire une couche entière aux signaux du LQFP, et l'îlot GND
F.Cu ↔ B.Cu subsiste (il n'est pas relié à In1 non plus). **Par défaut, les
faces seules** ; le levier reste un réglage de banc (`plan_gnd_interne`),
code et gardes conservés (`tests/test_plan_gnd_interne_des_quatre_couches.py`).
Une mesure étaye une proposition ; elle peut aussi la tuer, et c'est son travail.

Mesure du 2026-09-12 (carte-10, phase 2c, 6 tirages à 4 et 6 couches) : les
tirages sortent à 98 % avec la MÊME rupture — « Track [GND] 1,2 mm ↔ Via
[GND] », le tronçon d'échappement d'une broche GND du LQFP-48 (U1-8, puis
C37-2). Le via réservé est bien posé, mais il atterrit sur B.Cu dans un îlot
de plan de 1 mm² isolé par les pistes d'échappement ; l'îlot ne se coud pas
(trop petit pour un second via), il est retiré comme flottant, et la broche
reste orpheline. Sur stm32-100 (4 couches), même motif à 96-97 % pendant
quatre tirages. Les couches internes (In1, In2) n'ont AUCUN plan : elles ne
portent que des signaux, et un via traversant n'y trouve rien.

Aujourd'hui `_add_ground_planes` ne coule le plan que sur les deux faces
extérieures. Un empilage professionnel à 4 couches met la masse sur In1 :
tout via GND, où qu'il tombe, rejoint un plan continu qu'aucune piste ne
découpe. C'est une décision d'empilage (stratégie de routage), donc produit.

Options :
- **A** — plan GND sur In1 dès que le palier compte ≥ 4 couches, en plus des
  faces extérieures. Recommandée : c'est la pratique standard, et le via
  d'échappement atteint toujours du cuivre.
- **B** — statu quo, on s'en remet aux tirages (carte-10 est sortie à 100 %
  au 2e tirage, 4 couches).

Coût de A : un plan intérieur retire In1 aux signaux ; à mesurer sur
carte-08/09/10 (100 % à 4-6 couches aujourd'hui) avant de conclure.

## D-2026-09-12-a — le DRC de la chaîne et celui du routage jugent avec les MÊMES règles

**Statut : validée** par l'utilisateur le 2026-09-12 (« Gi », lu comme « go »
sur l'option recommandée B). Implémentée : `_projet_kicad` ne rend plus les
règles ouvertes qu'avec le réglage de banc `regles_fine_pitch` ; par défaut
le routage juge aux règles standard, comme la chaîne. Garde :
`tests/test_regles_microvias.py`. Même réponse pour la livraison : à
100 % / 0 erreur, le placement pro est livré même avec plus de couches
(`livrer_campagne.py --placement-pro`).

Mesure du 2026-09-12 (carte-08, campagne 1789171988) : le routage rend
« 100 %, 0 erreur » et la chaîne enregistre « 100 %, 2 erreurs DRC » sur le
même board. Deux instruments, deux règles :

| instrument | règles | via minimal | dégagement |
|---|---|---|---|
| `route_auto` (`_rapport_drc`) | projet « fine-pitch ouvert » dès qu'un boîtier dense existe (`_REGLES_FINE_PITCH`, 2026-08-26) | 0,30 mm, perçage 0,15, anneau 0,075 | 0,15 mm |
| `/drc/auto` (la chaîne, et `POST /api/jlcpcb/order`) | défauts KiCad (aucun projet) | 0,50 mm, perçage 0,30, anneau 0,10 | 0,20 mm |

Les règles ouvertes correspondent à une **option payante** chez JLCPCB
(perçage 0,15 mm). Un board « propre » pour le routage peut donc être refusé
par la chaîne, et un board livré peut coûter plus cher à fabriquer que prévu.

Deux options, une seule à choisir :
- **A** — la chaîne juge avec les règles ouvertes quand le board porte un
  boîtier dense (même helper que le routage). Livrable : oui, au tarif
  fine-pitch.
- **B** (recommandée) — le routage juge avec les règles standard : plus de
  via-in-pad sous 0,60 mm, les broches fines ne sortent que par tronçon + via
  (mécanisme réparé le 2026-09-11 : « tronçon seul quand le via est déjà
  là »). Livrable au tarif standard ; à mesurer sur carte-08/09/10.

Déjà fait sans décision (instrument, pas produit) : `_nets_incomplets` lit le
net de TOUT objet du rapport (`PTH pad`, `Via`, `Track`), donc un palier ne
peut plus afficher 100 % avec une liaison manquante.

Ne pas implémenter avant validation.

## D-2026-09-11-b — une carte qui stagne à son plafond de couches est AGRANDIE et re-placée

**Statut : validée** par l'utilisateur le 2026-09-11 (« go »). Implémentée en
règle générale : (1) le service rend le contour à la taille demandée quand
elle dépasse le contour du board (`_taille_contour`, `auto_place`) ; (2) la
boucle de la chaîne (`run_pipeline.py::taille_suivante`) agrandit de 20 % par
côté, au plus deux fois, une carte routée à son plafond de couches sans
100 % / 0 erreur. Gardes : `tests/test_agrandir_quand_stagne.py`. À porter
dans l'orchestrateur TypeScript (`run-orchestrator.ts`) pour la production.
La taille de la carte est une donnée visible du client (le générateur la
dimensionne au nombre de composants).

Mesure du 2026-09-11 sur `carte-08` (56 composants, 125 × 95 mm, plafond 98 %
depuis 24 h quels que soient placement, couches et routeur) : le MÊME schéma,
contour **150 × 114 mm (+20 %)**, placement complet (contrainte + rangées),
**100 % à 2 couches, 0 erreur** au premier tirage (1308 s dont attente du
verrou). Le levier des cartes denses n'est ni le routeur ni les couches :
c'est l'espace.

Proposition, générale : dans la boucle de la chaîne, quand un placement a
été routé à son plafond de couches sans atteindre 100 % (ou que le plancher
d'échappement dépasse le plafond), le contour est agrandi de 20 % (règle
`taille_carte`, qui sait déjà réécrire `Edge.Cuts`) et la carte est
re-placée — au lieu de re-tirer indéfiniment. Un pas maximal (par ex. deux
agrandissements) borne la surface. Le client voit une carte plus grande et
moins chère (2 couches) plutôt qu'une carte à 98 % sur 6 couches.

Ne pas implémenter avant validation.

## D-2026-09-11-a — plancher d'échappement > palier : UN tirage de preuve, puis escalade

**Statut : validée** par l'utilisateur le 2026-09-11 (« ok go »). Implémentée :
`_paliers_avec_tirages(…, plancher=…)` — un tirage par palier sous le
plancher, trois à partir du plancher ; réglage `tirage_de_preuve`. Garde :
`tests/test_tirage_de_preuve.py`. Elle nuance la décision du 2026-08-29
(« on part toujours de 2 couches »), qu'elle conserve.

Mesure du 2026-09-11 sur `carte-08` (56 composants, plancher calculé : 4
couches, budget 1800 s) : trois tirages à 2 couches (figé 80 %, 69 %, figé
80 %) ont consommé **tout le budget** ; le palier 4 couches, atteint à
13:14, a rendu « 0 % (aucun moteur) » — jamais tiré. La preuve « 2 couches
ne suffisent pas » a coûté la totalité de l'appel, et l'escalade que la
preuve devait déclencher n'a pas eu lieu.

Proposition, générale : quand le plancher d'échappement dit N > palier
courant, on garde le départ à 2 couches (le client ne paie pas une couche
sur une prévision) mais on n'y accorde **qu'un seul tirage de preuve** —
s'il n'atteint pas 100 %, on escalade tout de suite avec le budget restant,
pistes protégées. Aucun changement pour les cartes dont le plancher est 2.

Ne pas implémenter avant validation.

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
- ~~GND routé en pistes + plan coulé sur Bottom (2 couches) — déjà appliqué,
  confirmé par « grille de masse / ground pour ».~~ **Retiré le jour même**
  par D-2026-09-10-c (plus haut) : A/B sur carte-05 à 2 couches, GND en
  pistes 92 % contre GND au plan 100 %. Disponible par réglage `gnd_route`.
  Cette ligne disait encore « déjà appliqué » le 2026-09-18.

⚠️ **Portée réelle de la stratégie GND actuelle (relevé le 2026-09-19, à la
remarque de l'utilisateur : « notre solution doit marcher même sur 12 couches,
pas que deux couches »).** GND au plan, sur les faces extérieures seulement, a
été mesuré à **2 couches uniquement** (carte-05). Le code l'applique pourtant à
TOUS les paliers : à 4, 6, 8 couches et au-delà, les couches internes ne
portent que des signaux et aucun plan — ce qu'aucun empilage professionnel ne
fait. La seule mesure multicouche (D-2026-09-12-b, carte-08, conçue pour
2 couches) ne tranche rien pour une carte qui a réellement BESOIN de 6 ou
8 couches. « GND en pistes » contre « GND au plan » n'a jamais été mesuré
au-dessus de 2 couches. Le code accepte 10, 12, 16 couches (`_layer_ladder`
n'a pas de maximum), mais les plans plafonnent à 8, Enterprise compris
(`PLAN_ENTITLEMENTS`). Stratégie d'empilage au-delà de 2 couches : **tranchée
le 2026-09-19 par D-2026-09-19-a** (l'utilisateur garde l'actuel, masse sur les
faces extérieures à tout palier), en connaissance de cette portée.

**À faire, validé d'avance :**
- Routage orthogonal H/V par couche (préférence de direction Freerouting).
- Ordre de routage par priorité (fanout → critiques → alimentation → GPIO) —
  plus lourd, à mesurer avant.

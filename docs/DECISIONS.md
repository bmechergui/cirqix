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

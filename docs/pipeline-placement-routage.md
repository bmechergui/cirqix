# Pipeline placement → routage de Cirqix

> **Une seule chaîne, pour tout type de carte.** Aucun réglage n'est propre à
> une carte : chaque étape lit le board (nets, pastilles, boîtiers, contour) et
> applique une règle de l'industrie (`docs/methodologie-routage.md`). Les
> réglages de banc (`tools/reglages_banc.py`) ne servent qu'aux A/B ; le
> défaut est ce que le produit livre. Version du 2026-09-11.

## Ce qu'une carte doit atteindre pour être livrée

| critère | seuil | mesuré par |
|---|---|---|
| routage | **100 %** des connexions (verdict DRC, pas celui du routeur) | `kicad-cli pcb drc` |
| fabricabilité | **0 erreur** DRC (les avertissements de sérigraphie sont tolérés) | idem |
| couches | le **minimum** qui atteint 100 % (2 → 4 → 6, plafond du plan) | `livrer_campagne.py` |
| découplage | corps → broche VDD **≤ 3 mm** (1-3 mm, Hartley/IPC) | `comparer_a_la_reference.py` |
| paires LED/R | **≤ 5 mm**, en rangée | idem |
| grille | ≥ 80 % des empreintes sur le pas 0,5 mm | idem |
| placement livré à côté du board routé | `expected/placement.kicad_pcb` | `livrer_campagne.py` |

## Placement (`tools/placement.py::auto_place`)

```
0  contour        taille_carte.verifier_et_agrandir   le contour couvre l'encombrement réel
1  graine         bottom_up_placement (réglage)        grappes fonctionnelles posées avant le GA
2  contraintes    contraintes_du_board                 paires LED/R ≤ 5 mm ; par CI : ses découplages à corps + 3 mm
3  Architecte     OptimizationWorkflow hybrid          GA + force-directed, connecteurs ancrés
4  Géomètre       CMA-ES (enfant, 30 it.)              micro-raffinement, revert si > 20 mm ou erreurs
5  Inspecteur     PlacementAnalyzer + PlacementFixer   0 erreur garanti
6  halo           _reserve_escape_halos (5 mm)         canal d'échappement des fine-pitch ; capas exemptées
7  snap           snap_cluster_members                 une capa par broche VDD, sur la broche ; paires serrées
8  rangées        placement_rangees.ranger_les_paires  paires LED/R en rangée le long du bord le plus libre
9  grille         aligner_sur_grille (0,5 mm)          EN DERNIER, annulé si les erreurs augmentent
10 DRC placé      _compter_conflits_erreur             une erreur → re-tirage, on ne route jamais un board cassé
```

Chaque déplacement (4, 7, 8, 9) est suivi de l'Inspecteur et **annulé** s'il
ajoute une erreur. L'ordre est contraint des deux côtés : un snap avant le
Géomètre est défait par lui ; une grille avant les rangées est défaite par
elles.

## Routage (`routers/routing.py::route_auto`)

```
palier 2 couches (puis 4, 6 … jusqu'au plafond du plan)
  ① plan GND coulé et rempli sur les faces extérieures        _add_ground_planes + _fill_zones
  ② dogbones : chaque pastille CMS de masse reliée au plan       _relier_gnd_avant_routage
  ③ vias d'échappement des fine-pitch réservés dans le DSN       _vias_signaux_a_reserver
  ④ Freerouting (API, JVM persistante) — GND confié au plan      _route_with_freerouting_api
  ⑤ vias reposés, plans recoulés, fanout des pastilles isolées   _fanout_pads_isolees
  ⑥ couture des îlots, répétée                                   _coudre_les_ilots
  ⑦ DRC — c'est LUI qui donne le pourcentage                     _rapport_drc
tirages : 3 par palier ; le meilleur est gardé, jamais le dernier
escalade INCRÉMENTALE : les pistes + vias du meilleur board sont PROTÉGÉS
  dans le DSN du palier suivant (padstack lu dans le DSN) — jamais pire
```

Règles générales qui bornent le temps (toutes mesurées, `docs/DECISIONS.md`) :

- un tirage figé (150 passes sans progrès) est abandonné **et sa JVM tuée** —
  un job abandonné continuait sinon jusqu'à la passe 999 et ralentissait tous
  les suivants (D-2026-09-10-e) ;
- un placement dont tous les tirages figent sous 50 % est **condamné** : on
  rend la main pour re-placer, sans « dernière chance » (D-2026-09-10-d) ;
- le repli « GND en pistes » ne se paie que s'il reste ≤ 8 connexions ;
- GND est **confié au plan** sur 2 couches (A/B : 100 % vs 92 % en pistes,
  D-2026-09-10-c) ; `gnd_route` reste disponible pour un A/B multicouche.

### Ce qui manque quand une carte reste à 98 % (mesuré le 2026-09-11)

Sur carte-08 et carte-10, 60 verdicts DRC ratés : le net incomplet est
**GND dans 100 % des cas**, jamais un signal (le signal manquant change à
chaque tirage et disparaît à l'escalade). Le DRC nomme désormais les objets
séparés (« manquant : Via [GND] <-> Pad 23 [GND] of U1 »). Trois causes,
trois règles générales, toutes dans `routers/routing.py` :

| objet séparé | cause | règle |
|---|---|---|
| `Via [GND] <-> Pad 23 of U1` | le via réservé était déclaré au routeur, pas le tronçon pastille → via ; un signal passait dans le couloir | le tronçon est déclaré `(wire … protect)` avec le via (`_bloc_wiring`) |
| `Pad 1 [GND] of U2 <-> Zone [GND]` | la pastille est sur le plan, le relief thermique ne la rejoint pas | promue en connexion pleine comme une pastille affamée (`_pastilles_sur_le_plan_sans_raccord`) |
| pastille de 0402 sans sortie ni place pour un via | le repli global re-route TOUT le GND en pistes et perd 16 liaisons (0 retenu / 11) | **repli GND ciblé** : l'orpheline + 2 voisines GND d'un boîtier ordinaire, pistes libérées à 1,2 mm autour, répété ≤ 4 tours, avant et hors du seuil du repli global (`_repli_gnd_cible_iteratif`) |

Et une règle d'escalade : un meilleur board **sous 80 %** n'est plus protégé
au palier suivant — 55 % protégés à 4 couches donnaient 59 % figé à 6.

Chaque worker journalise l'**empreinte sha1 du module** au chargement :
`routers/` est monté à chaud mais le module importé ne suit pas le fichier,
et un worker périmé est indistinguable d'un worker à jour sans cette ligne.

## Boucle de la chaîne (`run_pipeline.py`, orchestrateur)

```
schéma → ERC → footprints → gen_pcb → [placement → routage → DRC] × ≤ 4 → export
```

On retire tant que le DRC n'est pas propre ; le meilleur est gardé
(`(composants perdus, erreurs, -%)`, puis couches).

**Agrandissement (D-2026-09-11-b, validée).** Une carte routée à son plafond
de couches sans 100 % / 0 erreur est agrandie de 20 % par côté pour l'essai
suivant, au plus deux fois (`run_pipeline.py::taille_suivante`) ; le service
rend alors le contour à la taille demandée (`tools/placement.py::_taille_contour`).
Mesure carte-08 : 98 % à 2, 4 et 6 couches pendant 24 h ; +20 % → 100 % /
0 erreur à 2 couches au premier tirage. Sous le plafond, l'escalade garde la
main ; un « 0 % (aucun moteur) » n'agrandit rien.

## Infrastructure — ce qui a coûté une journée et ne doit plus revenir

- uvicorn abat un worker muet 5 s : `lancer_service.py` porte la tolérance à
  30 s, la sonde de famine (`tools/sonde_gil.py`) écrit la pile avant la mort ;
- le journal Freerouting est lu par incréments (`tools/journal_freerouting.py`),
  jamais relu en entier ;
- la JVM est relancée en boucle par l'entrypoint (`|| true` sous `set -e`),
  `_tuer_la_jvm` ne vise qu'elle.

## Où voir le résultat

`examples/VUES.md` (index), `examples/<carte>/output/vue-placement.png` et
`vue-final.png`, `expected/placement.kicad_pcb` + `final.kicad_pcb`.
Régénération : `scripts/vues_index.py --rendre`.

## Ce qui reste ouvert

- campagne 1789150495 (08/09/10) : première mesure de la règle
  d'agrandissement dans la boucle. La même règle est portée en production
  (`packages/agents/src/engines/board-growth.ts`, câblée dans les deux boucles
  de re-tirage de `orchestrator.ts`, plafond = celui du plan).
- sérigraphie : références qui se chevauchent dans les rangées (A3).
- tirages sans budget en fin d'appel (« 0 % aucun moteur ») : ne pas les tirer.

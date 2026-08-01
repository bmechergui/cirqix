# Handoff — `2026-08-01-routage-fabricable-stm32`

- **Status:** `DONE` (objectif partiellement atteint — voir « Résultat »)
- **Owner:** `Claude Code`
- **Reviewer:** `aucun`
- **Receiver:** `human`
- **Branch:** `main` (+ PR #85 mergeable)
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Updated UTC:** `2026-08-01`

## Objectif

100 % routé **et** fabricable sur `examples/stm32-validation`, angles de routage
professionnels (pas de coin à 90°), **sans toucher au placement ni à sa
méthode**, en natif kct/kicad-tools, solution générale valable sur tout board.

## Résultat

| | Début | Fin |
|---|---|---|
| Erreurs DRC | 204 | **0** |
| Courts-circuits | 13 | **0** |
| Routé | 18 % | **82 %** |

**Fabricabilité atteinte** (0 erreur, vérifiée sur 3 boards indépendants).
**100 % routé non atteint** : plafond reproductible à 82 %, blocage géométrique.

## Méthode de mesure — non négociable

**Toute mesure locale Windows est invalide.** Sans `kct build-native`, le
routeur retombe sur l'A* Python et meurt sur deadline : **9 % en local contre
73 % en Docker**. Conteneur `cirqix-measure`, backend C++ 1.0.0 vérifié, juge =
`kicad-cli pcb drc` avec sidecar fabricant et `--refill-zones`.

⚠ L'image installe kicad-tools depuis `/opt`, **antérieur au gitlink** :
`--stitch-power-planes` et `ConflictType.OFF_BOARD` y sont absents.

## Le défaut central — angles de pads

Le writer du placement se trompe **dans les deux sens**, selon le tirage GA :

| Tirage | rotation boîtier | angle des pads | verdict |
|---|---|---|---|
| 1 | 0° | 90° — **en trop** | 204 erreurs |
| 2 | 270° | absent — **manque** | 204 erreurs |

Les pads 25-27 d'un LQFP-48 forment une colonne verticale au pas de 0,5 mm et
mesurent 1,475 × 0,3 mm. Dès que leur orientation ne suit pas celle du boîtier,
leur grand axe bascule le long de la colonne et les voisins se recouvrent d'un
millimètre. Preuve arithmétique dans le rapport DRC : `actual 0.0250 mm` entre
pads distants de 3 pas, soit exactement `1,5 − 1,475`.

**Règle correcte** : `angle_absolu = rotation_boîtier + angle_relatif_source`
(`restore_pad_angles`). Deux versions partielles ont échoué avant, chacune ne
couvrant qu'un des deux cas.

### Le réflexe de diagnostic qui manquait

`gen0` avant placement : **0 erreur**. Après placement, **0 piste** et déjà
**204 erreurs**. Le DRC sur le board **placé mais non routé** coûte 30 secondes
et prouve immédiatement que le routage est hors de cause. Faute de ce test,
l'essentiel de la session a été passé à traquer le défaut dans le routeur.

**Isoler l'étage avant de l'optimiser.**

## Les 10 défauts corrigés

1. Routeur et juge DRC sur deux règlements différents
2. Plancher fabricant transmis à la décimale exacte (1,6 µm → erreur DRC)
3. Zones jamais remplies → **aucun cuivre de masse à l'export Gerber**
4. Flag supposé au lieu d'être sondé (rc=2 sur toute la chaîne)
5. `board_origin` compté deux fois → 15-16 composants sur 17 hors carte
6. Budget de routage de l'exemple à 300 s contre 600 en production
7. Board partiel jeté → le reasoner ⑥b ne pouvait jamais s'exécuter
8. **Patch Cirqix #7 documenté mais jamais appliqué** → 204 erreurs
9. Ponts de masque interdits au niveau board → fine-pitch condamné d'avance
10. **Angles de pads corrompus** → la totalité des erreurs restantes

## Leviers fermés par la mesure — ne pas re-tester

| Levier | Résultat |
|---|---|
| `--routing-aware` | timeout 1500 s (contre 165 s pour `hybrid`) |
| `--use-routing-fitness` | timeout 1800 s |
| `--adaptive-rules` | 64 %, identique au nominal |
| clearance 0,127 / 0,15 mm | **refus de grille**, aucun board produit |
| pilotage LLM du reasoner | **dégrade** : 82 % → 73 % |

**0,2 mm de clearance est un plancher STRUCTUREL**, pas un choix conservateur :
le routeur refuse toute grille plus grossière que `clearance / 2`, et le budget
`max_cells` (non réglable) ne permet pas plus fin. Les 18 % manquants ne peuvent
donc pas être gagnés par la clearance.

Le seul levier qui gagne des points est le **dé-routage complet suivi d'un
re-routage** : 73 % → 82 %, point fixe confirmé sur deux passes.

## Pourquoi 82 % et pas 100 %

Blocage **géométrique et réparti** : `U2` et `J1` sont distants de 38 mm avec
**11 composants** dans la bande. Pas de bloqueur unique à écarter. Le routeur
diagnostique lui-même `Path blocked by component or trace`.

**La seule voie restante est de changer le placement**, exclu par la contrainte.

## Mes erreurs

- **Modifié la stratégie de placement validée** sans le demander : routage tombé
  à 0 % puis 36 %. Reverté (`a9c9e6e`).
- **Trois réparations du hors-carte** écrites puis retirées, chacune démentie par
  la mesure. Le défaut `OFF_BOARD` reste détecté mais non réparé.
- **Trois versions du correctif d'angles**, chacune validée sur un seul tirage.
- **Un harnais de mesure** rendant `rc=1`, un fichier et « 100 % »… avec
  **0 segment**. Toujours compter les segments du board produit.
- **Contention** : pytest lancé pendant un run Docker → 5 h 18 au lieu de 2 min.

## Validations

| Commande | Résultat |
|---|---|
| `pytest services/kicad/tests` | **257 verts** |
| Placement, Docker | 0 conflit, 0 hors carte, 0 erreur DRC |
| Routage, Docker | 64-82 %, **0 erreur DRC** |

## Travail restant

1. Réparer le défaut `OFF_BOARD` de `U2` (12-21 `copper_edge_clearance` sur
   certains tirages) — trois tentatives échouées, cf. mémoire projet.
2. Rebuild de `cirqix-kicad` sur le gitlink courant.
3. Pour les 18 % : Phase 6 RL_PCB, ou autoriser le reasoner à réorganiser le
   couloir `U2→J1`.

## Prochaine action atomique

Décider si la contrainte « ne pas toucher au placement » est levée pour ce
board. Sans cela, aucune optimisation de routage supplémentaire ne débloquera
les 18 % restants.

---

## Addendum — leviers de routabilité, tous fermés (2026-08-01, fin de session)

Comparatif des trois sorties, mesuré en Docker sur le même placement :

| Sortie | Routé | Erreurs DRC | Durée |
|---|---|---|---|
| ① `kct route` seul | 64-82 % selon tirage | 0 | ~600 s |
| ② ① + reasoner (dé-routage/re-routage) | **82 %** | **0** | ~1100 s |
| ③ ② + `PlaceRouteOptimizer` 2 itér. | **82 %**, 202 segments identiques | 0 | +861 s |

**② est le meilleur output** et le plafond du placement gelé.

### Pourquoi ③ n'apporte rien

`PlaceRouteOptimizer` optimise contre son propre `Autorouter` interne, qui n'a
ni `negotiated`, ni `--auto-layers`, ni la clearance dérivée du profil, ni
`--auto-mfr-tier`, ni les protections fine-pitch. Il résout des blocages que le
routeur de production ne rencontre pas, et ignore les siens. `success=False`
après 2 itérations, placement inchangé, 861 s perdues.

Deux erreurs de raisonnement corrigées au passage : le CLI **expose** bien un
plafond d'itérations (`--iterations`), et `--routing-aware` **remplace**
l'Architecte en ligne de commande alors que son contenu n'est qu'un affineur.

### Le blocage résiduel, mesuré

`NRST` (U2 → J1) barré par `C16` @ (146.5, 123.6) et `C1` @ (137.4, 119.6),
deux condensateurs de 1,5 mm posés sur la ligne directe. `P3V3` partiel 10/15.
Aucune piste ne traverse du cuivre.

**Dépasser 82 % exige un placement entraîné contre LE routeur de production.**
C'est l'objet de la Phase 6 RL_PCB.

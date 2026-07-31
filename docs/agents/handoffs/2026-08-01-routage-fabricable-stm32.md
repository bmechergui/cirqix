# Handoff — `2026-08-01-routage-fabricable-stm32`

- **Status:** `IN_PROGRESS`
- **Owner:** `Claude Code`
- **Reviewer:** `aucun`
- **Receiver:** `human`
- **Branch:** `main` (+ PR #85 mergeable)
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Updated UTC:** `2026-08-01`

## Objectif

100 % routé **et** fabricable sur `examples/stm32-validation`, angles de routage
professionnels (pas de coin à 90°), **sans toucher au placement ni à sa
méthode**, en natif kct/kicad-tools, avec une solution générale valable sur tout
type de carte.

## Méthode de mesure — non négociable

**Toute mesure locale Windows est invalide.** Sans `kct build-native`, `kct route`
retombe silencieusement sur l'A* Python et meurt sur deadline : **9 % en local
contre 73 % en Docker** pour le même board. Conteneur `cirqix-measure`
(image `cirqix-kicad:latest`, backend C++ 1.0.0 vérifié), juge =
`kicad-cli pcb drc` avec sidecar fabricant et `--refill-zones`.

⚠ L'image installe kicad-tools depuis `/opt`, **antérieur au gitlink du dépôt** :
`--stitch-power-planes` et `ConflictType.OFF_BOARD` y sont absents. Un rebuild
sur le gitlink courant est nécessaire pour une validation représentative.

## Défauts trouvés et corrigés

| # | Défaut | Mesure |
|---|---|---|
| 1 | Routeur et juge DRC sur deux règlements différents | clearance bridée à 2× la capacité fabricant → échappement LQFP-48 géométriquement impossible |
| 2 | Plancher fabricant transmis à la décimale exacte | une erreur DRC pour **1,6 µm** d'arrondi ; 4 → 2 erreurs |
| 3 | Zones jamais remplies | 12 fausses connexions manquantes, et **aucun cuivre de masse à l'export Gerber** |
| 4 | Flag supposé au lieu d'être sondé | un flag absent de l'image fait échouer tout le routage (rc=2) |
| 5 | `board_origin` compté deux fois après `write_to_pcb()` | **15-16 composants sur 17 hors carte**, 3 tirages sur 3 |
| 6 | Budget de routage de l'exemple à 300 s | contre 600 s en production — échecs fantômes |
| 7 | Board partiel jeté quand `min-completion` n'est pas atteint | le **reasoner ⑥b ne pouvait jamais s'exécuter** |
| 8 | **Patch Cirqix #7 documenté mais jamais appliqué** | `KCT_SAFE_OPTIMIZE` fixée nulle part → 204 erreurs DRC |
| 9 | Ponts de masque interdits au niveau board | condamne d'avance tout fine-pitch |

### Le point le plus important — #5

`PlacementOptimizer.from_pcb` construit ses `Component` avec `x=fp.position[0]`
(board-local) mais retranslate le polygone de la carte en page, en affirmant en
commentaire que « the optimizer adds components at their raw absolute
positions ». `update_footprint_position`, elle, documente attendre du relatif et
applique l'offset. **Les trois ne peuvent pas être vrais ensemble.**

Après correction : **0 conflit, 0 composant hors carte, 3 tirages sur 3**, en
151-180 s contre 207-329 s.

### Le point le plus subtil — #9

204 erreurs DRC identiques sur 3 boards routés à 9 %, 18 % et 18 %. Sur un board
à 9 % il y a une poignée de pistes : 107 violations de clearance ne peuvent pas
en venir. Classées : **toutes « pad + pad », zéro piste, zéro via, zéro zone**,
et toutes sur **U2 contre lui-même** — que `PlacementAnalyzer` ne peut pas voir,
puisqu'il compare les composants entre eux.

Ce ne sont pas les cuivres qui se touchent (mesuré : 0 paire sous 0,1016 mm) mais
les **ouvertures de masque**. Au pas de 0,5 mm avec des pads de 0,3 mm, la bande
de masque fait 0,2 mm — sous la largeur minimale. KiCad fusionne, et comme il
traite `<no net>` comme un net distinct, **chaque broche inutilisée crée un pont
avec ses deux voisines** : 31 broches libres → 84 ponts.

## Pistes fermées par la mesure

- **`--use-routing-fitness`** : timeout 1800 s sans terminer (jusqu'à 5 000
  routages avec `generations=100`, `population=50`).
- **`--routing-aware`** (`PlaceRouteOptimizer`) : timeout 1500 s.

Contre **165 s** pour la stratégie validée. Ces deux options étaient désignées
par `output/README-experiences-2026-07-22.md` et le handoff du 2026-07-19 comme
LA direction à suivre, jamais testée. **Elles ne tiennent pas le budget
0,12 €/PCB.** Ne pas re-benchmarker.

## Erreurs que j'ai commises

- J'ai **modifié la stratégie de placement validée** sans le demander
  (réparation hors-carte, marge par composant, re-tirage de l'Architecte). Le
  routage est tombé à 0 % puis 36 %. Tout est reverté au commit `a9c9e6e`.
- Trois réparations du hors-carte écrites puis retirées, chaque fois démenties
  par la mesure — la vraie cause était #5, à un seul endroit.
- Une suite pytest lancée **en même temps** qu'un run Docker a pris **5 h 18**
  au lieu de 2 min. Ne jamais chronométrer les deux ensemble.

## Validations

| Commande | Résultat |
|---|---|
| `pytest services/kicad/tests` | **250 verts** |
| Placement, 3 tirages Docker | 0 conflit, 0 hors carte, 151-180 s |
| Routage, 3 tirages Docker | **en cours** au moment d'écrire |

## Travail restant

1. Terminer la validation routage avec les correctifs #8 et #9.
2. Mesurer la distribution des angles (`0/45/90/135` vs arbitraires) — le board
   de référence de juillet n'a que **62 %** de segments alignés.
3. Rebuild de `cirqix-kicad` sur le gitlink courant.
4. Piloter le reasoner ⑥b, désormais atteignable grâce à #7 — jamais fait.

## Prochaine action atomique

Lire `examples/stm32-validation/output/valid-final.log` et mesurer les angles du
board produit avec `output/angles.py`.

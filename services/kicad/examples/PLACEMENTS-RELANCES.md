# Placements relancés — 2026-09-02

Relance du placement seul (aucun routage) sur les trois cartes demandées.
Chaque dossier `examples/<carte>/output/` contient **les deux versions**, pour
comparaison directe dans KiCad :

```
2_placement.kicad_pcb        l'ancien — celui qui a servi de référence au banc
2_placement_neuf.kicad_pcb   le nouveau
```

L'ancien n'a **pas** été écrasé : il est la référence de tous les verdicts du
banc, et l'écraser rendrait ces mesures inexploitables.

## Distance des condensateurs de découplage au MCU

Un découplage doit être à 2-3 mm de la broche qu'il sert ; au-delà,
l'inductance de la piste annule son effet.

### `nucleo-f401` — ancre `U1`, 8 condensateurs

| | ancien | neuf |
|---|---|---|
| C4 | 43,8 mm | **15,1 mm** |
| C8 | 62,8 mm | **13,8 mm** |
| C12 | 24,5 mm | **14,5 mm** |
| C16 | 62,5 mm | **14,2 mm** |
| C20 | 58,7 mm | **14,7 mm** |
| C24 | 51,5 mm | **15,1 mm** |
| C28 | 68,7 mm | **14,7 mm** |
| C29 | 58,3 mm | **14,1 mm** |

**Les huit passent de 24-69 mm à 13,8-15,1 mm** — un facteur quatre.

### `arduino-uno` — gain marginal, et deux régressions

```
C2  13,2 → 12,2 mm       C3  12,5 → 12,6 mm   (dégradé)
C5  11,2 → 10,2 mm       C4  12,2 → 12,6 mm   (dégradé)
```

### `esp32-baseline` — aucun changement

```
C1  23,7 → 23,7 mm    C2  39,9 → 39,9 mm    C3  35,8 → 35,8 mm
```

## Comparaison DRC — le neuf est meilleur ou égal partout

```
                 ancien              neuf
arduino-uno      35 violations  →    30        0 erreur des deux côtés
nucleo-f401      71 violations  →    50        0 erreur des deux côtés
esp32-baseline    1 violation   →     1        0 erreur
```

⚠️ `auto_place` a signalé « 4 conflits de placement NON RÉSOLUS » sur
`esp32-baseline`. Ce sont ceux de l'analyseur **interne**, pas du DRC : le
board final sort identique à l'ancien, sans erreur. Rien n'est cassé — mais le
message mérite d'être lu pour ce qu'il dit, et pas plus.

## ⚠️ Ce que ce gain n'est PAS

**Je ne peux pas attribuer le gain de `nucleo-f401` à la réparation du cluster
POWER** (`53329f3`), et je ne le ferai pas.

Le regroupement interne du GA de `kicad-tools` lit toujours le nom brut
`+3.3V` ; ma normalisation ne sert que **notre** snap, et le snap continue de
refuser les huit capas faute de place légale (contradiction 3 mm / 5 mm, voir
`docs/DECISIONS.md`, `D-2026-09-02-a`). Le gain vient donc très probablement du
GA ré-optimisant depuis un meilleur point de départ — c'est-à-dire d'un
**tirage plus heureux**.

Or le placement est **stochastique** : le projet a mesuré 6, 8 et 12 connexions
manquantes selon le tirage sur la même carte. Un seul tirage ne prouve rien sur
la reproductibilité de ces 14 mm.

**Pour en faire un résultat, il faudrait 3 à 5 tirages par carte** et regarder
la dispersion, pas le meilleur.

## Reste à faire si tu adoptes les nouveaux placements

Le routage n'a **pas** été rejoué : les verdicts du banc (`stm32-30` 100 %,
`nucleo-f401` 98 %, etc.) portent tous sur les **anciens** placements. Adopter
les nouveaux impose de relancer le banc pour obtenir des verdicts valides.

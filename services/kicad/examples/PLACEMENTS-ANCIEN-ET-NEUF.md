# Les placements : lequel est protégé, lequel est jetable

## ⚠️ Le danger qu'on vient d'écarter

`output/2_placement.kicad_pcb` **n'est pas un fichier sûr**. Deux raisons :

1. **Le banc l'écrase.** Toute exécution lancée sans `--placement-fige` le
   réécrit sans prévenir :

   ```python
   (sortie / "2_placement.kicad_pcb").write_bytes(board)
   ```

2. **Il n'est dans aucun dépôt.** `.gitignore` ligne 114 :
   `services/kicad/examples/*/output/`.

Autrement dit, le placement validé — celui sur lequel reposent **tous** les
verdicts du banc — ne tenait qu'à un fichier local, écrasable par une simple
relance. S'il avait été perdu, on n'aurait eu **aucun moyen d'y revenir**.

## La copie protégée

Chaque carte porte désormais, dans son dossier **versionné** :

```
expected/2_placement_valide.kicad_pcb    ← la copie de référence, dans Git
```

Neuf cartes, 924 Ko au total. C'est elle qu'on restaure si le placement neuf
casse quoi que ce soit :

```bash
cp examples/<carte>/expected/2_placement_valide.kicad_pcb \
   examples/<carte>/output/2_placement.kicad_pcb
```

## Les trois fichiers, et ce que chacun vaut

| fichier | dans Git | écrasable | rôle |
|---|---|---|---|
| `expected/2_placement_valide.kicad_pcb` | **oui** | non | **la référence — on y revient** |
| `output/2_placement.kicad_pcb` | non | **oui, par le banc** | ce que le banc relit en mode figé |
| `output/2_placement_neuf.kicad_pcb` | non | non | le placement relancé le 2026-09-02 |

`output/2_placement.kicad_pcb` garde son nom parce que le banc le lit
**exactement** ainsi en mode figé :

```python
fige = sortie / "2_placement.kicad_pcb"
if _PLACEMENT_FIGE and fige.is_file():
    board = fige.read_bytes()
```

Le renommer ferait retomber le banc dans la branche « figé demandé mais
ABSENT », qui recalcule un placement en prévenant que *« la mesure n'est PAS à
placement constant »*. Toutes les comparaisons deviendraient alors des
comparaisons de placements, plus de code.

## Ce que la référence protège

Les verdicts du banc du 2026-09-02 reposent **tous** sur elle :

```
cas             comp  couches   %   manq  err  warn  seg   durée
nucleo-f401       55     2     98     1    1    73   632   3668 s
stm32-30          30     2    100     1    0    24   173    413 s
stm32-60          60     2     98     2    0    68   374    324 s
stm32-100        100     2     99     3    0   130   710   4153 s
```

Et c'est la lignée de `stm32-validation`, cas d'étude de référence du projet,
dont `expected/stm32_final.kicad_pcb` sert de fixture pytest.

## Ce que le neuf apporte, et ce qu'il ne prouve pas

`nucleo-f401` — les huit condensateurs de découplage :

```
C4  43,8 → 15,1 mm      C20  58,7 → 14,7 mm
C8  62,8 → 13,8 mm      C24  51,5 → 15,1 mm
C12 24,5 → 14,5 mm      C28  68,7 → 14,7 mm
C16 62,5 → 14,2 mm      C29  58,3 → 14,1 mm
```

DRC, sur les trois cartes relancées — 0 erreur des deux côtés :

```
arduino-uno      35 violations  →  30
nucleo-f401      71 violations  →  50
esp32-baseline    1 violation   →   1
```

⚠️ **Un seul tirage ne prouve rien.** Le placement est stochastique : le projet
a mesuré 6, 8 puis 12 connexions manquantes sur la même carte selon le tirage.
Une campagne de 4 tirages par carte est en cours pour mesurer la **dispersion**
de ces distances — c'est elle qui dira si les 14 mm sont reproductibles.

⚠️ Le gain n'est **pas** attribuable à la réparation du cluster POWER
(`53329f3`) : le GA de `kicad-tools` lit toujours `+3.3V` brut, et notre snap
refuse encore les huit capas faute de place légale. Voir `docs/DECISIONS.md`,
`D-2026-09-02-a`.

## Adopter le neuf : ce que cela impliquerait

Le routage n'a **pas** été rejoué. Les verdicts ci-dessus portent sur l'ancien
placement. Adopter le neuf imposerait de relancer le banc complet — sinon on
comparerait un routage neuf à des chiffres obtenus sur un autre placement.

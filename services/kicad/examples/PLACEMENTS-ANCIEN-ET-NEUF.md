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

---

# Campagne de dispersion — 4 tirages par carte (2026-09-02)

Le placement est stochastique : un tirage isolé ne prouve rien. Quatre tirages
par carte, comparés au board conservé (« témoin »). Distance des condensateurs
de découplage au MCU, en médiane et en maximum.

```
carte             témoin   tirages                          étendue
arduino-uno        12,5     12,2 · 13,2 · 11,1 · 12,2         2,1 mm
nucleo-f401        58,5     14,8 · 14,4 · 14,8 · 14,5         0,4 mm
esp32-baseline     35,8     35,8 · 35,8 · 35,8 · 35,8         0,0 mm
```

## Verdict par carte

**`nucleo-f401` — l'ancien placement était un MAUVAIS TIRAGE.** Les quatre
tirages tiennent dans 0,4 mm autour de 14,5 mm ; le témoin, à 58,5 mm, est
très loin en dehors. Ce n'est donc pas de la chance : re-placer cette carte
améliore la médiane d'un facteur quatre, de façon reproductible.

⚠️ Deux réserves qui interdisent d'adopter sans vérifier :

```
le MAXIMUM varie   15,7 · 25,9 · 45,7 · 53,0 mm
                   un condensateur reste toujours loin — mais pas le même
le tirage 2 ajoute 1 erreur DRC
```

Un placement neuf n'est pas gratuit : il faut le passer au DRC à chaque fois.

**`arduino-uno` — aucun gain.** Le témoin (12,5 mm) tombe au milieu de la
plage des tirages (11,1-13,2 mm). Re-placer ne fait que tirer à nouveau.
Un point constant tout de même : les violations passent de 35 à 23-27 sur
**les quatre** tirages.

**`stm32-validation` — le neuf DÉGRADE.** Six condensateurs éloignés, quatre
rapprochés ; `C13` passe de 6,9 à 15,7 mm. DRC identique (0 erreur,
25 violations) — rien ne l'aurait signalé.

## ⚠️ `esp32-baseline` — le placement est un NO-OP sur cette carte

Quatre tirages, quatre résultats **bit-à-bit identiques** — y compris au board
d'entrée :

```
84707a6c5ee885a23678db21ee0095e2  2_placement.kicad_pcb
84707a6c5ee885a23678db21ee0095e2  2_placement_t1.kicad_pcb
84707a6c5ee885a23678db21ee0095e2  2_placement_t2.kicad_pcb
84707a6c5ee885a23678db21ee0095e2  2_placement_t3.kicad_pcb
84707a6c5ee885a23678db21ee0095e2  2_placement_t4.kicad_pcb
```

Pour un GA stochastique, c'est impossible. Le journal donne la cause :

```
auto_place: 3 conflit(s) au tirage 1/1 — on re-tire plutôt que de router un board cassé
auto_place: 11 conflit(s)  ·  9 conflit(s)  ·  7 conflit(s)
```

L'optimisation tourne, échoue à résorber 3 à 11 conflits, et le filet de
sécurité restaure l'entrée. Le comportement est **journalisé**, mais rien dans
la VALEUR RENDUE ne distingue « placé » de « rendu tel quel » : il faut
comparer les octets pour le voir.

⚠️ **Question ouverte, non mesurée.** Ce test a fourni un board DÉJÀ PLACÉ,
donc rendre l'entrée est inoffensif. Dans la chaîne réelle, `auto_place` reçoit
la **grille brute du générateur**. Si le même repli s'y déclenche, la carte
serait routée sur une grille non placée — et rien dans la réponse ne le dirait.
À mesurer séparément.

## Ce qu'il faut retenir

Aucun des deux placements n'est meilleur *par construction*. C'est la même
méthode qui tire deux fois. Ce que la dispersion permet, c'est de distinguer
un mauvais tirage conservé (`nucleo-f401`) d'un bruit sans enjeu
(`arduino-uno`) — et de repérer une carte où le placement ne fait rien du tout
(`esp32-baseline`).

# carte-05-capteur-i2c

> **Version git** `e74648b` (2026-09-07) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 26 composants ?*

## Le circuit

> un STM32 avec un capteur BME280 en I2C, deux LED d etat et un connecteur d extension

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 26 |
| nets | 13 |
| surface | 70 x 50 mm (135 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=False`, 43 violation(s) |
| **DRC du board livre** | **5 erreur(s)**, 30 violation(s) au total |
| types (board livre) | invalid_outline:1 · item_on_disabled_layer:4 · silk_over_copper:10 · silk_overlap:3 · track_dangling:10 · via_dangling:2 |
| **fabricable** | **NON** — 5 erreur(s) : invalid_outline, item_on_disabled_layer |
| fichiers exportes | 27 |
| duree du pipeline | 1052 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 290 | 29 | 0 | 26 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

30 composants : 70 x 50 mm. Le bus I2C sort du LQFP-48 par le bas, ses tirages sont groupes pres du capteur.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-05-capteur-i2c
python scripts/readme_banc_driver.py examples/carte-05-capteur-i2c
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

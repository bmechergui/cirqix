# carte-05-capteur-i2c

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
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
| DRC du pipeline | `clean=True`, 20 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 10 violation(s) au total |
| types (board livre) | silk_over_copper:4 · silk_overlap:6 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 327 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 143 | 36 | 3 | 26 |

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

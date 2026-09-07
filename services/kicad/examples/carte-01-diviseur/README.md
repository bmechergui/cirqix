# carte-01-diviseur

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 5 composants ?*

## Le circuit

> un diviseur de tension avec une LED temoin et un connecteur d entree

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 5 |
| nets | 4 |
| surface | 25 x 20 mm (100 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 6 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 3 violation(s) au total |
| types (board livre) | silk_over_copper:1 · silk_overlap:2 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 50 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 17 | 11 | 2 | 5 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

5 composants : 25 x 20 mm suffit largement, et une petite surface reduit l espace de recherche du routeur.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-01-diviseur
python scripts/readme_banc_driver.py examples/carte-01-diviseur
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

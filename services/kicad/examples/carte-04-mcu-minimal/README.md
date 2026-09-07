# carte-04-mcu-minimal

> **Version git** `61ebbae` (2026-09-07) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 15 composants ?*

## Le circuit

> un STM32 minimal : alimentation 3,3 V, decouplage, reset et connecteur de programmation SWD

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 15 |
| nets | 7 |
| surface | 60 x 45 mm (180 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 7 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 4 violation(s) au total |
| types (board livre) | silk_over_copper:1 · silk_overlap:2 · track_dangling:1 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 157 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 96 | 31 | 3 | 16 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

18 composants dont un LQFP-48 fine-pitch : 60 x 45 mm donne au routeur la place d echapper les broches.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-04-mcu-minimal
python scripts/readme_banc_driver.py examples/carte-04-mcu-minimal
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

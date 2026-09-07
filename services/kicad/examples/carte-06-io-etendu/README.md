# carte-06-io-etendu

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 35 composants ?*

## Le circuit

> un STM32 pilotant huit LED et exposant deux connecteurs d extension

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 35 |
| nets | 27 |
| surface | 80 x 60 mm (137 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 13 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 13 violation(s) au total |
| types (board livre) | silk_edge_clearance:1 · silk_over_copper:2 · silk_overlap:9 · track_dangling:1 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 624 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 242 | 43 | 3 | 35 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

35 composants autour d un LQFP-48 : les broches d E/S sont prises sur les QUATRE cotes du boitier, jamais groupees d un seul — c est ce qui avait plafonne la Nucleo a 68 %.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-06-io-etendu
python scripts/readme_banc_driver.py examples/carte-06-io-etendu
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

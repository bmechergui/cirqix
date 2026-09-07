# carte-08-dense

> **Version git** `61ebbae` (2026-09-07) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 56 composants ?*

## Le circuit

> une carte dense : seize sorties commandees et cinq connecteurs d extension

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 56 |
| nets | 49 |
| surface | 125 x 95 mm (212 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 77 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 40 violation(s) au total |
| types (board livre) | silk_over_copper:19 · silk_overlap:19 · track_dangling:1 · via_dangling:1 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 368 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 572 | 117 | 3 | 57 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

56 composants autour d un LQFP-48 : les broches d E/S sont prises sur les QUATRE cotes du boitier, jamais groupees d un seul — c est ce qui avait plafonne la Nucleo a 68 %. ⚠️ SURFACE PORTEE de 110x80 a 125x95 mm : a 110x80 le DRC rendait des `copper_edge_clearance` avec « actual 0 » — du cuivre touchait le bord. Meme cause que sur `carte-02`, meme reponse : on lit le diagnostic, on n ajuste pas au hasard.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-08-dense
python scripts/readme_banc_driver.py examples/carte-08-dense
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

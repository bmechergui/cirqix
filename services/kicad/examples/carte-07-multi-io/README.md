# carte-07-multi-io

> **Version git** `61ebbae` (2026-09-07) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 44 composants ?*

## Le circuit

> STM32F103 avec douze sorties a LED reparties sur les quatre cotes du boitier, cinq connecteurs, alimentation regulee et decouplage complet.

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 44 |
| nets | 37 |
| surface | 110 x 80 mm (200 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 52 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 29 violation(s) au total |
| types (board livre) | silk_over_copper:11 · silk_overlap:15 · via_dangling:3 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 1103 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 350 | 75 | 3 | 45 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

44 composants sur 110 x 80 mm, soit 200 mm2 par composant — entre la densite de la carte-06 (137, qui passe) et celle de la carte-08 (212, qui passe).

⚠️ CETTE CARTE A ETE RECONSTRUITE le 2026-09-07, et c est le constat le plus instructif du banc. Sa premiere version etait la carte-08 AMPUTEE de quatre paires de LED. Son schema etait sain — verifie : aucune broche pointant vers un composant absent, aucun composant isole. Et pourtant son PLACEMENT durait 1560 s, puis 70 minutes au tirage suivant, contre 104 s pour la carte-08 (56 composants) et 130 s pour la carte-10 (70). Douze a trente fois plus long pour MOINS de composants.

Ce n etait pas une contention : 12 processeurs, charge moyenne 4,00. C est le placement lui-meme, qui n a PAS de graine fixe (OptimizationWorkflow en strategie hybrid). Ce depot documentait deja sa dispersion en QUALITE — 6, 8 et 12 connexions manquantes selon le tirage ; on mesure ici qu elle porte aussi sur la DUREE, dans un rapport de trente.

Consequence : la duree d un pipeline ne se deduit PAS du nombre de composants, et un budget client calibre sur une moyenne coupera certaines cartes en plein travail. C est exactement le defaut deja corrige quatre fois ici.

La carte a donc ete refaite en ETENDANT la carte-06, qui passe, au lieu de mutiler la carte-08.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-07-multi-io
python scripts/readme_banc_driver.py examples/carte-07-multi-io
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

# carte-09-tres-dense

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 62 composants ?*

## Le circuit

> une carte tres dense : seize sorties commandees, cinq connecteurs et un decouplage renforce

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 62 |
| nets | 49 |
| surface | 130 x 100 mm (210 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=False`, 110 violation(s) |
| **DRC du board livre** | **1 erreur(s)**, 61 violation(s) au total |
| types (board livre) | silk_over_copper:31 · silk_overlap:22 · track_dangling:1 · unconnected_items:1 · via_dangling:6 |
| **fabricable** | **NON** — 1 erreur(s) : unconnected_items |
| fichiers exportes | 20 |
| duree du pipeline | 532 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 518 | 136 | 3 | 63 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

62 composants. ⚠️ PROFIL ETABLI le 2026-09-06 apres mesure : les versions qui ajoutaient des SORTIES (LED, connecteurs) finissaient avec des `via_dangling` et quelques connexions manquantes — chaque sortie tire un net de plus depuis le LQFP-48. La progression se fait donc par des condensateurs de DECOUPLAGE : ils ne portent que `+3V3` et `GND`, deux nets desservis par le PLAN, donc ils n ajoutent aucune liaison a router. Les broches d E/S restent prises sur les QUATRE cotes du boitier.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-09-tres-dense
python scripts/readme_banc_driver.py examples/carte-09-tres-dense
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

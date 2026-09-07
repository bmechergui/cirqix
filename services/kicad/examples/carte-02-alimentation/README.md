# carte-02-alimentation

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 12 composants ?*

## Le circuit

> une alimentation 5 V vers 3,3 V et 1,8 V, deux regulateurs, decouplage complet, deux LED temoins

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 12 |
| nets | 5 |
| surface | 55 x 40 mm (183 mm2 par composant) |
| **routage** | **100 %** |
| DRC du pipeline | `clean=True`, 4 violation(s) |
| **DRC du board livre** | **0 erreur(s)**, 2 violation(s) au total |
| types (board livre) | silk_over_copper:2 |
| **fabricable** | **oui** — aucune violation de severite `error` sur le board livre |
| fichiers exportes | 20 |
| duree du pipeline | 126 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 64 | 16 | 2 | 12 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

40 x 30 mm etait TROP PETIT : le DRC rendait 4 `copper_edge_clearance` avec « actual 0 » — du cuivre touchait le bord — et 48 `unconnected_items`, le plan de masse etant coupe par ce debordement. Deux SOT-223 (6,5 x 3,5 mm chacun, tab compris) plus dix passifs ne tiennent pas sur 1200 mm2. Porte a 55 x 40 mm, decision prise par le driver EN LISANT LE DIAGNOSTIC, pas par tatonnement.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-02-alimentation
python scripts/readme_banc_driver.py examples/carte-02-alimentation
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

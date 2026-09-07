# carte-11-croisements

> **Version git** `1c708ea` (2026-09-07) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 6 composants ?*

## Le circuit

> deux connecteurs 2x20 face a face, relies par un faisceau de 32 signaux cable EN ORDRE INVERSE — chaque liaison croise toutes les autres.

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 6 |
| nets | 34 |
| surface | 90 x 60 mm (900 mm2 par composant) |
| **routage** | **3 %** |
| DRC du pipeline | `clean=False`, 104 violation(s) |
| **DRC du board livre** | **42 erreur(s)**, 55 violation(s) au total |
| types (board livre) | copper_edge_clearance:2 · hole_to_hole:4 · silk_edge_clearance:2 · silk_overlap:1 · track_dangling:4 · unconnected_items:40 · via_dangling:2 |
| **fabricable** | **NON** — 42 erreur(s) : copper_edge_clearance, unconnected_items |
| fichiers exportes | 20 |
| duree du pipeline | 521 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| 13 | 3 | 0 | 6 |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

6 composants sur 90 x 60 mm. La densite n est PAS le sujet : cette carte est peu peuplee et route pourtant mal sur deux couches.

⚠️ ELLE EXISTE POUR METTRE L ESCALADE DE COUCHES A L EPREUVE. Aucune carte de ce depot n avait jamais declenche le passage a 4 couches — non parce que le mecanisme serait casse, mais parce qu aucune n en avait besoin : meme `stm32-100`, que `_couches_pour_echapper` declare a 4 couches, route a 100 % sur DEUX en 208 s. L absence de besoin n est pas une preuve de bon fonctionnement.

Ce qui rend deux couches insuffisantes ici n est pas le nombre de pistes mais leur NON-PLANARITE : un faisceau inverse de N signaux impose ~N²/2 croisements, et sur deux couches la face arriere porte le plan de masse — il ne reste qu UNE face de signal. Deux pistes qui se croisent ne tiennent pas sur une meme face.

Resultat attendu : echec net a 2 couches, puis passage a 4.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-11-croisements
python scripts/readme_banc_driver.py examples/carte-11-croisements
```

⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le
banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au
premier redemarrage — la lecon des worktrees vides, transposee.

Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,
`expected/mesures.json`.

# carte-07-multi-io

> **Version git** `4c45c7a` (2026-09-03) — le schema, le board et ces chiffres viennent
> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la
> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a 48 composants ?*

## Le circuit

> un STM32 avec douze sorties LED et cinq connecteurs d extension

⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —
Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le
driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle
mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,
aucune d'une description en langage naturel — la promesse du produit.

## Mesures

| | |
|---|---|
| composants | 48 |
| nets | 41 |
| surface | 115 x 88 mm (211 mm2 par composant) |
| **routage** | **None %** |
| DRC du pipeline | `clean=None`, None violation(s) |
| **DRC du board livre** | **? erreur(s)**, ? violation(s) au total |
| types (board livre) | aucune |
| **fabricable** | **NON** — **non mesure** — le pipeline n'a pas livre de board a juger |
| fichiers exportes | None |
| duree du pipeline | 1592 s |

Cuivre reellement pose sur le board livre :

| segments | vias | zones | empreintes |
|---|---|---|---|
| None | None | None | None |

⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un
compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC
vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant
« 0/16 route » sur un board portant 62 segments.

## Note de conception

48 composants, 211 mm2 par composant. ⚠️ PROFIL REPRIS de `carte-08` le 2026-09-06 : la version precedente oscillait entre 2 et 5 connexions manquantes selon le tirage — aleatoire, pas structurel. Plutot que de re-tirer indefiniment, on repart du profil qui rend 0 erreur et on retire quatre sorties. Le ratio de surface est aligne sur celui des cartes qui passent : 212 mm2/composant pour `carte-08`, 210 pour `carte-10`. ⚠️ CONSTAT DU 2026-09-07, le plus instructif du banc : le PLACEMENT de cette carte a dure 1560 s, contre 104 s pour `carte-08` (56 composants) et 130 s pour `carte-10` (70). Douze fois plus long pour MOINS de composants — et son schema est celui de `carte-08` moins quatre paires LED. Le placement n a pas de graine fixe (`OptimizationWorkflow` hybrid, cf. CLAUDE.md) : certaines configurations font diverger le GA. Ce n est donc ni la densite ni le compte, mais un tirage malheureux — et il rend le pipeline imprevisible en duree, pas seulement en resultat.

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

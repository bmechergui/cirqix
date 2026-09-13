# driver-stm32-minimal — un LQFP-48 écrit par le driver LLM, livré par la file

**Question posée :** la chaîne réelle tient-elle sur une carte dense écrite par
Claude Code (driver LLM) — un STM32F103C8 minimal, 27 composants — sans aucun
appel à l'API Anthropic ?

**Réponse (2026-09-13) : oui.** Run `a52f12df`, projet `4c6cc7e1`, provenance
`driver`, 506 s de bout en bout, 0 crédit.

## Ce que le driver a écrit

`input/schema.json` : STM32F103C8T6 en LQFP-48 alimenté en 3,3 V par un
AMS1117-3.3 (10 µF de part et d'autre), quartz 8 MHz HC49 avec ses deux 20 pF,
100 nF sur chacune des quatre paires VDD/VSS et sur VDDA, 100 nF sur NRST,
BOOT0 à la masse par 10 k, LED sur PC13 et quatre LED d'état sur PB0, PB1,
PB10, PB11 (470 Ω), connecteurs alimentation 5 V, SWD (3V3, SWDIO, SWCLK, GND)
et UART1 (3V3, TX, RX, GND). 27 composants, 21 nets, 70 × 50 mm.

## Ce que la chaîne a produit

| étape | résultat |
|---|---|
| SCHEMA, ERC | `.kicad_sch` produit ; ERC passé sans promotion `ERC_CLEAN` (repli TypeScript) |
| PLACEMENT (~7 min) | 0 erreur, découplage 2,3 mm en moyenne, 5,1 mm au pire |
| ROUTING (~1 min) | 100 % sur 2 couches, 59 vias, 548 mm de piste |
| DRC, EXPORT | `drc_clean`, 20 Gerbers + perçage + `pos.csv` + BOM, `PCB_LIVRÉ` |

Vérifié en local avec `kicad-cli pcb drc` sur `expected/final.kicad_pcb` :
**0 erreur, 0 connexion manquante**, 1 `via_dangling` (avertissement).

## Ce que ce run a révélé

Le journal du service portait « `serigraphie non degagee (name 'PCB' is not
defined)` » : la règle de dégagement des références, livrée la veille, était
**inerte en production** — son test ne vérifiait que la présence de l'appel
dans la source, et l'exception était avalée. Corrigée le jour même avec un test
qui exécute la règle sur un vrai board ; les références de ce board ont été
dégagées hors ligne (16 déplacées, 14 `silk_overlap` → 0).

## Ce que ce run ne prouve pas

- Le board n'est **pas commandable** (provenance `driver`) — voulu.
- La soumission depuis le dashboard avec un compte connecté n'a pas été jouée :
  run enfilé par `services/worker/scripts/enfiler-driver.mjs`.

## Fichiers

- `input/schema.json` — le schéma écrit par le driver
- `expected/schema.kicad_sch`, `expected/final.kicad_pcb`, `expected/rendu-3d.png`, `expected/mesures.json`

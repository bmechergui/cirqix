# Vues des cartes du banc — placement et routage

Pour chaque carte : `output/vue-placement.png` (board place, avant routage) et
`output/vue-final.png` (board route, plan GND coule), rendus par `kicad-cli pcb
render` depuis `expected/placement.kicad_pcb` et `expected/final.kicad_pcb`.
`output/` n est pas versionne ; regenerer avec `scripts/vues_index.py --rendre`.

Perimetre (decision utilisateur du 2026-09-10) : on traite TOUTES les cartes —
`carte-01` a `carte-11`, `stm32-30`, `stm32-60`, `stm32-100`, `stm32-baseline`,
`esp32-baseline` — SAUF deux REFERENCES intouchables : `stm32-validation`
(fixture pytest) et `STM32-Test-2026-09-10` (carte Astra/Codex).

Regle de lecture (docs/methodologie-routage.md) : decouplage corps->broche 1-3 mm,
grille = part des empreintes sur le pas 0,5 mm, paires = distance moyenne LED/resistance.
Une carte est FABRICABLE a 100 % route ET 0 erreur DRC ; les violations restantes
sont des avertissements de serigraphie.

| carte | livree le | route | err DRC | violations | couches | decouplage moy / max | grille | paires | placement | routage |
|---|---|---|---|---|---|---|---|---|---|---|
| carte-01-diviseur | 2026-09-10 (modifie) | 100 % | 0 | 4 | 2 | - | 100 % | 2.5 | [placement](carte-01-diviseur/output/vue-placement.png) | [routage](carte-01-diviseur/output/vue-final.png) |
| carte-02-alimentation | 2026-09-10 (modifie) | 100 % | 0 | 4 | 2 | 1.8 / 2.1 | 92 % | 3.0 | [placement](carte-02-alimentation/output/vue-placement.png) | [routage](carte-02-alimentation/output/vue-final.png) |
| carte-03-oscillateur | 2026-09-10 (modifie) | 100 % | 0 | 13 | 2 | 2.3 / 2.3 | 93 % | 4.0 | [placement](carte-03-oscillateur/output/vue-placement.png) | [routage](carte-03-oscillateur/output/vue-final.png) |
| carte-04-mcu-minimal | 2026-09-10 (modifie) | 100 % | 0 | 18 | 2 | 1.9 / 2.1 | 87 % | - | [placement](carte-04-mcu-minimal/output/vue-placement.png) | [routage](carte-04-mcu-minimal/output/vue-final.png) |
| carte-05-capteur-i2c | 2026-09-10 (modifie) | 100 % | 0 | 59 | 2 | 1.9 / 3.3 | 92 % | 4.0 | [placement](carte-05-capteur-i2c/output/vue-placement.png) | [routage](carte-05-capteur-i2c/output/vue-final.png) |
| carte-06-io-etendu | 2026-09-10 (modifie) | 100 % | 0 | 81 | 2 | 2.0 / 3.0 | 94 % | 4.0 | [placement](carte-06-io-etendu/output/vue-placement.png) | [routage](carte-06-io-etendu/output/vue-final.png) |
| carte-07-multi-io | 2026-09-11 (modifie) | 100 % | 0 | 260 | 2 | 2.5 / 4.8 | 93 % | 4.0 | [placement](carte-07-multi-io/output/vue-placement.png) | [routage](carte-07-multi-io/output/vue-final.png) |
| carte-08-dense | 2026-09-12 (modifie) | 100 % | 0 | 356 | 4 | 2.6 / 4.2 | 86 % | 2.5 | [placement](carte-08-dense/output/vue-placement.png) | [routage](carte-08-dense/output/vue-final.png) |
| carte-09-tres-dense | 2026-09-12 (modifie) | 100 % | 0 | 348 | 6 | 3.2 / 5.2 | 92 % | 4.0 | [placement](carte-09-tres-dense/output/vue-placement.png) | [routage](carte-09-tres-dense/output/vue-final.png) |
| carte-10-maximale | 2026-09-12 (modifie) | 100 % | 0 | ? | 4 | 4.1 / 9.6 | 93 % | 4.0 | [placement](carte-10-maximale/output/vue-placement.png) | [routage](carte-10-maximale/output/vue-final.png) |
| carte-11-croisements | 2026-09-12 (modifie) | 100 % | 0 | ? | 4 | - | 100 % | - | [placement](carte-11-croisements/output/vue-placement.png) | [routage](carte-11-croisements/output/vue-final.png) |

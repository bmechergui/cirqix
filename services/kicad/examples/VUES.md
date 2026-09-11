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
| carte-01-diviseur | 2026-09-10 | 100 % | 0 | 4 | 2 | - | 100 % | 3.6 | [placement](carte-01-diviseur/output/vue-placement.png) | [routage](carte-01-diviseur/output/vue-final.png) |
| carte-02-alimentation | 2026-09-10 | 100 % | 0 | 4 | 2 | 5.5 / 12.2 | 83 % | 10.3 | [placement](carte-02-alimentation/output/vue-placement.png) | [routage](carte-02-alimentation/output/vue-final.png) |
| carte-03-oscillateur | 2026-09-10 | 100 % | 0 | 13 | 2 | 3.5 / 4.9 | 87 % | 11.2 | [placement](carte-03-oscillateur/output/vue-placement.png) | [routage](carte-03-oscillateur/output/vue-final.png) |
| carte-04-mcu-minimal | 2026-09-10 | 100 % | 0 | 18 | 2 | 10.8 / 29.5 | 93 % | - | [placement](carte-04-mcu-minimal/output/vue-placement.png) | [routage](carte-04-mcu-minimal/output/vue-final.png) |
| carte-05-capteur-i2c | 2026-09-10 | 100 % | 0 | 59 | 2 | 3.6 / 7.9 | 81 % | 4.9 | [placement](carte-05-capteur-i2c/output/vue-placement.png) | [routage](carte-05-capteur-i2c/output/vue-final.png) |
| carte-06-io-etendu | 2026-09-10 | 100 % | 0 | 81 | 2 | 8.3 / 14.7 | 80 % | 15.3 | [placement](carte-06-io-etendu/output/vue-placement.png) | [routage](carte-06-io-etendu/output/vue-final.png) |
| carte-07-multi-io | 2026-09-09 (modifie) | 100 % | 0 | 260 | 2 | 2.5 / 3.7 | 91 % | 2.5 | [placement](carte-07-multi-io/output/vue-placement.png) | [routage](carte-07-multi-io/output/vue-final.png) |
| carte-08-dense | 2026-09-07 | 100 % | 0 | 77 | 2 | 10.6 / 19.5 | 4 % | 39.2 | pas de temoin | [routage](carte-08-dense/output/vue-final.png) |
| carte-09-tres-dense | 2026-09-11 | 100 % | 0 | 142 | 2 | 19.0 / 28.8 | 82 % | 34.2 | [placement](carte-09-tres-dense/output/vue-placement.png) | [routage](carte-09-tres-dense/output/vue-final.png) |
| carte-10-maximale | 2026-09-07 | 100 % | 0 | 104 | 2 | 15.8 / 26.5 | 3 % | 49.5 | pas de temoin | [routage](carte-10-maximale/output/vue-final.png) |
| carte-11-croisements | 2026-09-09 | 100 % | 0 | 10 | 2 | - | 100 % | - | [placement](carte-11-croisements/output/vue-placement.png) | [routage](carte-11-croisements/output/vue-final.png) |

# Vues des cartes du banc — placement et routage

Genere le 2026-09-10. Pour chaque carte : `output/vue-placement.png` (board place, avant routage)
et `output/vue-final.png` (board route, plan GND coule). Les PNG sont regeneres par
`kicad-cli pcb render` depuis `expected/placement.kicad_pcb` et `expected/final.kicad_pcb`
(`output/` n est pas versionne ; la commande est dans le journal de session du 2026-09-10).

Regle de lecture (docs/methodologie-routage.md) : decouplage corps->broche 1-3 mm,
grille = part des empreintes sur le pas 0,5 mm, paires = distance moyenne LED/resistance.

| carte | livree le | route | err DRC | violations | decouplage moy / max | grille | paires | placement | routage |
|---|---|---|---|---|---|---|---|---|---|
| carte-01-diviseur | 2026-09-10 | 100 % | 0 | 4 | - | 100 % | 3.6 | [placement](carte-01-diviseur/output/vue-placement.png) | [routage](carte-01-diviseur/output/vue-final.png) |
| carte-02-alimentation | 2026-09-10 | 100 % | 0 | 4 | 5.5 / 12.2 | 83 % | 10.3 | [placement](carte-02-alimentation/output/vue-placement.png) | [routage](carte-02-alimentation/output/vue-final.png) |
| carte-03-oscillateur | 2026-09-10 | 100 % | 0 | 13 | 3.5 / 4.9 | 87 % | 11.2 | [placement](carte-03-oscillateur/output/vue-placement.png) | [routage](carte-03-oscillateur/output/vue-final.png) |
| carte-04-mcu-minimal | 2026-09-10 | 100 % | 0 | 18 | 10.8 / 29.5 | 93 % | - | [placement](carte-04-mcu-minimal/output/vue-placement.png) | [routage](carte-04-mcu-minimal/output/vue-final.png) |
| carte-05-capteur-i2c | 2026-09-10 | 100 % | 0 | 59 | 3.6 / 7.9 | 81 % | 4.9 | [placement](carte-05-capteur-i2c/output/vue-placement.png) | [routage](carte-05-capteur-i2c/output/vue-final.png) |
| carte-06-io-etendu | 2026-09-10 | 100 % | 0 | 81 | 8.3 / 14.7 | 80 % | 15.3 | [placement](carte-06-io-etendu/output/vue-placement.png) | [routage](carte-06-io-etendu/output/vue-final.png) |
| carte-07-multi-io | 2026-09-09 | 100 % | 0 | 118 | 10.1 / 32.5 | 84 % | 15.7 | [placement](carte-07-multi-io/output/vue-placement.png) | [routage](carte-07-multi-io/output/vue-final.png) |
| carte-08-dense | 2026-09-07 | 100 % | 0 | 77 | 10.6 / 19.5 | 4 % | 39.2 | pas de temoin | [routage](carte-08-dense/output/vue-final.png) |
| carte-09-tres-dense | 2026-09-07 | 100 % | 0 | 86 | 14.4 / 22.3 | 3 % | 55.3 | pas de temoin | [routage](carte-09-tres-dense/output/vue-final.png) |
| carte-10-maximale | 2026-09-07 | 100 % | 0 | 104 | 15.8 / 26.5 | 3 % | 49.5 | pas de temoin | [routage](carte-10-maximale/output/vue-final.png) |
| carte-11-croisements | 2026-09-09 | 100 % | 0 | 10 | - | 100 % | - | [placement](carte-11-croisements/output/vue-placement.png) | [routage](carte-11-croisements/output/vue-final.png) |

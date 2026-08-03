# Bug kicad-tools — `kct route` émet du cuivre multi-couches sans via de liaison

- **Fork :** `bmechergui/kicad-tools`, branche `cirqix`
- **Date :** 2026-08-03
- **Sévérité :** haute — produit un board qui paraît routé mais dont des nets
  sont électriquement ouverts
- **Backend :** C++ 1.0.0 (`kct build-native --check` → available)

## Symptôme

`kct route` place, pour un même net, des pistes sur deux couches différentes
**sans poser le via qui les relie**. Le board sort avec un pourcentage de
complétion élevé, mais le DRC KiCad signale les deux tronçons comme non
connectés.

Extrait du rapport `kicad-cli pcb drc --severity-all --refill-zones`
(board à 82 % de complétion, 202 segments, 36 vias, 6 couches) :

```
Track [+3.3V] on In1.Cu, length 0.7072 mm | Track [+3.3V] on F.Cu, length 0.4633 mm
Track [+3.3V] on In4.Cu, length 0.7072 mm | Track [+3.3V] on F.Cu, length 1.3384 mm
Track [+3.3V] on In2.Cu, length 10.7168 mm | Track [+3.3V] on F.Cu, length 0.7089 mm
Track  [+5V] on F.Cu, length 0.1414 mm    | Track  [+5V] on In1.Cu, length 5.6569 mm
Pad 9  [+3.3V] of U2 on F.Cu              | Track [+3.3V] on In2.Cu, length 0.5500 mm
Pad 6  [OSC_OUT] of U2 on F.Cu            | Track [OSC_OUT] on In2.Cu, length 0.5500 mm
```

Les tronçons de 0,55 mm et 0,7072 mm sont caractéristiques : ce sont des amorces
de descente en couche interne, laissées orphelines.

## Comportement complémentaire — le routeur ne descend jamais de couche

Test d'isolation : router `NRST` **seul**, tous les autres nets figés, 6 couches
disponibles, `--preserve-existing` :

```
kct route in.kicad_pcb -o out.kicad_pcb --strategy negotiated \
    --layers 6 --no-auto-layers --clearance 0.2 --min-completion 0.0 \
    --preserve-existing --skip-nets <11 autres nets> --seed 42
```

Résultat :

```
Relief rescue: NRST blocked only by non-rippable copper of Net_2, Net_4, Net_5 -- rolling back
- Net 9 "NRST": blocked_path (blocked_path)
Total vias: 0
Nets routed: 0/1
```

**0 via créé**, alors que 5 couches internes étaient libres et qu'aucun autre net
ne pouvait plus bouger. Un via tient pourtant à côté des deux pads, mesuré
géométriquement (via 0,6 mm + 0,2 mm de clearance) :

| Pad | Position libre trouvée | Marge |
|---|---|---|
| `U2.7` | 1,6 mm du pad | 0,56 mm |
| `J1.5` | 0,4 mm du pad | 1,37 mm |

Le routeur cherche donc uniquement en surface, puis déclare `blocked_path`.

## Reproduction

Board : `services/kicad/examples/stm32-validation/`, STM32F103C8T6 en LQFP-48
(pas 0,5 mm), 17 composants, 12 nets, enveloppe 60 × 40 mm.

```bash
python examples/stm32-validation/output/chaine_aval.py   # placement validé
python -u examples/stm32-validation/output/stitch.py     # routage de production
```

Mesuré en conteneur Docker (backend C++ obligatoire — en A* Python pur le
routage tombe à 9 % contre 73 %).

Résultat reproductible sur 3 tirages : 73-82 % de complétion, 8 à 13 connexions
manquantes, toutes de la forme décrite ci-dessus.

## Leviers écartés par la mesure

| Levier | Résultat |
|---|---|
| `--targeted-ripup --max-ripups-per-net 8` | 73 %, inchangé |
| `--targeted-ripup --max-ripups-per-net 16` | 73 %, inchangé |
| `kct fix-vias` | ne fait que redimensionner les vias existants, n'en ajoute aucun |
| `kct stitch --net GND` | « No unconnected pads found on target nets » |
| `--preserve-existing` chaîné 2 → 4 → 6 couches | 82 %, aucun gain, 3× le temps |
| clearance 0,127 / 0,15 mm | refus de grille, aucun board produit |

## Défaut connexe — remplissage des zones

Le board sort avec **17 zones déclarées et 2 polygones remplis**. Les zones de
masse restent donc majoritairement vides, ce qui explique les connexions `GND`
manquantes sur les pads 8, 23, 35 et 47 de `U2`.

## Note sur `--stitch-power-planes`

Le drapeau est défini dans `src/kicad_tools/cli/route_cmd.py:9945`
(`parser.add_argument("--stitch-power-planes", ...)`) mais **n'apparaît pas dans
`kct route --help`** : le parseur actif est celui de
`src/kicad_tools/cli/commands/routing.py`. Le code de `route_cmd.py` semble donc
mort pour ce chemin. À confirmer côté amont.

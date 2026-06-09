# Exemple de référence — Validation pipeline STM32 (input → output)

> Cas d'étude complet exécuté le 2026-06-09 sur Windows (local, sans Docker) :
> **pipeline_pro.sh → optimiseur_pro.py → kct route → driver LLM** sur un
> devboard STM32F103C8T6 (Blue Pill, LQFP-48 0.5mm — le cas de stress du routage).
> 4 bugs upstream kicad-tools trouvés et patchés pendant cette validation.

---

## Le board

`input/generate_design.py` (copie du board `04-stm32-devboard` de kicad-tools) :
- U2 STM32F103C8T6 (LQFP-48, pitch 0.5mm) — Y1 quartz 8 MHz + C10/C11 20pF
- U1 AMS1117-3.3 LDO + C1-C3 — C12-C16 bypass — J1 header SWD 6 pins
- R1/D1 LED utilisateur — R2 pull-down BOOT0
- 17 composants, 12 nets, board 60×40mm, 4 couches après escalade

## Workflow reproduit (depuis la racine du repo)

```bash
export PYTHONUTF8=1                       # OBLIGATOIRE sur Windows (voir bug #1)
export PYTHONPATH=services/kicad/kicad-tools/src
export KICAD_SYMBOL_DIR="C:\Program Files\KiCad\<ver>\share\kicad\symbols"
export KICAD_FOOTPRINT_DIR="C:\Program Files\KiCad\<ver>\share\kicad\footprints"
export PATH="$PATH:/c/Program Files/KiCad/<ver>/bin"   # kicad-cli pour DRC/Gerbers

# 1. Générer schéma + PCB initial
python -m kicad_tools.cli build <dossier_board> --step schematic

# 2. Pipeline complet : sync → placement → route → reason → check
bash services/kicad/scripts/pipeline_pro.sh <dossier_board>

# 3. Driver LLM (Claude joue le LLM) : état → décision → exécution → diagnostic
python services/kicad/scripts/driver_llm.py state  <board_routé.kicad_pcb>
python services/kicad/scripts/driver_llm.py exec   <in.kicad_pcb> <out.kicad_pcb> batches/batch1.json
```

## Les batches du driver LLM (`batches/`)

| Batch | Décision du LLM | Résultat |
|-------|-----------------|----------|
| `batch1.json` | Supprimer 28 traces/vias mortes (2 courts-circuits DRC officiels : via OSC_OUT dans pad GND de C11, via LED_K dans pad +3.3V de R1) + **déplacer D1 et R2 hors du couloir U2→J1** (suggestion du routeur lui-même) | 9/9 ✅ |
| `batch2.json` | Nettoyer les traces orphelines de USER_LED (D1 a bougé) + re-router les 9 nets signaux. **Pré-requis découvert : retirer les zones cuivre** (le routeur du reasoner les rasterise en obstacles durs → 0 chemin possible) | 8/10 ✅ dont SWO, irroutable pour le routeur auto même en 6 couches |
| `batch3.json` | Router NRST + OSC_OUT restants + les power nets (+5V, +3.3V, GND) en pistes larges 0.4mm, vias autorisés | +5V ✅, +3.3V 8/14, GND 10/17, NRST toujours bloqué |
| `batch4.json` | Redéfinir les zones via `define_zone` : GND sur B.Cu (priorité 1) + +3.3V sur In2.Cu (plan power du stack 4 couches) | 2/2 ✅ → **11/12 nets** |

## Résultats

| Méthode | Nets routés | Commentaire |
|---------|-------------|-------------|
| `kct route --auto-layers` (2→6L, backend Python) | **22%** (2/9) | BLOCKED_PATH géométrique, pas de la congestion |
| `kct reason --auto-route` (heuristique) | 22% (0/4 sauvés) | ne déplace pas les composants |
| **Driver LLM (4 batches)** | **11/12 nets** (92%) | D1/R2 déplacés → couloir libéré → SWD routé, dont SWO irroutable avant |

**Réserve honnête** : le DRC officiel (`kicad-cli pcb drc --refill-zones`) compte
encore 23 connexions manquantes + 51 violations (20 courts) sur `expected/stm32_final.kicad_pcb` —
le petit routeur A* du reasoner route net par net **sans négociation de conflits**
(contrairement au routeur principal). Le concept est prouvé, pas la qualité des pistes.

Leçon : l'échec du routage était un **problème de placement**, pas de routeur —
exactement le rôle de `call_agent_reason` dans le pipeline Layrix. En prod, le bon
enchaînement est : **reasoner déplace les composants → on relance `kct route`**
(routeur négocié complet), pas « le reasoner route lui-même ». Le backend C++
(`kct build-native`, Docker) accélère mais ne résout pas un couloir bloqué.

## Les 4 bugs upstream trouvés (patchés dans la lib vendorée)

> Détail complet + diff : `services/kicad/DEPENDENCIES.md` §kicad-tools.

1. **Crash charmap Windows** — emojis (`⚠️✓🔴`) dans les logs du routeur tuaient
   le routage en plein vol sur console cp1252 (`router/fine_pitch.py`, `core.py`,
   `two_phase.py`, `monte_carlo.py`, `cli/route_cmd.py`). Fix : ASCII (`[!]`, `[ok]`).
2. **`int('+5V')` dans le reasoner** — kicad-cli 9/10 réécrit les zones au format
   name-only `(net "+5V")` après `fill-zones` ; le parser du reasoner crashait.
   Fix : `_resolve_net_node()` dans `reasoning/state.py` + `interpreter.py`.
   ⚠️ Latent en prod Docker (upgrade KiCad ⇒ crash `/reason/auto`).
3. **`layer_count=2` hardcodé** — le reasoner ne lisait jamais le nombre réel de
   couches : toute commande `route_net` crashait (`Layer value not in stack`) sur
   les boards 4/6 couches (= nos plans Pro/Pro Max). Fix : promotion automatique
   depuis `PCBState.layers` dans `interpreter.py`.
4. **Zones = obstacles durs dans le routeur du reasoner** — non patché (contourné) :
   le driver retire les zones avant routage et les redéfinit après (`define_zone`),
   même ordre que `kct route` (route d'abord, pour ensuite).

## `expected/`

- `stm32_final.kicad_pcb` — board final après driver LLM (référence)
- `render_top.png` — rendu `kicad-cli pcb render` du résultat

Les fichiers intermédiaires (`_optimised`, `_routed`, `step1/2/3`…) sont
régénérables et **ne doivent jamais être committés** (règle CLAUDE.md).

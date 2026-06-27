# Exemple de référence — Validation pipeline STM32 (input → output)

> **1 dossier = 1 cas = 1 question.** Ce cas : « placement → routage → sauvetage
> marchent-ils sur un board donné ? » (agents ④→⑥b, part d'un `.kicad_pcb`).
> Pour le pipeline COMPLET 8 agents depuis un JSON (« description → Gerbers »),
> voir `../stm32-full-pipeline/`.

> Cas d'étude complet exécuté le 2026-06-09 sur Windows (local, sans Docker) :
> **placement optimiseur → kct route → driver LLM** sur un devboard
> STM32F103C8T6 (Blue Pill, LQFP-48 0.5mm — le cas de stress du routage).
> 4 bugs upstream kicad-tools trouvés et patchés pendant cette validation
> (+ un 5e le 2026-06-10, voir plus bas). Workflow actuel : `run_agent_chain.py`
> (les scripts historiques `pipeline_pro.sh`/`optimiseur_pro.py` ont été supprimés).

---

## Le board

`input/generate_design.py` (Générateur géométrique "Phase 0") :
Son rôle est purement géométrique : il génère le schéma et le `.kicad_pcb` brut, mais sans aucune intelligence de routage ou de placement. Ce script est **appelé automatiquement en sous-processus** par notre orchestrateur principal `run_agent_chain.py`.
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

# 1. Pipeline Automatisé (Génération → Placement → Routage)
# L'orchestrateur appelle générator_design.py en interne (Etape 0), puis place (Etape 1) et route (Etape 2).
# Les fichiers générés sont automatiquement triés dans des sous-dossiers :
# out_dir/0_generation, out_dir/1_placement, et out_dir/2_routing.
python services/kicad/examples/stm32-validation/run_agent_chain.py <out_dir>

# 2. Driver LLM (Claude) lit l'analyse dans <out_dir>/2_routing/routing_analysis.txt
# et écrit son batch (ex: my_decisions.json), puis lance la boucle de sauvetage (Étape 4) :
python services/kicad/examples/stm32-validation/run_agent_chain.py <out_dir> --rescue my_decisions.json
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
exactement le rôle de `call_agent_reason` dans le pipeline Cirqix. En prod, le bon
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

## Rejouer la chaîne agents de PROD (`run_agent_chain.py`)

> Session 2026-06-10 : la même validation, mais via les **fonctions de production**
> (`tools/placement.py`, `tools/kct_route.py`, `tools/reasoning.py`) — celles
> qu'exécutent les endpoints `/place/auto`, `/route/auto`, `/reason/auto`.

```bash
# Étapes 0→2 : generation (via generate_design.py) → placement optimiseur → kct route
python run_agent_chain.py output/chain

# Le script crée automatiquement une arborescence propre étape par étape :
#  - 0_generation/  (Contient stm32_devboard.kicad_pcb brut et le schéma générés par generate_design.py)
#  - 1_placement/   (PCB placé + placement.log)
#  - 2_routing/     (PCB routé + routing_analysis.txt si le routeur bloque)

# Le driver LLM (Moi, l'IA) lit 2_routing/routing_analysis.txt,
# écrit decisions.json (place_component/delete_trace), puis :
python run_agent_chain.py output/chain --rescue decisions.json
# -> Ce qui génère le dossier 3_rescue/ (batch json, logs, et pcb sauvé)
```

> Note sur `run_feedback_loop.py` :
> C'est un tout petit script de test indépendant. Il importe exactement la même fonction (`rescue_with_placement_feedback`), mais il sert uniquement si un développeur veut tester la boucle de sauvetage toute seule (sans passer par la génération, le placement, etc.), avec le même pattern « moi = le LLM » (décisions servies depuis un JSON, sans clé API).

### Bug #5 trouvé par cette validation — kct route ne rippe pas l'existant

Re-router un board **déjà partiellement routé** le dégrade : les anciennes
pistes/vias sont des obstacles durs pour la passe from-scratch du routeur
(pads côté J1 tous stranded). Mesures (même placement, mêmes options, seed 42) :

| Board d'entrée | Nets routés |
|----------------|-------------|
| avec routage résiduel (53 segs + 3 zones) | 3/9 (33 %) — malgré escalade 4 couches |
| zones retirées, pistes gardées | 3/9 — identique (zones hors de cause) |
| **entièrement dé-routé** | **8/9 (89 %) sur 2 couches** |

**Fix prod (`tools/reasoning.py`)** : `_strip_routing()` — la boucle
placement-feedback dé-route TOUT (segments/vias/zones) avant chaque passe
`route_fn` ; kct route re-coule les zones power lui-même. Le nettoyage
« traces orphelines » est supprimé (subsumé). Tests TDD :
`tests/test_reasoning_feedback.py`.

Résultat boucle complète sur ce cas : 33 % (dégradé, avant fix) → 56 % conservé
(après fix, déplacements C10/C11 près de Y1 + D1/R2 hors du couloir U2→J1).
⚠ Le routeur reste non-reproductible d'un run à l'autre sur board identique
(56 –89 % observés ; stagnation/deadline wall-clock, issues upstream #2673/#2802) —
la garde anti-régression de la boucle conserve toujours le meilleur board vu.

## `expected/`

- `stm32_final.kicad_pcb` — board final après driver LLM (référence)
- `render_top.png` — rendu `kicad-cli pcb render` du résultat

Les fichiers intermédiaires (`_optimised`, `_routed`, `step1/2/3`…) et tout
`output/` sont régénérables et **ne doivent jamais être committés** (règle
CLAUDE.md — `.gitignore` : `services/kicad/examples/*/output/`).

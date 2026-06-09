# Dépendances vendorées — KiCad Service

Ces deux librairies sont installées localement en mode éditable (`pip install -e .`).
Elles sont **ignorées par git** mais leurs versions sont trackées ici.

## circuit_synth

- **Source :** https://github.com/circuit-synth/circuit-synth
- **Version locale :** 3.12 (0.12.1 selon git commit)
- **Chemin :** `services/kicad/circuit_synth/`
- **Install Docker :** `pip3 install --no-cache-dir ./circuit_synth`
- **Patches Layrix :**
  - `src/circuit_synth/kicad/sch_gen/circuit_loader.py` — fix pin_identifier vide
    → `_parse_circuit`: exclure `""` et `None` (pas seulement `"~"`) du test de nom de pin.
    Sans ce fix: Device:R et Device:C → pin_identifier="" → find_pin retourne toujours pin 1
    → VCC_5V ET DHT_DATA tous deux au même endroit (pin1) → R1.pin2=unconnected.
    Ligne ~286: `if "name" in pin_data and pin_data["name"] not in ("~", "", None):`
  - `src/circuit_synth/kicad/schematic/geometry_utils.py` — fallback index-based
    → `get_actual_pin_position`: si pin.number absent, utiliser l'index (défensif).

## kicad-tools (dossier officiel complet — 2026-06-02)

- **Source :** https://github.com/rjwalters/kicad-tools (dépôt officiel complet, avec
  src/, docs/, examples/, boards/, MCP, build C++).
- **Chemin :** `services/kicad/kicad-tools/` (tiret ; le package Python reste `kicad_tools`).
- **Import Python :** ajouter `kicad-tools/src` au sys.path → `import kicad_tools`.
- **Install Docker :** `pip3 install -e "/tmp/kicad-tools[placement,drc,geometry,native]"`
  puis `kct build-native --force` (backend C++ A* — 10-100× plus rapide ; non‑fatal).
- **Workflow officiel utilisé par nos agents :**
  - Placement : `kct create-pcb` (placement initial) → `kct placement optimize --fixed <connecteurs> --cluster`
  - Routage   : `kct route --mfr jlcpcb --auto-layers --auto-fix --seed`
  - Voir `docs/guides/placement-optimization.md` + `docs/guides/routing.md`.
- **Patches Layrix :**
  - `src/kicad_tools/cli/route_cmd.py` `_write_routed_pcb` — **fix fsync Windows (2026-06-02)**
    → `os.fsync` était appelé sur un handle ouvert en `"rb"` (read-only) → `OSError
    [Errno 9] Bad file descriptor` sur Windows → tout le build/route échoue.
    Fix : write + fsync dans **un seul handle writable** (`open(tmp, "w")`), fsync
    best‑effort (`try/except OSError`). Sans ce fix : `kct build`/`kct route`
    échouent sur Windows (preuve : board 01 du repo échouait 0/1, passe 13/13 après).
    **En Docker (Linux) ce bug n'existe pas** — le patch est inoffensif là-bas.
  - Sortie console routeur — **fix charmap Windows (2026-06-09)**
    → les emojis (`⚠️`, `🔶`, `🔴`, `✓`, `✅`, `❌`) dans les logs du routeur crashaient
    le routage en plein milieu sur Windows (console cp1252) :
    `'charmap' codec can't encode character '⚠'` → attempts interrompus à ~66-77%.
    Fix : remplacés par ASCII (`[!]`, `[#]`, `[X]`, `[ok]`, `[OK]`) dans
    `router/fine_pitch.py`, `router/core.py`, `router/algorithms/two_phase.py`,
    `router/algorithms/monte_carlo.py`, `cli/route_cmd.py`.
    Ceinture : exporter `PYTHONUTF8=1` avant `kct ...` en local Windows
    (PYTHONIOENCODING seul désynchronise parent cp1252 / enfant UTF-8 dans `kct build`).
    **En Docker (Linux, UTF-8) ce bug n'existe pas** — patch inoffensif là-bas.
  - `src/kicad_tools/reasoning/state.py` + `reasoning/interpreter.py` — **fix net
    name-only KiCad 9+ (2026-06-09)**
    → après routage, `kct route` lance `kicad-cli pcb fill-zones` ; **kicad-cli 9/10
    réécrit les nets au format name-only** `(net "+5V")` (sans id numérique).
    Le parser du reasoner faisait `int(atoms[0])` → `kct reason` / PCBReasoningAgent
    crashait : `invalid literal for int() with base 10: '+5V'`.
    Fix : helper `_resolve_net_node()` (state.py) — accepte `(net 1 "GND")`,
    `(net 1)` et `(net "GND")` avec résolution inverse nom→id ; appliqué aux
    parsers pad/segment/via/zone + comparaison défensive dans interpreter.py.
    ⚠️ **Critique pour l'agent reasoner Layrix en prod** : Docker a kicad-cli →
    zone fill systématique ; passage de l'image à KiCad 9/10 = crash garanti
    du `/reason/auto` sur tout PCB avec zones, sans ce patch.
  - `src/kicad_tools/reasoning/interpreter.py` — **fix layer_count 4/6 couches (2026-06-09)**
    → `InterpreterConfig.layer_count = 2` hardcodé : sur un board 4/6 couches
    (nos plans Pro/Pro Max), toute commande `route_net` du reasoner crashait
    (`Layer value not in stack`, le grid ne modélisait que F.Cu/B.Cu).
    Fix : promotion automatique de `layer_count` depuis `PCBState.layers`
    (uniquement vers le haut — une restriction explicite de l'appelant reste honorée).
  - **Limitation connue (non patchée, contournée)** : le routeur A* du reasoner
    rasterise les zones cuivre en obstacles durs → 0 chemin pour les autres nets.
    Contournement : retirer les zones avant `route_net`, les redéfinir après via
    `define_zone` (même ordre que `kct route`). Voir `examples/stm32-validation/`.

> Note : le pad-collapse de l'ancienne version (`optimize_placement_cmd._write_placements_to_pcb`)
> n'existe **plus** dans cette version officielle — on délègue le placement à l'API
> officielle (`PlacementOptimizer` / `kct placement optimize`) au lieu de notre code custom.

## Mise à jour

```bash
# circuit_synth
cd services/kicad/circuit_synth && git pull && pip install -e .

# kicad-tools (ré-appliquer les patches fsync + charmap après pull — voir ci-dessus)
cd services/kicad/kicad-tools && git pull && pip install -e ".[placement,drc,geometry,native]" && kct build-native
```

Puis mettre à jour ce fichier avec la nouvelle version.

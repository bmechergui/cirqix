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

> Note : le pad-collapse de l'ancienne version (`optimize_placement_cmd._write_placements_to_pcb`)
> n'existe **plus** dans cette version officielle — on délègue le placement à l'API
> officielle (`PlacementOptimizer` / `kct placement optimize`) au lieu de notre code custom.

## Mise à jour

```bash
# circuit_synth
cd services/kicad/circuit_synth && git pull && pip install -e .

# kicad-tools (ré-appliquer le patch fsync après pull — voir ci-dessus)
cd services/kicad/kicad-tools && git pull && pip install -e ".[placement,drc,geometry,native]" && kct build-native
```

Puis mettre à jour ce fichier avec la nouvelle version.

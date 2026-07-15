# Dépendances Git — KiCad Service

`circuit_synth` et `kicad-tools` sont des **git submodules** : le dépôt Cirqix
versionne leur gitlink, donc un checkout CI reproduit exactement les sources testées.
Le premier est installé normalement dans l'image ; `kicad-tools` reste éditable pour
le bind-mount de développement.

## circuit_synth

- **Fork public Cirqix :** https://github.com/bmechergui/circuit-synth (`cirqix`)
- **Base upstream :** v0.12.1, commit `f52f491b57ff1b95d9acbcc48d3323f5be8ad96a`
- **SHA Cirqix épinglé :** `302e22db48fde0f9d128ff5d755f36096bb8c8ee`
- **PR des patches :** https://github.com/bmechergui/circuit-synth/pull/1
- **Chemin :** `services/kicad/circuit_synth/`
- **Install Docker :** `pip3 install --no-cache-dir ./circuit_synth`
- **Runtime Docker :** Ubuntu 24.04 Noble + Python 3.12 dans `/opt/venv`
- **Patches Cirqix :**
  - `src/circuit_synth/kicad/sch_gen/circuit_loader.py` — fix pin_identifier vide
    → `_parse_circuit`: exclure `""` et `None` (pas seulement `"~"`) du test de nom de pin.
    Sans ce fix: Device:R et Device:C → pin_identifier="" → find_pin retourne toujours pin 1
    → VCC_5V ET DHT_DATA tous deux au même endroit (pin1) → R1.pin2=unconnected.
    Ligne ~286: `if "name" in pin_data and pin_data["name"] not in ("~", "", None):`
  - `src/circuit_synth/kicad/schematic/geometry_utils.py` — fallback index-based
    → `get_actual_pin_position`: utiliser l'index uniquement si **toutes** les broches
    sont non numérotées. Avec des numéros explicites, une absence retourne `None` afin
    de ne jamais connecter silencieusement la mauvaise broche.
- **Tests fork :** `tests/unit/test_cirqix_empty_pin_name.py` et
  `tests/unit/test_cirqix_pin_index_fallback.py` (3 scénarios).
- **Garde CI Cirqix :** `services/kicad/tests/test_docker_build_context.py` vérifie le
  gitlink public, Python 3.12/v0.12.1 et le caractère bloquant du build Docker.

## kicad-tools (fork privé complet — sous-module)

- **Fork privé :** https://github.com/bmechergui/kicad-tools (`cirqix`)
- **Upstream :** https://github.com/rjwalters/kicad-tools
- **SHA épinglé :** `c2482b8e582fcd8f76c9be414e4dfacd3d50847b`
- **Chemin :** `services/kicad/kicad-tools/` (tiret ; le package Python reste `kicad_tools`).
- **Import Python :** ajouter `kicad-tools/src` au sys.path → `import kicad_tools`.
- **Install Docker :** déplacement vers `/opt/kicad-tools`, puis
  `pip3 install -e "/opt/kicad-tools[placement,drc,geometry,native]"`
  puis `kct build-native --force` (backend C++ A* — 10-100× plus rapide ; non‑fatal).
- **Backend C++ en local Windows (validé 2026-07-04)** — `kct build-native` échoue
  tel quel : son check compilateur ne connaît que `clang++`/`g++` (jamais `cl.exe`),
  et MSVC 2019 est de toute façon trop vieux pour les headers nanobind (C2131
  constexpr — nanobind exige MSVC 2022+/clang 8+/GCC 9+). Recette qui marche :
  1. `winget install LLVM.LLVM` (clang-cl) + `pip install nanobind ninja` ;
  2. depuis un env `vcvars64` (VS 2019 Build Tools OK pour le SDK/STL) :
     `cmake -B <build_court> -S kicad-tools/src/kicad_tools/router/cpp -G Ninja
     -DCMAKE_CXX_COMPILER=clang-cl -DPython_EXECUTABLE=<python>
     -Dnanobind_DIR=$(python -c "import nanobind; print(nanobind.cmake_dir())")`
     puis `cmake --build <build_court> --config Release` ;
     ⚠ `<build_court>` = chemin COURT (ex. `%TEMP%\kct_build`) — MSBuild plante
     en MAX_PATH 260 sur un dossier profond ;
  3. copier `router_cpp.cp313-win_amd64.pyd` dans `kicad-tools/src/kicad_tools/router/` ;
  4. vérifier `kct build-native --check` → « available ».
  **Impact mesuré (board STM32 LQFP-48 de référence)** : sans le `.pyd`, la lib
  retombe EN SILENCE sur l'A* Python pur → 55-73 % routé en 431-600 s (variance
  énorme) ; avec le C++ → **100 % routé en 121 s** au 1er run. Toujours vérifier
  `build-native --check` avant un benchmark de routage.
- **Workflow officiel utilisé par nos agents :**
  - Placement (2 phases) : Phase 1 `PlacementOptimizer(fixed_refs, enable_clustering)`
    (physique locale) → Phase 2 `EvolutionaryPlacementOptimizer.optimize_hybrid()`
    (GA global, cluster-aware, fitness routabilité). API natives, zéro patch.
  - Routage   : `kct route --mfr jlcpcb --auto-layers --auto-fix --seed`
  - Voir `docs/guides/placement-optimization.md` + `docs/guides/routing.md`.
- **Patches Cirqix :**
  - `src/kicad_tools/cli/route_cmd.py` `_write_routed_pcb` — **fix fsync Windows (2026-06-02)**
    → `os.fsync` était appelé sur un handle ouvert en `"rb"` (read-only) → `OSError
    [Errno 9] Bad file descriptor` sur Windows → tout le build/route échoue.
    Fix : write + fsync dans **un seul handle writable** (`open(tmp, "w")`), fsync
    best‑effort (`try/except OSError`). Sans ce fix : `kct build`/`kct route`
    échouent sur Windows (preuve : board 01 du repo échouait 0/1, passe 13/13 après).
    **En Docker (Linux) ce bug n'existe pas** — le patch est inoffensif là-bas.
  - Sortie console routeur — **fix charmap Windows — DÉPLACÉ DANS NOTRE WRAPPER (2026-06-14)**
    → les emojis (`⚠️`, `🔶`, `🔴`, `✓`, `✅`, `❌`) dans les logs du routeur crashaient
    le routage en plein milieu sur Windows (console cp1252) :
    `'charmap' codec can't encode character '⚠'` → attempts interrompus à ~66-77%.
    **Ancienne approche (≤ 2026-06-09)** : remplacer les emojis par ASCII dans ~5
    fichiers `router/*` — fragile, reperdu à chaque update upstream (whack-a-mole).
    **Nouvelle approche (2026-06-14)** : forcer `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`
    dans l'**env du subprocess kct** depuis `tools/kct_route.py` (NOTRE code, tracké).
    L'enfant kct écrit alors en UTF-8 quel que soit le codepage console → plus aucun
    crash, **et le fix survit aux updates** de kicad-tools (plus rien à réappliquer
    dans la lib pour les emojis). **En Docker (Linux, UTF-8) inoffensif.**
  - `src/kicad_tools/reasoning/state.py` + `reasoning/interpreter.py` — **fix net
    name-only KiCad 9+ (2026-06-09)**
    → après routage, `kct route` lance `kicad-cli pcb fill-zones` ; **kicad-cli 9/10
    réécrit les nets au format name-only** `(net "+5V")` (sans id numérique).
    Le parser du reasoner faisait `int(atoms[0])` → `kct reason` / PCBReasoningAgent
    crashait : `invalid literal for int() with base 10: '+5V'`.
    Fix : helper `_resolve_net_node()` (state.py) — accepte `(net 1 "GND")`,
    `(net 1)` et `(net "GND")` avec résolution inverse nom→id ; appliqué aux
    parsers pad/segment/via/zone + comparaison défensive dans interpreter.py.
    ⚠️ **Critique pour l'agent reasoner Cirqix en prod** : Docker a kicad-cli →
    zone fill systématique ; passage de l'image à KiCad 9/10 = crash garanti
    du `/reason/auto` sur tout PCB avec zones, sans ce patch.
  - `src/kicad_tools/reasoning/interpreter.py` — **fix layer_count 4/6 couches (2026-06-09)**
    → `InterpreterConfig.layer_count = 2` hardcodé : sur un board 4/6 couches
    (nos plans Pro/Pro Max), toute commande `route_net` du reasoner crashait
    (`Layer value not in stack`, le grid ne modélisait que F.Cu/B.Cu).
    Fix : promotion automatique de `layer_count` depuis `PCBState.layers`
    (uniquement vers le haut — une restriction explicite de l'appelant reste honorée).
  - `src/kicad_tools/cli/optimize_placement_cmd.py` — **2 patches CMA-ES (réintroduits
    2026-06-18, Phase 3 « Géomètre »)**
    `tools/placement.py::_refine_with_cmaes` appelle `run_optimize_placement(
    seed_method="current")` **après** l'Architecte (hybrid+cluster) — micro-raffine
    (sub-mm/quelques degrés) la position déjà groupée par cluster, plutôt que de
    remplacer le placement. Filet de sécurité : si l'Inspecteur (`PlacementFixer`)
    ne résorbe pas tous les conflits ERROR introduits par le CMA-ES (CLI natif sans
    verrouillage par position), `auto_place` restaure le board pré-CMA-ES — l'invariant
    « 0 ERROR » prime toujours sur le gain d'adjacence. Voir `CLAUDE.md` §placement et
    `docs/notefinal.md` (2026-06-18).
    5 correctifs dans ce fichier (à ré-appliquer après chaque update upstream) :
    1. **Writer 2-pass** `_write_placements_to_pcb` — KiCad 8/9 : `(at ...)` apparaît
       AVANT `fp_text reference` dans le S-expr → writer single-pass ne met jamais à
       jour les positions. Fix : Pass 1 collecte (at_line_idx, ref) par footprint bloc ;
       Pass 2 patch ces lignes. Regex `_FP_RE_OLD` : supprimer `\s` final (absent
       après `.strip()` sur KiCad 8/9 — sinon aucun footprint reconnu).
    2. **Seed "current"** `_generate_seed` — ajoute `seed_method='current'` : encode
       positions Phase 1 comme vecteur initial CMA-ES. `fp.position` est déjà
       board-relative (PCB API soustrait board_origin) → NE PAS soustraire à nouveau.
    3. **Clamping per-dimension** dans `_generate_seed` — CMAwM exige mean[i] ∈
       [lower[i], upper[i]]. Clamp via `placement_bounds` passé depuis
       `run_optimize_placement` (grands footprints J1/U2 ont des bornes > marge fixe).
    4. **Signature étendue** `_generate_seed` — paramètres `pcb_path`, `board_origin`,
       `placement_bounds` ajoutés (kwonly).
    5. **Appel étendu** dans `run_optimize_placement` — passe `pcb_path`, `board_origin`,
       `placement_bounds` à `_generate_seed` pour seed_method="current".
  - **Limitation connue (non patchée, contournée)** : le routeur A* du reasoner
    rasterise les zones cuivre en obstacles durs → 0 chemin pour les autres nets.
    Contournement : retirer les zones avant `route_net`, les redéfinir après via
    `define_zone` (même ordre que `kct route`). Voir `examples/stm32-validation/`.

> Note : le pad-collapse de l'ancienne version (`optimize_placement_cmd._write_placements_to_pcb`)
> n'existe **plus** dans cette version officielle — on délègue le placement à l'API
> officielle (`PlacementOptimizer` / `kct placement optimize`) au lieu de notre code custom.

## Mise à jour

```bash
# circuit_synth — ne mettre à jour le gitlink qu'après revue et tests du fork
git -C services/kicad/circuit_synth fetch origin cirqix
git -C services/kicad/circuit_synth checkout <sha-revu>
git add services/kicad/circuit_synth

# kicad-tools — procédure complète : docs/kicad-tools-fork-strategy.md §7.
# Dans le fork privé, rebaser `cirqix`, résoudre les patches, tester, revoir et pousser :
git -C services/kicad/kicad-tools fetch upstream
git -C services/kicad/kicad-tools checkout cirqix
git -C services/kicad/kicad-tools rebase upstream/main
# exécuter la suite de tests du fork et `kct build-native --check`, puis double revue
git -C services/kicad/kicad-tools push origin cirqix --force-with-lease
# Dans Cirqix, seulement après le push validé, épingler le nouveau SHA :
git -C services/kicad/kicad-tools fetch origin cirqix
git -C services/kicad/kicad-tools checkout <sha-revu-et-pousse>
git add services/kicad/kicad-tools
#
# Inventaire des 8 patches DÉJÀ suivis dans le fork — ne pas les ré-appliquer
# manuellement dans le checkout du dépôt parent :
#   1. fsync Windows           (cli/route_cmd.py _write_routed_pcb)
#   2. reasoning name-only     (reasoning/state.py helper _resolve_net_node + 4 sites)
#   3. layer_count 4/6c        (reasoning/interpreter.py promotion depuis PCBState.layers)
#   4. CMA-ES writer 2-pass    (cli/optimize_placement_cmd.py _write_placements_to_pcb)
#   5. CMA-ES seed="current"   (cli/optimize_placement_cmd.py _generate_seed + appel)
#   6. Angles pads ABSOLUS     (backport upstream #3903/cd936c1, 2026-07-05 —
#      schema/pcb.py : champ Pad.rotation + parse + writer add_footprint_from_file ;
#      router/io.py : total_rot = pad_rot (2 sites) ; validate/rules/clearance.py :
#      total_rotation = pad.rotation. + 2 EXTENSIONS Cirqix que l'upstream n'a pas :
#      (a) setter Footprint.rotation replie le DELTA dans chaque pad (chemin
#      placement/GA), (b) writer texte CMA-ES _write_placements_to_pcb replie le
#      delta par ligne de pad (gère pads inline ET multi-lignes). Sans ces
#      extensions le pipeline placement désynchronise les angles.)
#   7. KCT_SAFE_OPTIMIZE=1     (router/optimizer/config.py __post_init__ — gate
#      opt-in qui neutralise les passes d'optimisation déplaçant la géométrie ;
#      mesuré NON responsable des courts, conservé comme outil de diagnostic.)
#   8. SIGNE ROTATION PADS     (router/io.py, 3 sites pad_x*cos_r… — LE fix
#      critique 2026-07-06 : le repère fichier KiCad a Y vers le BAS → rotation
#      des offsets locaux avec l'angle NÉGUÉ. L'ancienne matrice standard
#      inversait les pads de tout footprint ±90° → pistes terminées au centre
#      du pad voisin = 25-32 shorting_items au DRC officiel, invisibles au DRC
#      interne (modèle auto-cohérent). Mesure après fix : courts 32 → 0-6,
#      P3V3 8/15 → 14/15 pads. Garde : tests/test_pad_rotation_convention.py.
#      À REMONTER UPSTREAM (avec le #6/(a)(b)) — cause plausible de l'issue
#      upstream #3803 « kct PASS vs kicad-cli 400+ violations ».)
#   (ex-patch « marge couloir same-component » grid.py testé le 2026-07-05 puis
#    RETIRÉ — épiphénomène du #8, aucun effet mesuré sur les courts.)
# Le patch charmap n'est PLUS dans la lib (déplacé dans tools/kct_route.py — durable).
#
# RECETTE ROUTAGE PRO validée 2026-07-06 (board STM32 LQFP-48 de référence) :
#   placement auto_place (angles cohérents grâce au patch 6) →
#   kct route --strategy negotiated --auto-layers --min-completion 1.0
#     --auto-fix --clearance 0.2 --seed 42 (backend C++ obligatoire) →
#   rescue placement-feedback (déplacements ciblés, ex. R1/D1 hors couloir) →
#   kicad-cli pcb drc = JUGE (jamais le DRC interne seul).
#   Mesuré : 91% routé, 0 shorting_items, 0 copper_edge_clearance ;
#   reliquat = clearances pads NC (sans net, électriquement inoffensives,
#   carve-out #3490 assumé par la lib) + 4 pads GND LQFP à coudre (kct stitch
#   à ajuster : vias hors specs board avec --mfr jlcpcb) + 2 micro-gaps P3V3.
#   clearance 0.15 = plus de complétion mais courts/edge ; 0.25 = propre mais 64%.
# Phase 3 (Géomètre) = CMA-ES micro-raffinement via run_optimize_placement(seed_method="current")
# chaîné après l'Architecte (hybrid+cluster), depuis 2026-06-18 — avec filet de sécurité
# (revert si conflits ERROR non résorbés par l'Inspecteur). Voir tools/placement.py::_refine_with_cmaes.
# Validation locale à effectuer dans le fork avant le push :
cd services/kicad/kicad-tools && pip install -e ".[placement,drc,geometry,native]" && kct build-native
```

Consigner ici le SHA validé après la mise à jour du gitlink.

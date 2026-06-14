# Exemple de référence — Pipeline COMPLET 8 agents (JSON → Gerbers)

> Cas d'étude exécuté le 2026-06-11 sur Windows (local, sans Docker, sans clé API) :
> **les 8 étapes du pipeline prod** sur le devboard STM32 (mêmes 17 composants /
> 12 nets que `../stm32-validation`), en partant d'un simple JSON de circuit.
> 2 bugs prod trouvés pendant cette validation (voir Leçons).

**La question à laquelle ce cas répond :** « les 8 agents transforment-ils une
description logique en Gerbers ? » — là où `../stm32-validation` ne teste que
placement→routage→sauvetage sur un board déjà généré.

## Workflow

```bash
cd services/kicad/examples/stm32-full-pipeline
export PYTHONUTF8=1
export PATH="$PATH:/c/Program Files/KiCad/<ver>/bin"
export KICAD_SYMBOL_DIR="C:\Program Files\KiCad\<ver>\share\kicad\symbols"
export KICAD_FOOTPRINT_DIR="C:\Program Files\KiCad\<ver>\share\kicad\footprints"

# Étapes ①→⑥ (s'arrête sur l'analyse d'échec si le routage < 100 %)
python run_full_pipeline.py input/circuit_full.json output

# Le driver LLM (rôle 2) lit output/5_routing_analysis.txt,
# écrit decisions.json (déplacements), puis ⑥b→⑧ :
python run_full_pipeline.py input/circuit_full.json output --rescue output/decisions.json
```

Chaque étape appelle la **fonction de production** (celle des endpoints FastAPI)
et sauvegarde son artefact numéroté `1_schema.kicad_sch` … `8_export/gerbers.zip`.

## Les 2 rôles du driver LLM (pattern « moi = le LLM », sans clé API)

| Rôle | Quand | Artefact | Équivalent prod |
|------|-------|----------|-----------------|
| 1 — concepteur | AVANT le run | `input/circuit_full.json` | Haiku dans `call_agent_schema` |
| 2 — sauveteur | si routage < 100 % | `decisions.json` (output/, jetable) | Haiku dans `/reason/auto` (agent ⑥b) |

## Résultats du run de référence (2026-06-11)

| Étape | Résultat |
|-------|----------|
| ① schéma | 17 composants, 12 nets — circuit_synth timeout 20 s → fallback kicad-tools |
| ② ERC | **clean, 0 violation** (kicad-cli) |
| ③ gen PCB | 56 Ko, footprints réels |
| ④ placement | 17 composants — ⚠ J1 ancré HORS carte, bypass sous le MCU (voir Leçons) |
| ⑤ routage | 22 % |
| ⑥b sauvetage | 7 déplacements du driver (J1 rapatrié, caps désempilées) → **33 %** conservés |
| ⑦ DRC | clean |
| ⑧ export | **24 fichiers, gerbers.zip, devis $17** |

Le pipeline est **structurellement validé** (8/8 étapes produisent leurs
artefacts). La qualité du routage est limitée par un netlist PCB fragmenté
(83 nets au lieu de 12, voir Leçon #4) — **pas par le placement de l'étape
④**, qui est corrigé (voir run de validation 2026-06-13 ci-dessous).

## Run de validation (2026-06-13) — fix placement `_clamp_fixed_refs_to_outline`

Re-jeu des étapes ①③④⑤ (script inline, sans ERC/DRC/export) avec le fix
`_clamp_fixed_refs_to_outline()` (commit d849774) pour valider que J1 reste
dans le contour Edge.Cuts dès le placement :

| Étape | Résultat |
|-------|----------|
| ④ placement | **J1 corrigé** : généré hors-carte à (35.0, 50.0) sur un board 60×40mm → clampé à (35.0, 38.0), dans `[0,60]×[0,40]` (marge 2mm). Fix `_clamp_fixed_refs_to_outline` **CONFIRMÉ** ✅ |
| ⑤ routage | **0 %** — `Routed: 0/1 nets (0%)`. Cause : **pas le placement** — voir Leçon #4 (netlist niveau 1 cassé) |

Le fix placement (Leçon #2) fonctionne : J1 ne sort plus du contour. Le 0 %
de ce run n'est **pas comparable** au 22 % du run de référence 2026-06-11 —
les deux runs régénèrent le schéma (étape ①, fallback kicad-tools sans seed
fixe), avec un placement de labels différent à chaque fois, ce qui fait
varier la sévérité du bug de Leçon #4 (22 % vs 0 %) ; la **cause racine est
la même** dans les deux cas.

## Leçons (bugs prod trouvés par ce cas)

1. **`Schematic()` sans `title` → voie ② morte** — depuis le vendoring du dépôt
   officiel kicad-tools (2026-06-03), `Schematic.__init__` exige `title` ;
   `_generate_with_kicad_tools` (tools/schematic.py) crashait en TypeError →
   le fallback kicad-tools de `/schematic/generate` était silencieusement mort
   en prod. **Corrigé** + tests `tests/test_schematic_fallback.py`.
2. **`auto_place` ancre les connecteurs sans vérifier le contour** — la
   génération a posé J1 à y=135 (hors carte 60×40) et l'optimiseur l'a ancré
   là (`fixed_refs=J*`) → SWDIO/SWO physiquement inroutables. Le filet
   `place_unplaced` ne couvre que les composants très loin (-1000). **Corrigé**
   : `_clamp_fixed_refs_to_outline()` ramène les `fixed_refs` dans le contour
   Edge.Cuts avant `PlacementOptimizer.from_pcb()` + tests `tests/test_placement.py`.
   **Confirmé** par le run de validation 2026-06-13 : J1 (35,50) hors-carte
   → clampé (35,38), dans `[0,60]×[0,40]`.
3. circuit_synth **timeout 20 s** sur 17 composants en local — la cascade joue
   son rôle (fallback), mais budget à surveiller en Docker.
4. **Netlist niveau 1 cassé → fallback kicad-cli fragmente le netlist (83
   nets au lieu de 12) → routage structurellement bloqué** — `_generate_with_kicad_tools`
   (tools/pcb.py:415) importe `kicad_tools.workflow._netlist.build_netlist_from_schematic`,
   module **inexistant** dans le dépôt officiel vendoré (2026-06-03) →
   `ModuleNotFoundError` systématique → fallback niveau 2 (kicad-cli
   `export_netlist`), qui ne résout pas les hierarchical labels du schéma
   régénéré par le fallback kicad-tools de l'étape ① (labels pas aux pins
   exacts — cf. commentaire tools/pcb.py:376-379). Résultat : chaque pad sur
   son propre net `unconnected-(REF-PadN)` (83 nets pour 12 attendus). `kct
   route` ne voit alors **qu'1 net** à router (`Net-(U2-VSS-Pad23)`, 3 pads
   GND du MCU) → `Routed: 0/1 (0%)`. **Non corrigé** — piste : remplacer
   l'import niveau 1 par `Schematic.load(sch_path).extract_netlist()`, déjà
   utilisé avec succès dans `_generate_with_pcbnew` (tools/pcb.py:498-508).

## Gestion des fichiers

- `input/` — **committé** : la définition du cas (le JSON du driver LLM).
- `output/` — **jetable, gitignoré** : tous les artefacts d'un run, y compris
  `decisions.json` (chaque run peut donner une analyse différente).
- `expected/` — à promouvoir depuis `output/` quand un run atteint la qualité
  cible (board final + rendu) ; pas encore créé pour ce cas — bloqué par
  Leçon #4 (netlist fragmenté → routage 0-33 % selon le run).

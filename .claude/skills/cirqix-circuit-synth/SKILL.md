---
name: cirqix-circuit-synth
description: >
  Génération de schémas KiCad par circuit_synth dans le service Cirqix : création ou modification de
  composants, nets et symboles, correspondance valeur → symbole KiCad, noms de broches, erreurs de
  génération. Utiliser avant de modifier services/kicad/tools/schematic.py ou
  services/kicad/routers/schematic.py (/schematic/generate, /schematic/validate-symbols), ou quand
  une génération circuit_synth échoue.
version: 1.0.0
---

# Cirqix — Circuit-Synth : génération de schematics KiCad en Python

## Vue d'ensemble

Circuit-synth est la bibliothèque Python qui génère des fichiers `.kicad_sch` et `.kicad_pcb`
**natifs** à partir de code Python déclaratif. Elle est utilisée comme moteur primaire de
génération de schématiques dans `services/kicad/tools/schematic.py` (route `POST /schematic/generate`).

**Flux :** Haiku génère JSON schema → FastAPI router → circuit_synth Python → `.kicad_sch`
→ Supabase Storage → KiCanvas viewer.

---

## 1. Environnement

- circuit_synth vient du sous-module épinglé `services/kicad/circuit_synth/` (`pip install ./circuit_synth` dans l'image, `pip install -e services/kicad/circuit_synth` en local) ; ne jamais l'installer depuis PyPI, qui n'a pas les correctifs Cirqix (`services/kicad/DEPENDENCIES.md`).
- `KICAD_SYMBOL_DIR` pointe vers les symboles de la version de KiCad installée (`/usr/share/kicad/symbols` dans l'image ; recherche locale dans `services/kicad/tests/conftest.py`).
- `PYTHONUTF8=1` avant d'importer circuit_synth, déjà posé en tête de `services/kicad/tools/schematic.py` : ses journaux contiennent des emojis que la console Windows ne sait pas encoder.

---

## 2. Pattern `@circuit` — règle ABSOLUE

Tous les `Net()` et `Component()` **DOIVENT** être créés à l'intérieur de la fonction décorée.
Jamais dans `main()` ou en dehors du contexte actif.

```python
from circuit_synth import circuit, Component, Net

# CORRECT ✓
@circuit(name="NE555_Blinker_1Hz")
def ne555_blinker():
    vcc = Net("VCC")          # Net INSIDE la fonction
    gnd = Net("GND")
    r1 = Component(           # Component INSIDE la fonction
        symbol="Device:R",
        ref="R",
        value="4.7k",
        footprint="Resistor_SMD:R_0603_1608Metric",
    )
    r1[1] += vcc
    r1[2] += gnd

circ = ne555_blinker()        # appel sans arguments

# INTERDIT ✗ — provoque CircuitSynthError: No active circuit found
vcc = Net("VCC")              # Net en dehors du contexte = crash
```

---

## 3. Correspondance valeur → symbole

La table fait foi dans `services/kicad/tools/schematic.py` : `_SYMBOL_RULES` (ordre = priorité, première correspondance) et `_SYMBOL_FALLBACKS` (repli par bibliothèque). La lire plutôt que la recopier.

### Vérifier que le symbol existe

```bash
grep -oP '\(symbol "\K[^"]+' "$KICAD_SYMBOL_DIR/Device.kicad_sym" \
  | grep -v '_[0-9]_[0-9]$' | sort | head -30
```

---

## 4. Noms de broches

Les bibliothèques KiCad ne nomment pas les broches comme les datasheets. Le nom fait foi dans le `.kicad_sym` de `KICAD_SYMBOL_DIR`, ou dans la liste `Available:` de l'erreur `ComponentError` de circuit_synth. En cas de doute, brancher par numéro (`u1[4]`).

Exemple, `Timer:NE555P` en KiCad 10 : 1 `GND`, 2 `TRIG`, 3 `OUT`, 4 `~{RST}`, 5 `CONT`, 6 `THRES`, 7 `DISCH`, 8 `VCC`. Les abréviations de datasheet (TR, Q, R, CV, THR, DIS) n'existent pas dans la bibliothèque : `_resolve_pin` (`services/kicad/tools/schematic.py`) les traduit par `_ALIAS_BROCHES`, puis par un préfixe qui ne désigne qu'une seule broche, jamais par sous-chaîne, car « R », contenu dans « THRES », branchait VCC sur la broche seuil (`services/kicad/tests/test_broches_par_nom.py`). Une abréviation nouvelle s'ajoute à `_ALIAS_BROCHES`, avec son test.

---

## 5. Références

`Component(ref="C12")` garde `C12` ; `Component(ref="C")` laisse circuit_synth renuméroter dans son ordre de création. Le service passe toujours la référence complète du JSON (`_generate_with_cs_lib`, `services/kicad/tools/schematic.py`) : avec un préfixe, le board et le BOM portaient C1..C8 là où le schéma déclarait C1, C2, C3, C10…, et le résultat dépendait de la course avec le repli kicad-tools. Les broches se branchent par `_resolve_pin` (§4), pas par `comp[pin] += net` direct.

---

## 6. Génération du projet KiCad

```python
# Générer avec circuit_synth
circ = ne555_blinker()

# generate_kicad_project(path, force_regenerate=True, generate_pcb=False)
# - path : chemin SANS extension — circuit_synth ajoute /<project_name>/
# - force_regenerate : True pour écraser un projet existant
# - generate_pcb : False pour schéma seul (PCB généré séparément via router)
result = circ.generate_kicad_project(
    str(output_dir / project_name),
    force_regenerate=True,
    generate_pcb=False,
)

# Lire le fichier généré
sch_files = list(output_dir.rglob("*.kicad_sch"))
sch_content = sch_files[0].read_text(encoding="utf-8") if sch_files else None
```

> **Attention :** le nom du dossier créé = `name` passé au `@circuit`, pas `project_name`.
> Ex: `@circuit(name="NE555_Blinker_1Hz")` + `path="output/ne555_blinker"` → génère
> `output/ne555_blinker/NE555_Blinker_1Hz.kicad_sch`.

---

## 7. Chemins de génération

Routeur : `services/kicad/routers/schematic.py` (`POST /schematic/generate`). Logique : `services/kicad/tools/schematic.py`. Ordre : circuit_synth → kicad-tools Schematic → S-expression TypeScript en dernier recours. Le PCB est produit à part par `POST /pcb/generate` (`services/kicad/tools/pcb.py`, kicad-tools `PCBFromSchematic`).

---

## 8. Erreurs classiques et corrections

| Erreur | Cause | Fix |
|--------|-------|-----|
| `LibraryNotFound: Library 'Device' not found` | `KICAD_SYMBOL_DIR` non défini ou mauvais chemin | Définir `KICAD_SYMBOL_DIR` pointant vers dossier avec `.kicad_sym` |
| `SymbolNotFoundError: Symbol 'IC' not found in library 'Device'` | Symbole générique absent de la bibliothèque installée | Symbole réel (`Timer:NE555P`…) ajouté à `_SYMBOL_RULES` (§3) |
| `ComponentError: Pin 'RST' not found in U (Timer:NE555P)` | Nom de datasheet absent de la bibliothèque | Nom KiCad (`~{RST}`), numéro de broche, ou alias dans `_ALIAS_BROCHES` (§4) |
| `CircuitSynthError: No active circuit found` | `Net()` ou `Component()` créé hors du contexte `@circuit` | Tout mettre INSIDE la fonction décorée |
| `'charmap' codec can't encode character '\U0001f50d'` | circuit_synth utilise des emojis dans ses logs, incompatible Windows | `PYTHONUTF8=1` ou `os.environ["PYTHONUTF8"] = "1"` avant import |
| `Circuit.generate_json_netlist() missing 1 required positional argument: 'filename'` | API mal appelée | Ignorer — la méthode JSON n'est pas nécessaire pour le workflow principal |
| Fichier `.kicad_sch` absent après génération | Unicode crash pendant la génération (log emoji) | Vérifier `PYTHONUTF8=1`, réessayer avec `2>&1 \| grep ERROR` |
| KiCanvas affiche fond cyan sans contenu | Blob URL sans extension `.kicad_sch` | Servir depuis fichier statique avec extension correcte |

---

## 9. Tester

Tests dans `services/kicad/tests/` (`test_*.py`), jamais à la racine du service.

---

## 10. Ajouter un composant

1. Vérifier le symbole et ses broches dans la bibliothèque KiCad installée (`KICAD_SYMBOL_DIR`).
2. Ajouter la règle à `_SYMBOL_RULES` dans `services/kicad/tools/schematic.py` (ordre = priorité).
3. Ajouter un test dans `services/kicad/tests/`.

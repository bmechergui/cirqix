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
grep -oP '\(symbol "\K[^"]+' kicad-symbols/Device.kicad_sym \
  | grep -v '_[0-9]_[0-9]$' | sort | head -30
```

---

## 4. Noms de pins — pièges courants

Les noms de pins KiCad **diffèrent** des noms "logiques" que l'on utilise habituellement.
Toujours vérifier avec `comp.available_pins` ou depuis `.kicad_sym`.

### NE555P (Timer:NE555P)

| Pin logique | Nom circuit_synth | N° pin |
|------------|------------------|--------|
| GND        | `GND`            | 1      |
| TRIG       | `TR`             | 2      |
| OUT        | `Q`              | 3      |
| RST        | `R`              | 4      |
| CV         | `CV`             | 5      |
| THR        | `THR`            | 6      |
| DIS        | `DIS`            | 7      |
| VCC        | `VCC`            | 8      |

> `TRIG` → `TR`, `OUT` → `Q`, `RST` → `R` — les trois pièges classiques NE555.

### Lire les pins disponibles depuis l'erreur

Quand un pin n'existe pas, circuit_synth affiche les pins valides :
```
ComponentError: Pin 'RST' not found in U (Timer:NE555P).
Available: 'CV', 'DIS', 'GND', 'Q', 'R', 'THR', 'TR', 'VCC', 1, 2, 3, 4, 5, 6, 7, 8
```
→ Utiliser les noms entre guillemets (ex: `u1["R"]`) ou les numéros de pin (ex: `u1[4]`).

---

## 5. Gestion des `ref` : préfixe vs ref complète

Circuit_synth accepte deux modes :

```python
# Mode préfixe — auto-numérotation R1, R2, R3...
r1 = Component(ref="R", ...)   # → numéroté R1 automatiquement
r2 = Component(ref="R", ...)   # → numéroté R2 automatiquement

# Mode ref complète (trailing digits détectés)
r1 = Component(ref="R1", ...)  # → utilisé tel quel
r2 = Component(ref="R2", ...)  # → utilisé tel quel
```

**Pour le router FastAPI** (JSON avec refs numérotées comme "R1", "U1") :
→ Utiliser le **mode préfixe** (strip des chiffres) + dict `json_ref → Component` :

```python
comps: dict[str, CSComponent] = {}
for comp in req.components:
    ref_prefix = comp.ref.rstrip("0123456789") or comp.ref
    c = CSComponent(symbol=..., ref=ref_prefix, value=comp.value, footprint=comp.footprint)
    comps[comp.ref] = c   # clé = "R1", objet = Component avec prefix "R"

# Connexions avec les refs JSON originales
for conn in req.connections:
    net = nets[conn.name]
    for pin in conn.pins:
        comp_obj = comps.get(pin.ref)   # lookup par "R1", "U1", etc.
        if comp_obj:
            comp_obj[pin.pin] += net
```

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
| `LibraryNotFound: Library 'Device' not found` | Fichier téléchargé depuis `master` (→ 404 car HEAD = `.kicad_symdir`) | Utiliser tag `7.0.11` : `/-/raw/7.0.11/Device.kicad_sym` |
| `SymbolNotFoundError: Symbol 'IC' not found in library 'Device'` | `Device:IC` n'existe pas dans KiCad 7 | Utiliser `Timer:NE555P` pour NE555, `Device:R` etc. |
| `ComponentError: Pin 'RST' not found in U (Timer:NE555P)` | Noms pins différents du schéma logique | Voir table pins §4 : `RST`→`R`, `TRIG`→`TR`, `OUT`→`Q` |
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

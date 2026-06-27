---
name: cirqix-circuit-synth
description: >
  Use this skill whenever the user mentions "circuit-synth", "générer un schéma KiCad",
  "netlist Python", "schéma KiCad depuis JSON", "@circuit decorator", "Device:R", "Timer:NE555P",
  "KICAD_SYMBOL_DIR", "kicad_sch depuis Python", "mapping symbol", "router /circuit-synth/generate",
  or asks to "générer un circuit", "créer un schéma", "définir des composants et nets en Python".
  Also invoke when the user modifies services/kicad/routers/circuit_synth.py or
  services/kicad/test_ne555_circuit_synth.py, or when circuit-synth generation fails.
  This skill encodes all production experience from integrating the circuit-synth Python library
  into the Cirqix KiCad microservice — use it proactively before writing any circuit-synth code.
version: 1.0.0
---

# Cirqix — Circuit-Synth : génération de schematics KiCad en Python

## Vue d'ensemble

Circuit-synth est la bibliothèque Python qui génère des fichiers `.kicad_sch` et `.kicad_pcb`
**natifs** à partir de code Python déclaratif. Elle est utilisée comme moteur primaire de
génération de schématiques dans `services/kicad/routers/circuit_synth.py`.

**Flux :** Haiku génère JSON schema → FastAPI router → circuit_synth Python → `.kicad_sch`
→ Supabase Storage → KiCanvas viewer.

---

## 1. Setup requis

### Variables d'environnement (obligatoires)

```bash
# services/kicad/.env
KICAD_SYMBOL_DIR=services/kicad/kicad-symbols   # chemin absolu en prod
PYTHONUTF8=1                                     # CRITIQUE sur Windows — évite erreur charmap emoji
```

Le code doit setter `PYTHONUTF8=1` **avant** d'importer circuit_synth :

```python
import os
os.environ.setdefault("PYTHONUTF8", "1")   # en haut du fichier, avant tout import circuit_synth
```

### Bibliothèques KiCad requises

Télécharger depuis GitLab tag `7.0.11` (`.kicad_sym` format KiCad 7) :

```bash
for lib in Device Timer Connector_Generic power Analog; do
  curl -L -o "services/kicad/kicad-symbols/${lib}.kicad_sym" \
    "https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/7.0.11/${lib}.kicad_sym"
done
```

> **Attention :** `HEAD` du repo kicad-symbols utilise `.kicad_symdir` (KiCad 8/9 format) — inutilisable.
> Toujours cibler le tag `7.0.11` pour `.kicad_sym`.
> URL GitLab raw : `/-/raw/7.0.11/` (pas `/raw/master/` qui retourne 404).

### Installation Python

```bash
cd services/kicad
.venv/Scripts/pip install circuit-synth   # Windows
# ou
pip install circuit-synth
```

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

## 3. Mapping symbol KiCad

### Règle de mapping (par priorité)

| Valeur (value) contient | Footprint contient | Symbol KiCad |
|------------------------|-------------------|--------------|
| NE555, LM555, NA555, SA555, TLC555, ICM7555 | — | `Timer:NE555P` |
| LM7805 / L7805 | — | `Regulator_Linear:L7805` |
| LM7812 | — | `Regulator_Linear:L7812` |
| LM317 | — | `Regulator_Linear:LM317_TO-220` |
| LM1117 (3.3V) | — | `Regulator_Linear:LM1117T-3.3` |
| LM1117 (5V) | — | `Regulator_Linear:LM1117T-5.0` |
| LM358 | — | `Amplifier_Operational:LM358` |
| BC547 / BC337 | — | `Transistor_BJT:BC547` |
| BC557 | — | `Transistor_BJT:BC557` |
| 2N3904 | — | `Transistor_BJT:2N3904` |
| 1N4148 | — | `Diode:1N4148` |
| 1N4007 | — | `Diode:1N4007` |
| — | CONN_01X01 | `Connector_Generic:Conn_01x01` |
| — | CONN_01X02, PINHEADER_1X02 | `Connector_Generic:Conn_01x02` |
| — | CONN_01X03, PINHEADER_1X03 | `Connector_Generic:Conn_01x03` |
| LED | — | `Device:LED` |
| — | LED_THT, LED_SMD | `Device:LED` |
| 1N4148, 1N4001 | — | `Device:D` |
| BC547, 2N3904 | — | `Device:Q_NPN_BCE` |
| BC557, 2N3906 | — | `Device:Q_PNP_BCE` |
| — | C_POLARIZED, CP_, CPOL | `Device:C_Polarized` |
| — | C_0402, C_0603, C_0805, C_1206 | `Device:C` |
| — | R_0402, R_0603, R_0805, R_1206, R_AXIAL | `Device:R` |

Fallback universel : `Device:R`

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

## 7. Router FastAPI — pattern primary/fallback

**Fichier :** `services/kicad/routers/circuit_synth.py`

```python
import os
os.environ.setdefault("PYTHONUTF8", "1")

def _circuit_synth_available() -> bool:
    """Vérifie si circuit_synth ET KICAD_SYMBOL_DIR sont disponibles."""
    if not os.environ.get("KICAD_SYMBOL_DIR"):
        return False
    try:
        import circuit_synth  # noqa
        return True
    except ImportError:
        return False

@router.post("/generate")
def generate(req: CircuitSynthRequest):
    sch_content = None

    # Chemin primaire : circuit_synth (schémas avec vrais corps de composants)
    if _circuit_synth_available():
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                sch_content, _ = _generate_with_circuit_synth(req, Path(tmp_dir))
        except Exception as e:
            logger.warning(f"circuit_synth failed, fallback: {e}")
            sch_content = None

    # Fallback : S-expression hand-written (pas de corps composant, mais toujours valide KiCad)
    if not sch_content:
        sch_content = _generate_schematic_fallback(req.components, req.connections)

    # PCB toujours via S-expression (circuit_synth PCB non activé)
    pcb_content = _generate_pcb_sexpr(req.components, req.connections,
                                       req.board_width_mm, req.board_height_mm)
    ...
```

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

## 9. Test standalone sans API Anthropic

```bash
# Fichier : services/kicad/test_ne555_circuit_synth.py
cd services/kicad
KICAD_SYMBOL_DIR="$(pwd)/kicad-symbols" PYTHONUTF8=1 .venv/Scripts/python test_ne555_circuit_synth.py

# Résultat attendu :
# [OK]  circuit-synth importe
# [OK]  Circuit instancie: 9 composants
# [OK]  Projet genere dans: services/kicad/output_ne555
#       ne555_blinker/NE555_Blinker_1Hz.kicad_sch  (48,454 bytes)
# [F]   Copie -> apps/web/public/test-cs-ne555.kicad_sch
# [W]   Ouvre: http://localhost:3333/test-cs.html
```

La page `test-cs.html` utilise KiCanvas pour rendre le schéma — doit montrer le NE555P
avec corps du composant (boîte avec 8 pins étiquetées), résistances, condensateurs, LED.

---

## 10. Checklist ajout d'un nouveau composant

1. Identifier la librairie KiCad : `Timer`, `Device`, `Connector_Generic`, `Analog`, etc.
2. Télécharger la lib si absente : `curl .../kicad-symbols/-/raw/7.0.11/<LibName>.kicad_sym`
3. Vérifier le symbol exact : `grep -oP '\(symbol "\K[^"]+' <lib>.kicad_sym | grep -v '_[0-9]'`
4. Vérifier les noms de pins : `grep -A5 '"<SymbolName>"' <lib>.kicad_sym | grep 'pin'`
5. Ajouter à `_SYMBOL_RULES` dans le router si besoin de mapping automatique
6. Tester dans `test_ne555_circuit_synth.py` ou un script Python dédié

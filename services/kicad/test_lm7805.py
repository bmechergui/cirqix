import os, sys, shutil
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("KICAD_SYMBOL_DIR", os.path.join(os.path.dirname(__file__), "kicad-symbols"))

from pathlib import Path
from circuit_synth import circuit, Component, Net

@circuit(name="LM7805_Regulator_5V")
def lm7805_reg():
    vin  = Net("VIN")
    vout = Net("VOUT")
    gnd  = Net("GND")

    # LM7805 régulateur 5V
    u1 = Component(symbol="Regulator_Linear:L7805", ref="U", value="LM7805",
                   footprint="Package_TO_SOT_THT:TO-220-3_Vertical")
    u1[1] += vin   # IN
    u1[2] += gnd   # GND
    u1[3] += vout  # OUT

    # Condensateurs entrée
    c1 = Component(symbol="Device:C", ref="C", value="330nF",
                   footprint="Capacitor_SMD:C_0603_1608Metric")
    c1[1] += vin
    c1[2] += gnd

    c2 = Component(symbol="Device:C", ref="C", value="100nF",
                   footprint="Capacitor_SMD:C_0603_1608Metric")
    c2[1] += vin
    c2[2] += gnd

    # Condensateurs sortie
    c3 = Component(symbol="Device:C", ref="C", value="100nF",
                   footprint="Capacitor_SMD:C_0603_1608Metric")
    c3[1] += vout
    c3[2] += gnd

    # Connecteur entrée (barrel jack 2 broches)
    j1 = Component(symbol="Connector_Generic:Conn_01x02", ref="J", value="VIN_CONN",
                   footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
    j1[1] += vin
    j1[2] += gnd

    # Connecteur sortie 5V
    j2 = Component(symbol="Connector_Generic:Conn_01x02", ref="J", value="VOUT_5V",
                   footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
    j2[1] += vout
    j2[2] += gnd

circ = lm7805_reg()

out_dir = Path(__file__).parent / "output_lm7805"
out_dir.mkdir(exist_ok=True)
circ.generate_kicad_project(str(out_dir / "lm7805_reg"), force_regenerate=True, generate_pcb=False)

# Trouver le .kicad_sch généré
sch_files = list(out_dir.rglob("*.kicad_sch"))
if not sch_files:
    print("[FAIL] Aucun .kicad_sch généré")
    sys.exit(1)

sch_path = sch_files[0]
print(f"[OK]  Généré: {sch_path} ({sch_path.stat().st_size:,} bytes)")

# Copier vers le dossier public web pour KiCanvas
dest = Path(__file__).parent.parent.parent / "apps/web/public/test-lm7805.kicad_sch"
shutil.copy(sch_path, dest)
print(f"[OK]  Copié  → {dest}")
print(f"[->] Ouvre  : http://localhost:3333/test-cs.html?file=/test-lm7805.kicad_sch")

"""
Test circuit-synth library — NE555 1Hz blinker
Genere .kicad_sch + .kicad_pcb sans API Anthropic, sans KiCad installe.

Usage:
    .venv/Scripts/python test_ne555_circuit_synth.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Point circuit_synth at the repo-local KiCad symbol libraries before importing it.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault(
    "KICAD_SYMBOL_DIR",
    os.path.join(os.path.dirname(__file__), "kicad-symbols"),
)

try:
    from circuit_synth import circuit, Component, Net
    print("[OK]  circuit-synth importe")
except ImportError as e:
    print(f"[ERR]  Import echoue: {e}")
    sys.exit(1)

OUT_DIR = Path(__file__).parent / "output_ne555"

# ---------------------------------------------------------------------------
# NE555 1Hz blinker — tout dans la fonction decoree (contexte actif)
# ---------------------------------------------------------------------------

@circuit(name="NE555_Blinker_1Hz")
def ne555_blinker():
    """Astable NE555 — f ~1 Hz, duty cycle ~59%"""

    # Nets
    vcc     = Net("VCC")
    gnd     = Net("GND")
    thr_dis = Net("THR_DIS")
    cv      = Net("CV")
    out     = Net("OUT")

    # IC principal — NE555P timer (8 pins: GND,TRIG,OUT,RST,CV,THR,DIS,VCC)
    u1 = Component(
        symbol="Timer:NE555P",
        ref="U",
        value="NE555P",
        footprint="Package_DIP:DIP-8_W7.62mm",
    )

    # Resistances timing
    r1 = Component(symbol="Device:R", ref="R", value="4.7k",
                   footprint="Resistor_SMD:R_0603_1608Metric")
    r2 = Component(symbol="Device:R", ref="R", value="68k",
                   footprint="Resistor_SMD:R_0603_1608Metric")
    r3 = Component(symbol="Device:R", ref="R", value="330R",
                   footprint="Resistor_SMD:R_0603_1608Metric")

    # Condensateurs
    c1 = Component(symbol="Device:C", ref="C", value="10uF",
                   footprint="Capacitor_SMD:C_1206_3216Metric")
    c2 = Component(symbol="Device:C", ref="C", value="10nF",
                   footprint="Capacitor_SMD:C_0603_1608Metric")
    c3 = Component(symbol="Device:C", ref="C", value="100nF",
                   footprint="Capacitor_SMD:C_0603_1608Metric")

    # LED + connecteur
    led1 = Component(symbol="Device:LED", ref="D", value="LED_RED",
                     footprint="LED_THT:LED_D5.0mm")
    j1   = Component(symbol="Connector_Generic:Conn_01x02", ref="J",
                     value="PWR_5V",
                     footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")

    # Connexions VCC
    j1[1]   += vcc
    u1["VCC"] += vcc
    u1["R"]   += vcc   # Reset (pin 4) — tied high
    r1[1]   += vcc
    c3[1]   += vcc

    # Connexions GND
    j1[2]   += gnd
    u1["GND"] += gnd
    c1[2]   += gnd
    c2[2]   += gnd
    c3[2]   += gnd
    led1[2] += gnd

    # Noeud timing THR/DIS (TR=TRIG pin2, THR=threshold pin6, DIS=discharge pin7)
    r1[2]      += thr_dis
    r2[1]      += thr_dis
    u1["TR"]   += thr_dis
    u1["THR"]  += thr_dis
    u1["DIS"]  += thr_dis
    c1[1]      += thr_dis
    r2[2]      += thr_dis

    # Pin 5 CV decoupling
    u1["CV"] += cv
    c2[1]    += cv

    # Sortie Q (OUT) -> R3 -> LED -> GND
    u1["Q"]  += out
    r3[1]    += out
    r3[2]     += led1[1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n[*] Instanciation du circuit...")
    try:
        circ = ne555_blinker()
        n_comps = len(circ._components) if hasattr(circ, '_components') else '?'
        print(f"[OK]  Circuit instancie: {n_comps} composants")
    except Exception as e:
        print(f"[ERR]  Instanciation: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # JSON netlist
    print("\n[-] Export JSON netlist...")
    try:
        netlist = circ.generate_json_netlist()
        OUT_DIR.mkdir(exist_ok=True)
        json_path = OUT_DIR / "netlist.json"
        json_path.write_text(json.dumps(netlist, indent=2, default=str))
        print(f"[OK]  {json_path}")
    except Exception as e:
        print(f"[WARN] JSON export: {e}")

    # Generer projet KiCad
    print("\n[>] Generation .kicad_sch + .kicad_pcb...")
    try:
        result = circ.generate_kicad_project(
            str(OUT_DIR / "ne555_blinker"),
            force_regenerate=True,
            generate_pcb=False,   # schematic only pour le test
        )
        print(f"[OK]  Projet genere dans: {OUT_DIR}")
        for f in sorted(OUT_DIR.rglob("*.*")):
            print(f"     {f.relative_to(OUT_DIR)}  ({f.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"[ERR]  Generation: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # Copier vers public/ pour KiCanvas
    pub = Path(__file__).parent.parent.parent / "apps/web/public"
    sch_files = list(OUT_DIR.rglob("*.kicad_sch"))
    pcb_files = list(OUT_DIR.rglob("*.kicad_pcb"))

    if pub.exists():
        if sch_files:
            dest = pub / "test-cs-ne555.kicad_sch"
            shutil.copy(sch_files[0], dest)
            print(f"\n[F]  Copie -> {dest}")
        if pcb_files:
            dest = pub / "test-cs-ne555.kicad_pcb"
            shutil.copy(pcb_files[0], dest)
            print(f"[F]  Copie -> {dest}")

        # Creer page de test KiCanvas
        _write_test_html(pub, bool(sch_files), bool(pcb_files))
        print("[W]  Ouvre: http://localhost:3333/test-cs.html")
    else:
        print(f"\n[WARN] Public dir introuvable: {pub}")


def _write_test_html(pub: Path, has_sch: bool, has_pcb: bool) -> None:
    tabs = ""
    if has_sch:
        tabs += '<button class="tab active" onclick="show(\'sch\')">Schematic circuit-synth</button>\n    '
    if has_pcb:
        tabs += '<button class="tab" onclick="show(\'pcb\')">PCB circuit-synth</button>'

    default_src = "/test-cs-ne555.kicad_sch" if has_sch else "/test-cs-ne555.kicad_pcb"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>circuit-synth Test — NE555 1Hz</title>
  <script type="module" src="/kicanvas.js"></script>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0A0A0A;color:#ccc;font-family:monospace;display:flex;flex-direction:column;height:100vh}}
    h1{{padding:8px 16px;font-size:13px;color:#D4820A;border-bottom:1px solid #222}}
    .tabs{{display:flex;gap:4px;padding:6px 16px;background:#111;border-bottom:1px solid #222}}
    .tab{{padding:4px 12px;cursor:pointer;border:1px solid #333;border-radius:4px;font-size:11px;color:#888}}
    .tab.active{{border-color:#D4820A;color:#D4820A}}
    .viewer{{flex:1;display:flex}}
    kicanvas-embed{{width:100%;height:100%}}
  </style>
</head>
<body>
  <h1>circuit-synth library test — NE555 1Hz Blinker — genere par Python, sans API</h1>
  <div class="tabs">
    {tabs}
  </div>
  <div class="viewer" id="container">
    <kicanvas-embed id="kv" src="{default_src}" controls="full" theme="dark"></kicanvas-embed>
  </div>
  <script>
    function show(type) {{
      document.querySelectorAll('.tab').forEach((t,i)=>
        t.classList.toggle('active',(i===0&&type==='sch')||(i===1&&type==='pcb')));
      const p=document.getElementById('container');
      const old=document.getElementById('kv');
      const n=old.cloneNode(false);
      n.setAttribute('src',type==='sch'?'/test-cs-ne555.kicad_sch':'/test-cs-ne555.kicad_pcb');
      p.replaceChild(n,old);
    }}
  </script>
</body>
</html>"""
    (pub / "test-cs.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()

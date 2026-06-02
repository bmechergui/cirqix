"""
Pipeline complet local — même comportement que Docker :
  1. Exécuter script circuit_synth Python → génère .kicad_sch + .kicad_net correct
  2. generate_pcb(kicad_sch_content, kicad_net_content) → PCB avec nets corrects
  3. Placement CMA-ES (place_unplaced cluster)
  4. Routage kicad-tools A* (kct route --power-nets)

Sortie dans C:\\Users\\Mechegui\\Downloads\\Kicadmcptest\\test\\meteo_arduino\\
  meteo_arduino.kicad_sch          — schéma circuit_synth
  meteo_arduino.kicad_pcb          — PCB généré (footprints + nets corrects)
  meteo_arduino_placed.kicad_pcb   — après placement
  meteo_arduino_routed.kicad_pcb   — après routage
"""

import base64
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

# Console Windows (cp1252) plante sur les caractères Unicode (═, ✅) — forcer UTF-8
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

_KICAD = Path(r"C:\Program Files\KiCad\10.99")
os.environ.setdefault("KICAD_SYMBOL_DIR",    str(_KICAD / "share/kicad/symbols"))
os.environ.setdefault("KICAD_FOOTPRINT_DIR", str(_KICAD / "share/kicad/footprints"))

# Utiliser les copies Layrix patchées (services/kicad/) en priorité sur les versions installées
_SVC = Path(__file__).parents[1]
CS_SRC = _SVC / "circuit_synth" / "src"
KT_SRC = _SVC / "kicad-tools" / "src"
for _p in [str(CS_SRC), str(KT_SRC), str(_SVC)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Propager aux sous-processus (kct route / optimize-placement lancent
# `python -m kicad_tools.cli` — sys.path ne se propage pas aux enfants)
_pp = [str(KT_SRC), str(CS_SRC)]
_existing = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = os.pathsep.join(
    _pp + [p for p in (_existing.split(os.pathsep) if _existing else []) if p and p not in _pp]
)

OUT_DIR  = Path(r"C:\Users\Mechegui\Downloads\Kicadmcptest\test")
BOARD_W, BOARD_H = 200.0, 160.0  # assez grand pour 2 rangées Arduino (68×53) + composants


# ── Script circuit_synth pour station météo Arduino ──────────────────────────

CIRCUIT_SYNTH_CODE = """
import os, sys
sys.path.insert(0, r'{cs_src}')
os.environ.setdefault('KICAD_SYMBOL_DIR', r'{sym_dir}')
os.chdir(r'{out_dir}')

from circuit_synth import Component, Net, circuit

@circuit(name='meteo_arduino')
def station_meteo():
    arduino = Component(symbol='MCU_Module:Arduino_UNO_R3', ref='U',
                        value='Arduino_UNO_R3', footprint='Module:Arduino_UNO_R3')
    dht22   = Component(symbol='Connector_Generic:Conn_01x03', ref='J',
                        value='DHT22',
                        footprint='Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical')
    r_pull  = Component(symbol='Device:R', ref='R', value='10k',
                        footprint='Resistor_SMD:R_0603_1608Metric')
    cap_dec = Component(symbol='Device:C', ref='C', value='100nF',
                        footprint='Capacitor_SMD:C_0603_1608Metric')
    pwr     = Component(symbol='Connector_Generic:Conn_01x02', ref='J',
                        value='PWR_5V',
                        footprint='Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical')

    vcc  = Net('VCC_5V')
    gnd  = Net('GND')
    data = Net('DHT_DATA')

    arduino['+5V'] += vcc;  arduino['GND'] += gnd;  arduino['D2'] += data
    dht22['Pin_1'] += vcc;  dht22['Pin_2'] += data;  dht22['Pin_3'] += gnd
    r_pull['1']    += vcc;  r_pull['2']    += data
    cap_dec['1']   += vcc;  cap_dec['2']   += gnd
    pwr['Pin_1']   += vcc;  pwr['Pin_2']   += gnd

circ = station_meteo()
circ.generate_kicad_project(
    r'{out_dir}\\meteo_arduino',
    force_regenerate=True,
    generate_pcb=False,
)
print('circuit_synth OK')
"""


def pcb_stats(content: str) -> str:
    fps   = content.count("(footprint ")
    segs  = len(re.findall(r"\(segment[\s\n]", content))
    zones = len(re.findall(r"\(zone[\s\n]", content))
    vias  = len(re.findall(r"\(via[\s\n]", content))
    return f"{fps} footprints · {segs} segments · {zones} zones · {vias} vias"


def run_circuit_synth() -> tuple[str, str | None]:
    """Execute circuit_synth Python script → returns (sch_content, net_content)."""
    code = CIRCUIT_SYNTH_CODE.format(
        cs_src   = str(CS_SRC).replace("\\", "\\\\"),
        sym_dir  = str(_KICAD / "share/kicad/symbols").replace("\\", "\\\\"),
        out_dir  = str(OUT_DIR).replace("\\", "\\\\"),
    )
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False,
                                     encoding="utf-8") as f:
        f.write(code); script = Path(f.name)

    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONUTF8": "1"},
        )
        if r.returncode != 0:
            print(f"  ERREUR circuit_synth (rc={r.returncode}):\n{r.stderr[-500:]}")
            return "", None
        print(f"  {r.stdout.strip()}")
    finally:
        script.unlink(missing_ok=True)

    sch_path = OUT_DIR / "meteo_arduino" / "meteo_arduino.kicad_sch"
    net_path = OUT_DIR / "meteo_arduino" / "meteo_arduino.net"

    # Lire les contenus AVANT de supprimer le sous-dossier
    sch_content = sch_path.read_text(encoding="utf-8") if sch_path.exists() else ""
    net_content = net_path.read_text(encoding="utf-8") if net_path.exists() else None

    # Copier le schéma dans OUT_DIR (racine test/)
    if sch_path.exists():
        dest = OUT_DIR / "meteo_arduino.kicad_sch"
        dest.write_text(sch_content, encoding="utf-8")
        print(f"  .kicad_sch → {dest.name}")

    # Nettoyer le sous-dossier circuit_synth (meteo_arduino/) — tout dans test/ directement
    import shutil as _shutil
    sub = OUT_DIR / "meteo_arduino"
    if sub.exists():
        _shutil.rmtree(sub, ignore_errors=True)

    if net_content:
        print(f"  .kicad_net trouvé ({len(net_content):,} chars) — connexions correctes ✅")
    else:
        print("  ATTENTION : pas de .kicad_net — netlist depuis kicad-cli (peut avoir des erreurs)")

    return sch_content, net_content


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Sortie : {OUT_DIR}")
    print(f"Board  : {BOARD_W}×{BOARD_H}mm\n")

    # ── Étape 1 : circuit_synth → .kicad_sch + .kicad_net ────────────────────
    print("═" * 60)
    print("ÉTAPE 1 — Génération schéma (circuit_synth Python)")
    print("═" * 60)
    sch_content, net_content = run_circuit_synth()
    if not sch_content:
        print("ERREUR — circuit_synth n'a pas généré de schéma")
        sys.exit(1)

    # ── Étape 2 : PCB generation ──────────────────────────────────────────────
    print()
    print("═" * 60)
    print("ÉTAPE 2 — Génération PCB (kicad-tools PCBFromSchematic)")
    print("═" * 60)
    from tools.pcb import generate_pcb
    from tools.schematic import SchemaNet

    # Passer kicad_net_content si disponible (même comportement que Docker)
    pcb_content = generate_pcb(
        components=[],
        connections=[],
        board_w=BOARD_W,
        board_h=BOARD_H,
        kicad_sch_content=sch_content,
        kicad_net_content=net_content,
    )
    if not pcb_content:
        print("ERREUR génération PCB")
        sys.exit(1)

    # Vérifier les nets de R1/C1
    nets = {int(m.group(1)): m.group(2)
            for m in re.finditer(r'\(net\s+(\d+)\s+"([^"]+)"\)', pcb_content)}
    print(f"  {pcb_stats(pcb_content)}")

    # Check R1/C1 nets
    print("  Nets clés :")
    for fpm in re.finditer(
        r'\(footprint\s+"[^"]+"\s+[\s\S]*?(?=\n\s+\(footprint|\n\s+\(gr_|\Z)', pcb_content
    ):
        b   = fpm.group(0)
        rm  = re.search(r'\(property "Reference" "([^"]+)"', b)
        ref = rm.group(1) if rm else "?"
        if ref in ("R1", "C1", "J1"):
            pads = re.findall(r'\(pad\s+"([^"]+)"[\s\S]*?\(net\s+(\d+)', b)
            net_names = [(p, nets.get(int(n), "?")) for p, n in pads]
            ok = all(n not in ("", "?") and not n.startswith("unconnected") and not n.startswith("Net-(") for _, n in net_names)
            print(f"    {ref}: {net_names}  {'✅' if ok else '❌ (netlist incorrect)'}")

    pcb_path = OUT_DIR / "meteo_arduino.kicad_pcb"
    pcb_path.write_text(pcb_content, encoding="utf-8")
    print(f"  OK  {pcb_path.name}  ({pcb_path.stat().st_size:,} octets)")

    # ── Étape 3 : Placement ───────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("ÉTAPE 3 — Placement (optimize-placement CMA-ES → place_unplaced)")
    print("═" * 60)
    from tools.placement import auto_place

    pcb_b64   = base64.b64encode(pcb_content.encode()).decode()
    place_res = auto_place(pcb_b64, BOARD_W, BOARD_H)
    placed_bytes   = base64.b64decode(place_res["kicad_pcb_b64"])
    placed_content = placed_bytes.decode("utf-8", errors="replace")

    placed_path = OUT_DIR / "meteo_arduino_placed.kicad_pcb"
    placed_path.write_bytes(placed_bytes)
    print(f"  {pcb_stats(placed_content)}")
    print(f"  placed_count = {place_res['placed_count']}")

    from kicad_tools.schema.pcb import PCB as _PCB
    from kicad_tools.placement.place_unplaced import _get_board_bounds as _bb
    pcb2  = _PCB.load(str(placed_path))
    bnds  = _bb(pcb2) or (0, 0, BOARD_W, BOARD_H)
    bx0, by0, bx1, by1 = bnds
    print(f"  Board : {bx1-bx0:.0f}×{by1-by0:.0f}mm")
    for fp in pcb2.footprints:
        x, y    = fp.position
        inside  = bx0 <= x <= bx1 and by0 <= y <= by1
        print(f"    {fp.reference:6s}  ({x:.1f},{y:.1f})  {'OK' if inside else 'HORS-BOARD'}")

    print(f"  OK  {placed_path.name}  ({placed_path.stat().st_size:,} octets)")

    # ── Étape 4 : Routage ─────────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("ÉTAPE 4 — Routage (kct route --power-nets)")
    print("═" * 60)
    from routers.routing import _route_with_kicad_tools

    routed_bytes, pct = _route_with_kicad_tools(placed_bytes)
    routed_content    = routed_bytes.decode("utf-8", errors="replace")

    routed_path = OUT_DIR / "meteo_arduino_routed.kicad_pcb"
    routed_path.write_bytes(routed_bytes)
    print(f"  {pcb_stats(routed_content)}")
    print(f"  Routé : {pct}%")
    print(f"  OK  {routed_path.name}  ({routed_path.stat().st_size:,} octets)")

    # ── Bilan ─────────────────────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("BILAN")
    print("═" * 60)
    print(f"  1. Schéma   → meteo_arduino.kicad_sch")
    print(f"  2. PCB      → meteo_arduino.kicad_pcb")
    print(f"  3. Placé    → meteo_arduino_placed.kicad_pcb")
    print(f"  4. Routé    → meteo_arduino_routed.kicad_pcb")
    print()
    print("Ouvrir dans KiCad → appuyer B pour remplir les zones GND/VCC")


if __name__ == "__main__":
    main()

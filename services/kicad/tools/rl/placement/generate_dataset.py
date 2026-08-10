#!/usr/bin/env python3
"""Generate synthetic pre-CMA-ES style boards for RL placement training.

Writes committed fixtures under::

    examples/rl-placement-dataset/boards/*.kicad_pcb
    examples/rl-placement-dataset/manifest.json

Boards intentionally use suboptimal / clustered positions so the Géomètre-RL
has something to improve (not already-perfect layouts).

Usage (from services/kicad)::

    python -m tools.rl.placement.generate_dataset
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicad_tools.schema.pcb import PCB  # noqa: E402

_DATASET = _SERVICE_ROOT / "examples" / "rl-placement-dataset"
_BOARDS = _DATASET / "boards"


def _resistor(ref: str, uuid: str, x: float, y: float, net_a: int, net_b: int, net_a_name: str, net_b_name: str) -> str:
    return f"""\
  (footprint "Resistor_SMD:R_0402_1005Metric"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x} {y})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "10k" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net_a} "{net_a_name}"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net_b} "{net_b_name}"))
  )
"""


def _cap(ref: str, uuid: str, x: float, y: float, net_a: int, net_b: int, na: str, nb: str) -> str:
    return f"""\
  (footprint "Capacitor_SMD:C_0402_1005Metric"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x} {y})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "100n" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net_a} "{na}"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net_b} "{nb}"))
  )
"""


def _connector(ref: str, uuid: str, x: float, y: float, net1: int, net2: int, n1: str, n2: str) -> str:
    return f"""\
  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x} {y})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Conn" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net {net1} "{n1}"))
    (pad "2" thru_hole circle (at 0 2.54) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net {net2} "{n2}"))
  )
"""


def _soic(ref: str, uuid: str, x: float, y: float, nets: list[tuple[int, str]]) -> str:
    """Minimal 8-pad SOIC-like footprint (2x4) for dual-cluster boards."""
    pads = ""
    positions = [
        (-2.0, -1.5), (-2.0, -0.5), (-2.0, 0.5), (-2.0, 1.5),
        (2.0, 1.5), (2.0, 0.5), (2.0, -0.5), (2.0, -1.5),
    ]
    for i, ((px, py), (net_id, net_name)) in enumerate(zip(positions, nets), start=1):
        pads += f"""
    (pad "{i}" smd rect (at {px} {py}) (size 0.6 0.5) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net_id} "{net_name}"))"""
    return f"""\
  (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x} {y})
    (property "Reference" "{ref}" (at 0 -3 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "IC" (at 0 3 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
{pads}
  )
"""


def _write_board(name: str, width: float, height: float, inject: str, description: str) -> dict:
    pcb = PCB.create(width=width, height=height, layers=2)
    ox, oy = pcb.board_origin
    # Rewrite inject with absolute coords if callers pass board-relative;
    # callers pass absolute already including origin.
    path = _BOARDS / f"{name}.kicad_pcb"
    path.parent.mkdir(parents=True, exist_ok=True)
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    n_fp = text[:close_idx].count('(property "Reference"')  # rough; recount after
    pcb2 = PCB.load(str(path))
    return {
        "id": name,
        "path": str(path.relative_to(_SERVICE_ROOT)).replace("\\", "/"),
        "width_mm": width,
        "height_mm": height,
        "n_footprints": len(pcb2.footprints),
        "description": description,
        "role": "synthetic_pre_cmaes",
    }


def _board_two_resistor_overlap(ox: float, oy: float) -> tuple[str, str, float, float]:
    """R1/R2 almost stacked — wirelength + overlap to resolve."""
    inj = ""
    inj += _resistor("R1", "a0000001-0001-0001-0001-000000000001", ox + 30, oy + 20, 1, 2, "VCC", "N1")
    inj += _resistor("R2", "a0000001-0001-0001-0001-000000000002", ox + 30.4, oy + 20.2, 2, 3, "N1", "GND")
    inj += _connector("J1", "a0000001-0001-0001-0001-0000000000j1", ox + 5, oy + 5, 1, 3, "VCC", "GND")
    return "01_two_resistor_overlap", inj, 50.0, 40.0


def _board_rc_chain_scattered(ox: float, oy: float) -> tuple[str, str, float, float]:
    """RC chain with passives far from logical order."""
    inj = ""
    inj += _connector("J1", "b0000001-0001-0001-0001-0000000000j1", ox + 4, oy + 20, 1, 5, "VIN", "GND")
    # Scattered positions (not sequential)
    places = [(40, 8), (12, 32), (45, 30), (18, 10), (35, 18)]
    nets = [(1, 2, "VIN", "N1"), (2, 3, "N1", "N2"), (3, 4, "N2", "N3"), (4, 5, "N3", "GND")]
    for i, ((x, y), (a, b, na, nb)) in enumerate(zip(places[:4], nets), start=1):
        inj += _resistor(f"R{i}", f"b0000001-0001-0001-0001-0000000000r{i}", ox + x, oy + y, a, b, na, nb)
    inj += _cap("C1", "b0000001-0001-0001-0001-0000000000c1", ox + places[4][0], oy + places[4][1], 4, 5, "N3", "GND")
    return "02_rc_chain_scattered", inj, 55.0, 40.0


def _board_dual_cluster(ox: float, oy: float) -> tuple[str, str, float, float]:
    """Two ICs with bypass caps piled near wrong IC (clustering exercise)."""
    nets_u1 = [(1, "VCC"), (2, "S1"), (3, "S2"), (4, "GND"), (5, "GND"), (6, "S3"), (7, "S4"), (8, "VCC")]
    nets_u2 = [(1, "VCC"), (2, "S5"), (3, "S6"), (4, "GND"), (5, "GND"), (6, "S7"), (7, "S8"), (8, "VCC")]
    inj = ""
    inj += _soic("U1", "c0000001-0001-0001-0001-0000000000u1", ox + 15, oy + 15, nets_u1)
    inj += _soic("U2", "c0000001-0001-0001-0001-0000000000u2", ox + 45, oy + 25, nets_u2)
    # Caps clustered on U1 side even for U2 nets (bad placement)
    inj += _cap("C1", "c0000001-0001-0001-0001-0000000000c1", ox + 18, oy + 22, 1, 4, "VCC", "GND")
    inj += _cap("C2", "c0000001-0001-0001-0001-0000000000c2", ox + 20, oy + 12, 1, 4, "VCC", "GND")
    inj += _cap("C3", "c0000001-0001-0001-0001-0000000000c3", ox + 16, oy + 28, 1, 4, "VCC", "GND")  # should be near U2
    inj += _connector("J1", "c0000001-0001-0001-0001-0000000000j1", ox + 5, oy + 5, 1, 4, "VCC", "GND")
    return "03_dual_ic_misclustered", inj, 65.0, 45.0


def _board_connector_passives(ox: float, oy: float) -> tuple[str, str, float, float]:
    """Edge connector + passives dumped in the opposite corner."""
    inj = ""
    inj += _connector("J1", "d0000001-0001-0001-0001-0000000000j1", ox + 5, oy + 5, 1, 2, "VCC", "GND")
    inj += _connector("J2", "d0000001-0001-0001-0001-0000000000j2", ox + 5, oy + 35, 3, 2, "SIG", "GND")
    # Passives far away (high wirelength)
    for i, (x, y) in enumerate([(50, 30), (48, 28), (52, 32), (46, 34)], start=1):
        inj += _resistor(
            f"R{i}", f"d0000001-0001-0001-0001-0000000000r{i}",
            ox + x, oy + y, 1 if i < 3 else 3, 2, "VCC" if i < 3 else "SIG", "GND",
        )
    return "04_connectors_passives_far", inj, 60.0, 45.0


def _board_dense_grid(ox: float, oy: float) -> tuple[str, str, float, float]:
    """3x3 resistors with compressed spacing (congestion)."""
    inj = ""
    inj += _connector("J1", "e0000001-0001-0001-0001-0000000000j1", ox + 3, oy + 20, 1, 10, "VCC", "GND")
    n = 1
    idx = 1
    for row in range(3):
        for col in range(3):
            x = 20 + col * 1.2  # too tight
            y = 15 + row * 1.2
            na, nb = n, n + 1 if n < 9 else 10
            inj += _resistor(
                f"R{idx}", f"e0000001-0001-0001-0001-0000000000r{idx}",
                ox + x, oy + y, na, nb, f"N{na}", f"N{nb}" if nb < 10 else "GND",
            )
            n += 1
            idx += 1
    return "05_dense_resistor_grid", inj, 50.0, 40.0


def _board_asymmetric_power(ox: float, oy: float) -> tuple[str, str, float, float]:
    """Power entry bottom-left, load top-right, decoupling in center pile."""
    inj = ""
    inj += _connector("J1", "f0000001-0001-0001-0001-0000000000j1", ox + 5, oy + 35, 1, 2, "VCC", "GND")
    inj += _soic(
        "U1", "f0000001-0001-0001-0001-0000000000u1", ox + 50, oy + 10,
        [(1, "VCC"), (2, "IO1"), (3, "IO2"), (4, "GND"), (5, "GND"), (6, "IO3"), (7, "IO4"), (8, "VCC")],
    )
    for i, (dx, dy) in enumerate([(28, 22), (29, 23), (27, 21)], start=1):
        inj += _cap(
            f"C{i}", f"f0000001-0001-0001-0001-0000000000c{i}",
            ox + dx, oy + dy, 1, 2, "VCC", "GND",
        )
    inj += _resistor("R1", "f0000001-0001-0001-0001-0000000000r1", ox + 40, oy + 30, 1, 3, "VCC", "IO1")
    return "06_asymmetric_power_load", inj, 70.0, 50.0


def generate() -> dict:
    _BOARDS.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    builders = [
        _board_two_resistor_overlap,
        _board_rc_chain_scattered,
        _board_dual_cluster,
        _board_connector_passives,
        _board_dense_grid,
        _board_asymmetric_power,
    ]
    descriptions = [
        "Two resistors nearly overlapping + power connector (overlap/wirelength)",
        "RC chain with passives scattered (ordering / proximity)",
        "Dual SOIC with bypass caps mis-clustered on wrong IC",
        "Edge connectors with passives dumped in far corner",
        "3x3 resistor grid with too-tight pitch (congestion)",
        "Power entry opposite load IC; caps piled in center",
    ]

    for builder, desc in zip(builders, descriptions):
        # origin from a blank board of matching size — build twice: once for origin
        name_probe, _, w, h = builder(0, 0)
        probe = PCB.create(width=w, height=h, layers=2)
        ox, oy = probe.board_origin
        name, inject, w, h = builder(ox, oy)
        meta = _write_board(name, w, h, inject, desc)
        entries.append(meta)

    # Reference real fixtures (paths only — not copied, stay in their example dirs).
    # Prefer pre-CMA-ES / gen_pcb grids over final placed boards so RL learns to
    # *improve* layouts (training on 5_placed alone caused the 2026-07-28 NO-GO).
    refs = [
        {
            "id": "ref_led_gen",
            "path": "examples/led-blinker-full-pipeline/output/4_gen.kicad_pcb",
            "description": "Real LED board post-gen_pcb (grid start, pre-place/CMA-ES).",
            "role": "reference_pre_cmaes",
            "optional": True,
        },
        {
            "id": "ref_led_placed",
            "path": "examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb",
            "description": "Real LED pipeline board (post full place). Eval only / hard case.",
            "role": "reference_existing",
            "optional": True,
            "train_default": False,
        },
        {
            "id": "ref_stm32_final",
            "path": "examples/stm32-validation/expected/stm32_final.kicad_pcb",
            "description": "Real STM32 stress board. Optional dense fine-pitch case.",
            "role": "reference_existing",
            "optional": True,
            "train_default": False,
        },
    ]
    for r in refs:
        p = _SERVICE_ROOT / r["path"]
        r["available"] = p.is_file()
        if r["available"]:
            entries.append(r)

    # Train set = synthetic boards only by default (homogeneous pre-CMA-ES distribution).
    # Real refs are listed for optional --pcb / eval; avoid mixing final boards into train.
    train_ids = [e["id"] for e in entries if e.get("role") == "synthetic_pre_cmaes"]
    manifest = {
        "name": "rl-placement-dataset",
        "version": 2,
        "purpose": (
            "Multi-board RL placement training (Phase 6a) — synthetic pre-CMA-ES "
            "layouts (overlap, scatter, dual-IC clustering, congestion) + optional real refs"
        ),
        "train_board_ids": train_ids,
        "train_command": (
            "python -m tools.rl.placement.train_placement "
            "--pcb-dir examples/rl-placement-dataset/boards "
            "--algo ppo --steps 200000 "
            "--max-episode-steps 48 "
            "--out models/placement_ppo_v2.zip "
            "--metrics-json tmp/rl_ppo_v2_metrics.json"
        ),
        "eval_command": (
            "python -m tools.rl.placement.eval_vs_cmaes "
            "--pcb-dir examples/rl-placement-dataset/boards "
            "--model models/placement_ppo_v2.zip "
            "--out-json tmp/rl_vs_cmaes_v2.json "
            "--artifact-dir tmp/rl_vs_cmaes_v2_art"
        ),
        "boards": entries,
    }
    man_path = _DATASET / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    man = generate()
    print(json.dumps({"boards": len(man["boards"]), "manifest": str(_DATASET / "manifest.json")}, indent=2))
    for b in man["boards"]:
        print(f"  - {b['id']}: {b.get('path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Export RL routing path → copper segments on a placed PCB."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from kicad_tools.schema.pcb import PCB


def export_paths_to_pcb(
    placed_pcb: str | Path,
    paths: list[dict],
    out_path: str | Path,
    *,
    width_mm: float = 0.25,
) -> Path:
    """Write segment chains onto a copy of ``placed_pcb``.

    Each path dict::
        {
          "net_name": str,
          "net_id": int,
          "points": list[tuple[float,float]],  # absolute mm world
          "layer": str,  # "F.Cu" | "B.Cu"
        }
    """
    placed_pcb = Path(placed_pcb)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(placed_pcb, out_path)
    pcb = PCB.load(str(out_path))

    for path in paths:
        pts = path.get("points") or []
        if len(pts) < 2:
            continue
        net = path.get("net_name") or None
        layer = path.get("layer") or "F.Cu"
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a == b:
                continue
            try:
                pcb.add_trace(
                    (float(a[0]), float(a[1])),
                    (float(b[0]), float(b[1])),
                    width=width_mm,
                    layer=layer,
                    net=net,
                    dedupe=True,
                )
            except Exception:
                # Fallback: skip bad segment
                continue

    pcb.save(str(out_path))
    return out_path


def path_cells_to_points(
    board,
    cells: list[tuple[int, int, int]],
) -> list[tuple[float, float]]:
    """Convert (gx, gy, layer) cells to world mm points (dedupe consecutive)."""
    points: list[tuple[float, float]] = []
    for gx, gy, _layer in cells:
        x, y = board.grid_to_world(int(gx), int(gy))
        pt = (float(x), float(y))
        if not points or points[-1] != pt:
            points.append(pt)
    return points

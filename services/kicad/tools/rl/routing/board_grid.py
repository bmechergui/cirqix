"""Board grid for RL routing — thin envelope over kicad-tools RoutingGrid.

Loads a *placed* ``.kicad_pcb``, builds production ``RoutingGrid`` + pads,
and rasterises observation channels for the local router policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
from kicad_tools.core.types import CopperLayer
from kicad_tools.optim.board_outline import extract_board_outline
from kicad_tools.router.grid import DesignRules, RoutingGrid
from kicad_tools.router.primitives import Pad
from kicad_tools.schema.pcb import PCB

# Observation channel order (PLAN / README)
CH_SOURCE_TARGET = 0
CH_SAME_NET_COPPER = 1
CH_OTHER_NET_COPPER = 2
CH_KEEP_OUT = 3
CH_EDGE = 4
CH_CONGESTION = 5
CH_CURSOR = 6
CH_DISTANCE = 7
N_CHANNELS = 8

# Default curriculum net order (LED blinker)
DEFAULT_NET_ORDER: tuple[str, ...] = (
    "LED_A",
    "OUT",
    "DISCH",
    "TRIG_THR",
    "VCC",
    "GND",
)


@dataclass
class NetTerminals:
    """Pads belonging to one electrical net (for multi-pin nets: pair source→target)."""

    net_id: int
    net_name: str
    pads: list[Pad] = field(default_factory=list)

    @property
    def source(self) -> Pad | None:
        return self.pads[0] if self.pads else None

    @property
    def target(self) -> Pad | None:
        return self.pads[-1] if len(self.pads) >= 2 else None


@dataclass
class BoardGrid:
    """Surrogate board: RoutingGrid + net terminals + observation raster helpers."""

    pcb_path: Path
    pcb: PCB
    grid: RoutingGrid
    rules: DesignRules
    origin_x: float
    origin_y: float
    width_mm: float
    height_mm: float
    nets: dict[str, NetTerminals]
    resolution_mm: float

    @property
    def shape(self) -> tuple[int, int, int]:
        """(n_layers, height_cells, width_cells) for blocked array."""
        blocked = self.grid._blocked  # production array
        return tuple(int(x) for x in blocked.shape)  # type: ignore[return-value]

    @property
    def n_layers(self) -> int:
        return int(self.grid._blocked.shape[0])

    @property
    def height_cells(self) -> int:
        return int(self.grid._blocked.shape[1])

    @property
    def width_cells(self) -> int:
        return int(self.grid._blocked.shape[2])

    def world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        return self.grid.world_to_grid(x, y)

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        return self.grid.grid_to_world(gx, gy)

    def layer_enum(self, stack_index: int) -> CopperLayer:
        """Map dense stack index 0..n_layers-1 to CopperLayer for RoutingGrid APIs."""
        try:
            indices = list(self.grid.get_routable_indices())
            if indices and 0 <= stack_index < len(indices):
                # reverse: stack slot → layer enum via index_to_layer if present
                if hasattr(self.grid, "index_to_layer"):
                    return self.grid.index_to_layer(indices[stack_index])
        except Exception:
            pass
        # 2-layer default: 0 → F.Cu, 1 → B.Cu
        return CopperLayer.F_CU if stack_index <= 0 else CopperLayer.B_CU

    def is_blocked(self, layer: int, gx: int, gy: int, net_id: int | None = None) -> bool:
        """Return True if cell is blocked. ``layer`` is dense stack index (0=F, 1=B)."""
        if gx < 0 or gy < 0 or gx >= self.width_cells or gy >= self.height_cells:
            return True
        if layer < 0 or layer >= self.n_layers:
            return True
        net = 0 if net_id is None else int(net_id)
        layer_e = self.layer_enum(layer)
        try:
            return bool(self.grid.is_blocked(gx, gy, layer_e, net))
        except Exception:
            # Fallback: raw blocked array [layer, gy, gx]
            return bool(self.grid._blocked[layer, gy, gx])

    def list_net_names(self) -> list[str]:
        return sorted(self.nets.keys(), key=lambda n: (n not in DEFAULT_NET_ORDER, n))

    def terminals_for(self, net_name: str) -> NetTerminals | None:
        return self.nets.get(net_name)

    def observation(
        self,
        *,
        net_name: str,
        cursor_xy: tuple[float, float],
        layer: int = 0,
        source_pad: Pad | None = None,
        target_pad: Pad | None = None,
    ) -> np.ndarray:
        """Build float32 observation (N_CHANNELS, H, W) for one layer view.

        Multi-layer stacks still expose one layer's channels (local router v1);
        layer index selects which copper layer maps are read.
        """
        h, w = self.height_cells, self.width_cells
        obs = np.zeros((N_CHANNELS, h, w), dtype=np.float32)
        term = self.nets.get(net_name)
        net_id = term.net_id if term else -1
        layer = int(max(0, min(layer, self.n_layers - 1)))

        # CH_KEEP_OUT / blocked (static obstacles) — same as RoutingGrid
        blocked = self.grid._blocked[layer].astype(np.float32)
        obs[CH_KEEP_OUT] = blocked

        # CH_EDGE: board edge cells (dilated blocked border approximation)
        edge = np.zeros((h, w), dtype=np.float32)
        edge[0, :] = 1.0
        edge[-1, :] = 1.0
        edge[:, 0] = 1.0
        edge[:, -1] = 1.0
        obs[CH_EDGE] = edge

        # CH_CONGESTION
        if hasattr(self.grid, "get_congestion_map"):
            try:
                cmap = self.grid.get_congestion_map(layer)
                obs[CH_CONGESTION] = np.asarray(cmap, dtype=np.float32)
            except Exception:
                obs[CH_CONGESTION] = 0.0

        # Pads source/target + same-net markers
        if term is not None:
            for pad in term.pads:
                gx, gy = self.world_to_grid(pad.x, pad.y)
                if 0 <= gx < w and 0 <= gy < h:
                    obs[CH_SOURCE_TARGET, gy, gx] = 1.0
                    # same-net copper seed on pad centers
                    obs[CH_SAME_NET_COPPER, gy, gx] = 1.0

        if source_pad is not None:
            gx, gy = self.world_to_grid(source_pad.x, source_pad.y)
            if 0 <= gx < w and 0 <= gy < h:
                obs[CH_SOURCE_TARGET, gy, gx] = 1.0
        if target_pad is not None:
            gx, gy = self.world_to_grid(target_pad.x, target_pad.y)
            if 0 <= gx < w and 0 <= gy < h:
                obs[CH_SOURCE_TARGET, gy, gx] = 1.0

        # Other-net pads as keepouts already in blocked; mark copper channel
        for name, other in self.nets.items():
            if name == net_name:
                continue
            for pad in other.pads:
                gx, gy = self.world_to_grid(pad.x, pad.y)
                if 0 <= gx < w and 0 <= gy < h:
                    obs[CH_OTHER_NET_COPPER, gy, gx] = 1.0

        # Cursor
        cgx, cgy = self.world_to_grid(cursor_xy[0], cursor_xy[1])
        if 0 <= cgx < w and 0 <= cgy < h:
            obs[CH_CURSOR, cgy, cgx] = 1.0

        # Distance map to target (normalized)
        if target_pad is not None:
            tgx, tgy = self.world_to_grid(target_pad.x, target_pad.y)
            ys = np.arange(h, dtype=np.float32)[:, None]
            xs = np.arange(w, dtype=np.float32)[None, :]
            dist = np.sqrt((xs - tgx) ** 2 + (ys - tgy) ** 2)
            max_d = float(dist.max()) or 1.0
            obs[CH_DISTANCE] = 1.0 - (dist / max_d)
        else:
            obs[CH_DISTANCE] = 0.0

        return obs

    def flat_observation(self, **kwargs) -> np.ndarray:
        """Flattened observation for MLP policies (N_CHANNELS*H*W,)."""
        return self.observation(**kwargs).reshape(-1)


def _pad_abs_xy(fp, pad) -> tuple[float, float]:
    """Footprint API positions are origin-relative; RoutingGrid wants absolute mm."""
    ox, oy = fp.position[0], fp.position[1]
    # PCB.board_origin is the Edge.Cuts origin; API fp.position already subtracts it
    # so absolute = board_origin + fp.position + pad.position
    return float(ox + pad.position[0]), float(oy + pad.position[1])


def _layer_from_pad(pad) -> CopperLayer:
    layers = getattr(pad, "layers", None) or []
    layer_strs = [str(x) for x in layers]
    if any("B.Cu" in s for s in layer_strs) and not any("F.Cu" in s for s in layer_strs):
        return CopperLayer.B_CU
    return CopperLayer.F_CU


def _through_hole(pad) -> bool:
    t = str(getattr(pad, "type", "") or "").lower()
    return "thru" in t or "through" in t or float(getattr(pad, "drill", 0) or 0) > 0


def build_board_grid(
    pcb_path: str | Path,
    *,
    resolution_mm: float | None = None,
    rules: DesignRules | None = None,
) -> BoardGrid:
    """Load placed PCB and build RoutingGrid with all pads as obstacles."""
    path = Path(pcb_path)
    if not path.is_file():
        raise FileNotFoundError(f"PCB not found: {path}")

    pcb = PCB.load(str(path))
    ox, oy = pcb.board_origin
    outline = extract_board_outline(pcb)
    if outline is not None and outline.vertices:
        xs = [float(v.x) for v in outline.vertices]
        ys = [float(v.y) for v in outline.vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max_x - min_x
        height = max_y - min_y
        origin_x, origin_y = min_x, min_y
    else:
        # Fallback 60×45 LED-style board at origin
        width, height = 60.0, 45.0
        origin_x, origin_y = float(ox), float(oy)

    rules = rules or DesignRules(
        grid_resolution=resolution_mm if resolution_mm is not None else 0.25,
        trace_clearance=0.2,
        trace_width=0.2,
    )
    if resolution_mm is not None:
        rules.grid_resolution = float(resolution_mm)

    grid = RoutingGrid(
        width,
        height,
        rules,
        origin_x,
        origin_y,
        resolution_override=rules.grid_resolution,
    )

    nets: dict[str, NetTerminals] = {}
    for fp in pcb.footprints:
        # absolute mm: file at = origin + relative API position
        base_x = float(ox) + float(fp.position[0])
        base_y = float(oy) + float(fp.position[1])
        for pad in fp.pads:
            net_name = str(getattr(pad, "net_name", "") or "")
            net_id = int(getattr(pad, "net", 0) or getattr(pad, "net_number", 0) or 0)
            if not net_name or net_id <= 0:
                continue
            px = base_x + float(pad.position[0])
            py = base_y + float(pad.position[1])
            size = getattr(pad, "size", None)
            if size is not None and isinstance(size, (list, tuple)) and len(size) >= 2:
                pw, ph = float(size[0]), float(size[1])
            else:
                pw, ph = 0.6, 0.6
            drill = float(getattr(pad, "drill", 0) or 0)
            gpad = Pad(
                x=px,
                y=py,
                width=pw,
                height=ph,
                net=net_id,
                net_name=net_name,
                layer=_layer_from_pad(pad),
                ref=str(fp.reference),
                pin=str(getattr(pad, "number", "")),
                through_hole=_through_hole(pad),
                drill=drill,
            )
            grid.add_pad(gpad)
            if net_name not in nets:
                nets[net_name] = NetTerminals(net_id=net_id, net_name=net_name)
            nets[net_name].pads.append(gpad)

    return BoardGrid(
        pcb_path=path.resolve(),
        pcb=pcb,
        grid=grid,
        rules=rules,
        origin_x=origin_x,
        origin_y=origin_y,
        width_mm=width,
        height_mm=height,
        nets=nets,
        resolution_mm=float(rules.grid_resolution),
    )


def pair_terminals(term: NetTerminals) -> tuple[Pad, Pad] | None:
    """Pick source/target pads for a net (first / last by ref+pin sort)."""
    if len(term.pads) < 2:
        return None
    pads = sorted(term.pads, key=lambda p: (p.ref, p.pin))
    return pads[0], pads[-1]

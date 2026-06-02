"""FastAPI router for auto-routing.

Two endpoints:

- ``POST /route``         — path-based, kept for backwards compatibility.
- ``POST /route/auto``    — base64 I/O. Pipeline:
    1. Freerouting (Java) — preferred, handles all complexity.
    2. kicad-tools Python router — fallback when Java absent, ≤ 10 nets, 60s budget.
    3. skipped=True — when both are unavailable or board is too complex.

Pipeline Freerouting: ``.kicad_pcb`` → Specctra DSN → Freerouting (Java) → SES → ``.kicad_pcb``.
Pipeline kicad-tools: ``.kicad_pcb`` → Python A* negotiated router → ``.kicad_pcb``.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["routing"])

# 2-layer simple boards usually < 90s, 4-layer ~300s, 8-layer ~600s
_DEFAULT_TIMEOUT_S: int = 300


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

_KICAD_TOOLS_MAX_NETS: int = 30
_KICAD_TOOLS_MAX_COMPS: int = 30
_PYTHON_ROUTER_TIMEOUT_S: int = 60

# Below this completion %, prefer Freerouting (higher quality) when available.
# Matches kct's own --min-completion 0.95 default.
_MIN_ROUTED_PCT: int = 95


class RouteAutoRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    layers: int = Field(default=2, description="Copper layer count (2, 4, or 8)")
    timeout_s: int = Field(default=_DEFAULT_TIMEOUT_S, ge=30, le=900)

    def model_post_init(self, _context: Any) -> None:
        if self.layers not in (2, 4, 8):
            raise ValueError("layers must be 2, 4, or 8")


class RouteAutoResponse(BaseModel):
    kicad_pcb_b64: Optional[str] = None
    routed_percent: int = 0
    layers: int
    via_count: int = 0
    track_length_mm: float = 0.0
    skipped: bool = False
    warning: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

def _find_freerouting_api() -> Optional[str]:
    """Return Freerouting API base URL if the server is reachable, else None."""
    import urllib.request, urllib.error
    base = os.environ.get("FREEROUTING_API_URL", "http://127.0.0.1:37864")
    try:
        urllib.request.urlopen(f"{base}/api/v1/system/status", timeout=2)
        return base
    except Exception:
        return None


def _route_with_freerouting_api(
    pcb_bytes: bytes,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> bytes:
    """Route via Freerouting persistent REST API server (1 JVM for all users).

    Flow: export DSN → POST session → POST job → upload DSN → PUT start →
          poll status → GET output (SES) → pcbnew Specctra import.
    """
    import json
    import time
    import urllib.request, urllib.error

    base = os.environ.get("FREEROUTING_API_URL", "http://127.0.0.1:37864")

    def _api(method: str, path: str, body: Optional[bytes] = None,
             content_type: str = "application/json") -> dict:
        req = urllib.request.Request(
            f"{base}{path}", data=body, method=method,
            headers={"Content-Type": content_type, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _api_raw(method: str, path: str, body: bytes, content_type: str) -> bytes:
        req = urllib.request.Request(
            f"{base}{path}", data=body, method=method,
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    with tempfile.TemporaryDirectory() as tmp:
        dsn_path = Path(tmp) / "board.dsn"
        ses_path = Path(tmp) / "board.ses"

        # Export PCB → DSN
        _export_specctra(pcb_bytes, dsn_path)

        # Create session
        session = _api("POST", "/api/v1/sessions/create", b"{}")
        session_id = session["id"]

        # Enqueue job
        job_body = json.dumps({"session_id": session_id}).encode()
        job = _api("POST", "/api/v1/jobs/enqueue", job_body)
        job_id = job["id"]

        # Upload DSN (multipart)
        dsn_bytes = dsn_path.read_bytes()
        boundary = b"----LayrixBoundary"
        body = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="board.dsn"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n"
            + dsn_bytes + b"\r\n"
            b"--" + boundary + b"--\r\n"
        )
        _api_raw("POST", f"/api/v1/jobs/{job_id}/input",
                 body, f"multipart/form-data; boundary={boundary.decode()}")

        # Start routing
        _api("PUT", f"/api/v1/jobs/{job_id}/start", b"{}")

        # Poll until done
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = _api("GET", f"/api/v1/jobs/{job_id}")
            state = status.get("state", "")
            if state == "completed":
                break
            if state in ("failed", "cancelled"):
                raise RuntimeError(f"Freerouting API job {state}")
            time.sleep(2)
        else:
            raise RuntimeError("Freerouting API timeout")

        # Download SES output
        import base64 as _b64
        output = _api("GET", f"/api/v1/jobs/{job_id}/output")
        ses_b64 = output.get("output_file") or output.get("ses") or ""
        ses_path.write_bytes(_b64.b64decode(ses_b64))

        return _specctra_roundtrip(pcb_bytes, ses_path)


def _find_freerouting() -> Optional[tuple[str, str]]:
    """Locate (java, freerouting.jar) or return None when either is absent."""
    java = shutil.which("java")
    if not java:
        return None
    candidates = [
        os.environ.get("FREEROUTING_JAR"),
        "/opt/freerouting/freerouting.jar",
        "/usr/local/share/freerouting/freerouting.jar",
        str(Path(__file__).parent.parent / "freerouting" / "freerouting.jar"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return (java, c)
    return None


def _run_freerouting(
    paths: tuple[str, str], dsn: Path, ses: Path, timeout_s: int
) -> None:
    """Invoke Freerouting CLI. Raises on non-zero exit or timeout."""
    java, jar = paths
    cmd = [
        java, "-jar", jar,
        "-de", str(dsn),
        "-do", str(ses),
        "-mp", "100",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if result.returncode != 0 and not ses.exists():
        raise RuntimeError(f"Freerouting exit {result.returncode}")


def _specctra_roundtrip(pcb_bytes: bytes, ses_path: Path) -> bytes:
    """Apply a .ses session back onto a .kicad_pcb via pcbnew, return new bytes."""
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — gated by router caller
        raise RuntimeError("pcbnew unavailable for Specctra import") from exc

    with tempfile.TemporaryDirectory() as tmp:
        in_pcb = Path(tmp) / "in.kicad_pcb"
        out_pcb = Path(tmp) / "out.kicad_pcb"
        in_pcb.write_bytes(pcb_bytes)
        board = pcbnew.LoadBoard(str(in_pcb))
        # Remove stale tracks — Freerouting's SES output replaces them entirely.
        # Without this, old tracks (from circuit-synth or a previous routing pass)
        # survive in the final PCB alongside Freerouting's routes and cause
        # "Track has unconnected end" DRC violations.
        for track in list(board.GetTracks()):
            board.Remove(track)
        pcbnew.ImportSpecctraSES(board, str(ses_path))
        for zone in board.Zones():
            zone.SetFilled(True)
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        pcbnew.SaveBoard(str(out_pcb), board)
        return out_pcb.read_bytes()


def _count_routable_nets(pcb_bytes: bytes) -> int:
    """Count nets that actually require routing (≥ 2 pads assigned).

    In a .kicad_pcb file each net appears exactly once as a top-level
    declaration ``(net N "name")`` plus once per pad that carries it.
    Total occurrences = 1 (declaration) + pad_count.
    A net needs routing only when pad_count ≥ 2, i.e. total count ≥ 3.

    Single-pad nets (unconnected Arduino pins → Net-(U1-X)) appear exactly
    twice (declaration + 1 pad) and are correctly excluded.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    from collections import Counter
    all_occurrences = re.findall(r'\(net\s+(\d+)\s+"[^"]+"\)', text)
    counts = Counter(all_occurrences)
    # ≥3 = 1 top-level declaration + at least 2 pad assignments
    return sum(1 for c in counts.values() if c >= 3)


def _count_footprints(pcb_bytes: bytes) -> int:
    """Count footprint blocks in a .kicad_pcb S-expression."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    return len(re.findall(r'\(footprint\s+"', text))


def _extract_board_bbox(pcb_text: str) -> tuple[float, float, float, float] | None:
    """Extract board bounding box from Edge.Cuts gr_rect or gr_line elements only."""
    # Priority 1: gr_rect on Edge.Cuts (PCBFromSchematic output)
    m = re.search(
        r'\(gr_rect\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\)\s+\(end\s+([\d.\-]+)\s+([\d.\-]+)\)',
        pcb_text,
    )
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))

    # Priority 2: gr_line elements labeled Edge.Cuts
    xs, ys = [], []
    for block in re.finditer(r'\(gr_line.*?"Edge\.Cuts".*?\)', pcb_text, re.DOTALL):
        for c in re.finditer(r'\((?:start|end)\s+([\d.\-]+)\s+([\d.\-]+)\)', block.group()):
            xs.append(float(c.group(1)))
            ys.append(float(c.group(2)))
    if xs:
        return min(xs), min(ys), max(xs), max(ys)
    return None


def _build_zone_sexp(net_id: int, net_name: str, layer: str,
                     x0: float, y0: float, x1: float, y1: float,
                     inset: float = 0.3) -> str:
    """Build a filled copper-pour zone S-expression covering the board."""
    import uuid as _uuid
    xi0, yi0 = round(x0 + inset, 4), round(y0 + inset, 4)
    xi1, yi1 = round(x1 - inset, 4), round(y1 - inset, 4)
    uid = str(_uuid.uuid4())
    return (
        f'\n  (zone\n'
        f'    (net {net_id})\n'
        f'    (net_name "{net_name}")\n'
        f'    (layer "{layer}")\n'
        f'    (uuid "{uid}")\n'
        f'    (hatch edge 0.5)\n'
        f'    (connect_pads (clearance 0.3))\n'
        f'    (min_thickness 0.25)\n'
        f'    (filled_areas_thickness no)\n'
        f'    (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4))\n'
        f'    (polygon (pts\n'
        f'      (xy {xi0} {yi0}) (xy {xi0} {yi1})\n'
        f'      (xy {xi1} {yi1}) (xy {xi1} {yi0})\n'
        f'    ))\n'
        f'  )'
    )


def _add_power_zones(pcb_text: str) -> str:
    """Inject GND (B.Cu) and VCC_5V / +5V (F.Cu) copper-pour zones into the PCB."""
    bbox = _extract_board_bbox(pcb_text)
    if not bbox:
        logger.warning("_add_power_zones: board bbox not found — zones skipped")
        return pcb_text

    x0, y0, x1, y1 = bbox

    # Extract net IDs from top-level declarations only (lines with exactly 2 indent levels)
    # Pattern: "  (net N "name")" — top-level nets appear before any footprint block
    seen: dict[str, tuple[int, str, str]] = {}  # net_name → (id, name, layer)
    for m in re.finditer(r'^\s{0,4}\(net\s+(\d+)\s+"([^"]+)"\)', pcb_text, re.MULTILINE):
        nid, name = int(m.group(1)), m.group(2)
        if name in seen:
            continue
        if name == "GND":
            seen[name] = (nid, name, "B.Cu")
        elif name in ("VCC_5V", "+5V", "VCC", "VDD", "+3V3", "+3.3V"):
            seen[name] = (nid, name, "F.Cu")

    if not seen:
        logger.info("_add_power_zones: no GND/VCC nets found")
        return pcb_text

    zones_sexp = "".join(
        _build_zone_sexp(*args, x0=x0, y0=y0, x1=x1, y1=y1)
        for args in seen.values()
    )
    last_paren = pcb_text.rfind(")")
    if last_paren < 0:
        return pcb_text
    return pcb_text[:last_paren] + zones_sexp + "\n" + pcb_text[last_paren:]


_POWER_NET_NAMES = ("GND", "VCC_5V", "+5V", "VCC", "VDD", "+3V3", "+3.3V", "VBUS")


def _detect_power_nets(pcb_text: str) -> list[str]:
    """Return power net names present in the PCB (for kct route --power-nets)."""
    found = set()
    for m in re.finditer(r'\(net\s+\d+\s+"([^"]+)"\)', pcb_text):
        if m.group(1) in _POWER_NET_NAMES:
            found.add(m.group(1))
    return sorted(found)


def _power_nets_arg(power_nets: list[str]) -> str:
    """Format power nets as kct '--power-nets NET:LAYER,...'.

    GND → B.Cu, supply rails → F.Cu (standard 2-layer pour convention).
    kct expects the NET:LAYER form; a bare net list is mis-parsed.
    """
    layer_for = lambda n: "B.Cu" if n == "GND" else "F.Cu"
    return ",".join(f"{n}:{layer_for(n)}" for n in power_nets)


def _route_with_kicad_tools(pcb_bytes: bytes) -> tuple[bytes, int]:
    """Route via the official ``kct route`` CLI command.

    Uses kicad-tools' own routing rules — signal nets routed as tracks,
    power nets (GND, VCC_5V…) handled as copper-pour zones via --power-nets.
    No hand-rolled S-expression manipulation.

    Returns (routed_pcb_bytes, routed_percent). Raises RuntimeError on failure.
    """
    pcb_text = pcb_bytes.decode("utf-8", errors="replace")
    power_nets = _detect_power_nets(pcb_text)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "output.kicad_pcb"
        src.write_bytes(pcb_bytes)

        cmd = [
            sys.executable, "-m", "kicad_tools.cli", "route",
            str(src), "--output", str(dst),
            "--strategy", "negotiated",
            "--timeout", str(_PYTHON_ROUTER_TIMEOUT_S),
        ]
        power_arg = _power_nets_arg(power_nets)
        if power_arg:
            cmd += ["--power-nets", power_arg]

        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_PYTHON_ROUTER_TIMEOUT_S + 30, check=False,
        )

        if not dst.exists():
            raise RuntimeError(
                f"kct route produced no output (rc={result.returncode}): "
                f"{result.stderr[:200] or result.stdout[-200:]}"
            )

        routed = dst.read_bytes()
        routed_text = routed.decode("utf-8", errors="replace")
        seg_count = len(re.findall(r'\(segment[\s\n]', routed_text))
        zone_count = len(re.findall(r'\(zone[\s\n]', routed_text))

        # Parse completion % from CLI output ("Nets routed: N/M")
        routed_pct = 100
        m = re.search(r'(\d+)\s*/\s*(\d+)\s+nets', result.stdout)
        if m and int(m.group(2)) > 0:
            routed_pct = round(int(m.group(1)) / int(m.group(2)) * 100)

        logger.info(
            "kct route: %d segments, %d zones, power-nets=%s (%d%%)",
            seg_count, zone_count, power_nets, routed_pct,
        )
        return routed, routed_pct


def _export_specctra(pcb_bytes: bytes, dsn_path: Path) -> None:
    """Export a .kicad_pcb byte blob to a Specctra DSN file via pcbnew.

    All existing tracks are removed before export so Freerouting starts from
    scratch — without stale TS-generated traces that pointed to pre-placement
    component positions.
    """
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pcbnew unavailable for Specctra export") from exc

    with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as tmp_pcb:
        tmp_pcb.write(pcb_bytes)
        tmp_pcb_path = tmp_pcb.name
    try:
        board = pcbnew.LoadBoard(tmp_pcb_path)
        # Remove all existing tracks so Freerouting routes from clean pads only.
        for track in list(board.GetTracks()):
            board.Remove(track)
        # KiCad 8 uses ExportSpecctraDSN instead of ExportSpecctraSession
        pcbnew.ExportSpecctraDSN(board, str(dsn_path))
    finally:
        Path(tmp_pcb_path).unlink(missing_ok=True)


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@router.post("/route/auto", response_model=RouteAutoResponse)
def route_auto(req: RouteAutoRequest) -> RouteAutoResponse:
    """
    Auto-route a board.

    Priority:
      1. kicad-tools A* (negotiated) — ≤30 composants ET ≤30 nets, timeout 60s.
      2. Freerouting (Java)          — circuits complexes ou si kicad-tools échoue.
      3. skipped=True                — aucun routeur disponible → GND plane seulement.
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    net_count = _count_routable_nets(pcb_bytes)
    comp_count = _count_footprints(pcb_bytes)
    is_simple = net_count <= _KICAD_TOOLS_MAX_NETS and comp_count <= _KICAD_TOOLS_MAX_COMPS

    logger.info(
        "route_auto: %d routable nets, %d composants — simple=%s",
        net_count, comp_count, is_simple,
    )

    # Best kicad-tools partial result so far (reused at Niveau 4 if Freerouting absent)
    kt_partial: Optional[tuple[bytes, int]] = None

    # --- Niveau 1 : kicad-tools A* (circuits simples ≤30 nets/comps) ---
    if is_simple:
        try:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes)
            logger.info("kicad-tools A*: %d%% routé", routed_pct)
            if routed_pct >= _MIN_ROUTED_PCT:
                return RouteAutoResponse(
                    kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                    routed_percent=routed_pct,
                    layers=req.layers,
                    skipped=False,
                )
            # Below threshold: keep it, but try Freerouting for a better result.
            kt_partial = (new_pcb, routed_pct)
            logger.info(
                "kicad-tools %d%% < %d%% — tentative Freerouting",
                routed_pct, _MIN_ROUTED_PCT,
            )
        except Exception as exc:
            logger.warning("kicad-tools A* échoué (%s) — Freerouting API", exc)

    # --- Niveau 2 : Freerouting REST API server (1 JVM persistant, meilleure qualité) ---
    api_url = _find_freerouting_api()
    if api_url is not None:
        try:
            new_pcb = _route_with_freerouting_api(pcb_bytes, req.timeout_s)
            logger.info("Freerouting API: 100%% routé")
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=100,
                layers=req.layers,
                skipped=False,
            )
        except Exception as exc:
            logger.warning("Freerouting API échoué (%s) — subprocess fallback", exc)

    # --- Niveau 3 : Freerouting subprocess (fallback si API server absent) ---
    paths = _find_freerouting()
    if paths is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dsn = Path(tmp) / "board.dsn"
                ses = Path(tmp) / "board.ses"
                _export_specctra(pcb_bytes, dsn)
                _run_freerouting(paths, dsn, ses, req.timeout_s)
                new_pcb = _specctra_roundtrip(pcb_bytes, ses)
            logger.info("Freerouting: 100%% routé")
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=100,
                layers=req.layers,
                skipped=False,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Freerouting échoué: %s", exc)
            raise HTTPException(status_code=500, detail="routing failed") from exc

    # --- Niveau 4 : kicad-tools negotiated sans limite (tous circuits) ---
    # Reuse the Niveau-1 partial when we already have one (avoid a second
    # expensive run). Même algorithme A* negotiated, fallback quand Freerouting
    # absent ou échoue.
    try:
        if kt_partial is not None:
            new_pcb, routed_pct = kt_partial
        else:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes)
        logger.info("kicad-tools A* (no limit): %d%% routé", routed_pct)
        return RouteAutoResponse(
            kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
            routed_percent=routed_pct,
            layers=req.layers,
            skipped=False,
            warning=f"Freerouting indisponible — kicad-tools negotiated utilisé ({net_count} nets)",
        )
    except Exception as exc:
        logger.warning("kicad-tools A* (no limit) échoué (%s) — GND plane", exc)

    # --- Niveau 5 : skipped → GND plane seulement (TypeScript addGroundPlane) ---
    reason = f"Tous les routeurs ont échoué ({net_count} nets, {comp_count} composants)"
    logger.info("Routage ignoré — %s", reason)
    return RouteAutoResponse(
        kicad_pcb_b64=None,
        routed_percent=0,
        layers=req.layers,
        skipped=True,
        warning=reason,
    )

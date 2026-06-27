"""
Cirqix KiCad Service — FastAPI headless
Endpoints actifs (tous via routers/) :
  /health
  /schematic/execute · /schematic/generate · /schematic/validate-symbols
  /pcb/generate
  /place/auto · /erc · /route/auto · /drc/auto · /export/all · /simulate/auto
"""

import os
import sys as _sys

# Use Cirqix-patched copies of circuit_synth and kicad_tools (in services/kicad/).
# These contain bug fixes and extensions not in the original packages.
# Priority: local patched copy → installed package.
# PYTHONPATH is updated too so CLI subprocesses (`python -m kicad_tools.cli route`
# in routers/routing.py and tools/placement.py) inherit the patched copies — an
# in-process sys.path insert does not propagate to child processes. In Docker
# kicad_tools is pip-installed (editable), so subprocesses already resolve it;
# prepending the same source dir here is redundant but harmless.
_here = os.path.dirname(__file__)
_patched_dirs: list[str] = []
for _lib in ["circuit_synth/src", "kicad-tools/src"]:
    _lib_path = os.path.join(_here, _lib)
    if os.path.isdir(_lib_path):
        if _lib_path not in _sys.path:
            _sys.path.insert(0, _lib_path)
        _patched_dirs.append(_lib_path)

if _patched_dirs:
    _existing_pp = os.environ.get("PYTHONPATH", "")
    _pp_parts = [p for p in (_existing_pp.split(os.pathsep) if _existing_pp else []) if p]
    os.environ["PYTHONPATH"] = os.pathsep.join(
        _patched_dirs + [p for p in _pp_parts if p not in _patched_dirs]
    )

# Ensure KiCad symbol library path is set BEFORE importing any router that probes it.
# Priority: env var → repo-local kicad-symbols/ → Windows KiCad install.
if not os.environ.get("KICAD_SYMBOL_DIR"):
    _candidates = [
        os.path.join(os.path.dirname(__file__), "kicad-symbols"),
        r"C:\Program Files\KiCad\10.99\share\kicad\symbols",
        r"C:\Program Files\KiCad\9.0\share\kicad\symbols",
        r"C:\Program Files\KiCad\8.0\share\kicad\symbols",
        "/usr/share/kicad/symbols",  # Linux/Docker
    ]
    for _dir in _candidates:
        if os.path.isdir(_dir):
            os.environ["KICAD_SYMBOL_DIR"] = _dir
            break

if not os.environ.get("KICAD_FOOTPRINT_DIR"):
    _fp_candidates = [
        r"C:\Program Files\KiCad\10.99\share\kicad\footprints",
        r"C:\Program Files\KiCad\9.0\share\kicad\footprints",
        r"C:\Program Files\KiCad\8.0\share\kicad\footprints",
        "/usr/share/kicad/footprints",  # Linux/Docker
    ]
    for _dir in _fp_candidates:
        if os.path.isdir(_dir):
            os.environ["KICAD_FOOTPRINT_DIR"] = _dir
            break

# Ensure kicad-cli is in PATH so PCBFromSchematic uses it for netlist export.
# Without kicad-cli, export_netlist falls back to pure Python extraction which
# does NOT resolve hierarchical labels from circuit_synth schematics — causing
# R1.pin2 to become Net-(R1-2) instead of DHT_DATA.
import shutil as _shutil
if not _shutil.which("kicad-cli"):
    _cli_candidates = [
        r"C:\Program Files\KiCad\10.99\bin",
        r"C:\Program Files\KiCad\9.0\bin",
        r"C:\Program Files\KiCad\8.0\bin",
        "/usr/bin",        # Linux/Docker (kicad-cli in PATH by default)
        "/usr/local/bin",
    ]
    import os as _os
    for _bin in _cli_candidates:
        if _os.path.isfile(_os.path.join(_bin, "kicad-cli")) or \
           _os.path.isfile(_os.path.join(_bin, "kicad-cli.exe")):
            _os.environ["PATH"] = _bin + _os.pathsep + _os.environ.get("PATH", "")
            break

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

# Import pcbnew (disponible dans le container KiCad)
try:
    import pcbnew  # noqa: F401
    PCBNEW_AVAILABLE = True
except ImportError:
    PCBNEW_AVAILABLE = False
    logging.warning("pcbnew non disponible — mode simulation activé")

app = FastAPI(
    title="Cirqix KiCad Service",
    version="1.0.0",
    description="Microservice headless KiCad : placement, routage Freerouting, DRC, export Gerbers",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schematic router — /schematic/execute · /schematic/generate · /schematic/validate-symbols
from routers.schematic import router as schematic_router  # noqa: E402
app.include_router(schematic_router)

# PCB router — /pcb/generate
from routers.pcb import router as pcb_router  # noqa: E402
app.include_router(pcb_router)

# Placement router — /place (explicit) + /place/auto (grid algorithm, base64 I/O)
from routers.placement import router as placement_router  # noqa: E402
app.include_router(placement_router)

# ERC router — /erc (kicad-cli sch erc with auto-fix loop)
from routers.erc import router as erc_router  # noqa: E402
app.include_router(erc_router)

# Routing router — /route (path-based legacy) + /route/auto (base64 I/O, fallback skip)
from routers.routing import router as routing_router  # noqa: E402
app.include_router(routing_router)

from routers.reasoning import router as reasoning_router  # noqa: E402
app.include_router(reasoning_router)

# DRC router — /drc/auto (base64 I/O, kicad-cli pcb drc with auto-fix loop)
from routers.drc import router as drc_router  # noqa: E402
app.include_router(drc_router)

# Export router — /export/all (Gerbers + drill + CPL, b64 zip output, fallback skip)
from routers.export import router as export_router  # noqa: E402
app.include_router(export_router)

# Simulate router — /simulate/auto (kicad-cli → ngspice, base64 I/O, fallback demo)
from routers.simulate import router as simulate_router  # noqa: E402
app.include_router(simulate_router)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "pcbnew": PCBNEW_AVAILABLE,
        "version": "1.0.0",
    }


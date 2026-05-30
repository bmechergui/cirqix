"""
Layrix KiCad Service — FastAPI headless
Endpoints actifs (tous via routers/) :
  /health · /schematic/generate · /schematic/execute
  /place/auto · /erc · /route/auto · /drc/auto · /export/all · /simulate/auto
"""

import os

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
    title="Layrix KiCad Service",
    version="1.0.0",
    description="Microservice headless KiCad : placement, routage Freerouting, DRC, export Gerbers",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# KiCad file generator router — JSON schema → .kicad_sch (circuit_synth) + .kicad_pcb (Python S-expr)
from routers.kicad_gen import router as kicad_gen_router  # noqa: E402
app.include_router(kicad_gen_router)

# Placement router — /place (explicit) + /place/auto (grid algorithm, base64 I/O)
from routers.placement import router as placement_router  # noqa: E402
app.include_router(placement_router)

# ERC router — /erc (kicad-cli sch erc with auto-fix loop)
from routers.erc import router as erc_router  # noqa: E402
app.include_router(erc_router)

# Routing router — /route (path-based legacy) + /route/auto (base64 I/O, fallback skip)
from routers.routing import router as routing_router  # noqa: E402
app.include_router(routing_router)

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


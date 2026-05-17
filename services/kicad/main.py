"""
Layrix KiCad Service — FastAPI headless
Routes : /health, /place, /route, /drc, /drc/fix, /export/gerbers, /export/step, /export/bom, /simulate
         /circuit-synth/generate (JSON schema → .kicad_sch + .kicad_pcb natifs)
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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
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

# ============================================================
# Modèles Pydantic
# ============================================================

class RoutingRequest(BaseModel):
    pcb_path: str
    output_path: str
    timeout: int = Field(default=300, ge=30, le=600)

class DRCRequest(BaseModel):
    pcb_path: str

class DRCFix(BaseModel):
    type: str  # "widen_track" | "add_via" | "refill_zones" | "apply_teardrops"
    params: dict = {}

class DRCFixRequest(BaseModel):
    pcb_path: str
    fixes: list[DRCFix]
    output_path: str

class ExportRequest(BaseModel):
    pcb_path: str
    output_dir: str
    project_id: str

class SimulationRequest(BaseModel):
    netlist_path: str
    sim_type: str = "transient"  # "dc" | "transient" | "ac" | "noise"
    output_dir: str

# Circuit-Synth router — JSON schema → native KiCad files
from routers.circuit_synth import router as circuit_synth_router  # noqa: E402
app.include_router(circuit_synth_router)

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

# ============================================================
# Routes
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "pcbnew": PCBNEW_AVAILABLE,
        "version": "1.0.0",
    }

@app.post("/route")
def route(req: RoutingRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.routing import route_with_freerouting
    return route_with_freerouting(req.pcb_path, req.output_path, req.timeout)

@app.post("/drc")
def drc(req: DRCRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.drc import run_drc
    return run_drc(req.pcb_path)

@app.post("/drc/fix")
def drc_fix(req: DRCFixRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.drc import apply_drc_fixes
    return apply_drc_fixes(req.pcb_path, [f.model_dump() for f in req.fixes], req.output_path)

@app.post("/export/gerbers")
def export_gerbers(req: ExportRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.export import export_gerbers as _export
    return _export(req.pcb_path, req.output_dir)

@app.post("/export/step")
def export_step(req: ExportRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.export import export_step as _export
    return _export(req.pcb_path, req.output_dir)

@app.post("/export/bom")
def export_bom(req: ExportRequest):
    if not PCBNEW_AVAILABLE:
        raise HTTPException(status_code=503, detail="pcbnew non disponible")
    from tools.export import export_bom as _export
    return _export(req.pcb_path, req.output_dir)

@app.post("/simulate")
def simulate(req: SimulationRequest):
    from tools.simulation import run_simulation
    return run_simulation(req.netlist_path, req.sim_type, req.output_dir)

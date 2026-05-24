"""FastAPI router — POST /simulate/auto

Accepts a base64-encoded .kicad_sch, exports a SPICE netlist via kicad-cli,
runs ngspice in batch mode, and returns structured waveform vectors.
Falls back to synthetic demo waveforms when ngspice is unavailable.
"""
import base64
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tools.simulation import run_simulation_from_content

router = APIRouter(prefix="/simulate", tags=["simulate"])


class SimulateAutoRequest(BaseModel):
    kicad_sch_b64: str = Field(..., description="Base64-encoded .kicad_sch content")
    sim_type: str = Field(
        default="transient",
        description="SPICE analysis type: 'transient' | 'dc' | 'ac'",
    )


class SimulationVectorOut(BaseModel):
    name: str
    unit: str
    time: list[float]
    values: list[float]


class SimulateAutoResponse(BaseModel):
    status: str
    sim_type: str
    vectors: list[SimulationVectorOut]


@router.post("/auto", response_model=SimulateAutoResponse)
def simulate_auto(req: SimulateAutoRequest) -> dict[str, Any]:
    """Export SPICE netlist from .kicad_sch and run ngspice.

    Falls back gracefully to demo waveforms when kicad-cli or ngspice
    are unavailable (e.g. local dev without KiCad Docker).
    """
    try:
        sch_content = base64.b64decode(req.kicad_sch_b64).decode("utf-8")
    except Exception:
        return {
            "status": "error",
            "sim_type": req.sim_type,
            "vectors": [],
        }

    return run_simulation_from_content(sch_content, req.sim_type)

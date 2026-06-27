"""
Cirqix — Router placement
POST /place         → placement explicite (coordonnées fournies par l'agent)
POST /place/auto    → auto-placement grille (I/O base64, pas de filesystem partagé)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["placement"])


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------

class ComponentPlacement(BaseModel):
    ref: str
    x_mm: float
    y_mm: float
    rotation: float = 0.0
    side: str = "front"  # "front" | "back"


class PlacementRequest(BaseModel):
    """Placement explicite — coordonnées fournies par l'agent."""
    pcb_path: str
    components: list[ComponentPlacement]
    output_path: str


class PlacementResponse(BaseModel):
    status: str
    path: str
    placed: int
    errors: list[str] = []


class AutoPlacementRequest(BaseModel):
    """Auto-placement grille — I/O base64, aucun filesystem partagé requis."""
    kicad_pcb_b64: str = Field(..., description="Contenu .kicad_pcb encodé base64")
    board_width_mm: float = Field(default=100.0, ge=10.0, le=500.0)
    board_height_mm: float = Field(default=80.0, ge=10.0, le=500.0)


class AutoPlacementResponse(BaseModel):
    kicad_pcb_b64: str
    placed_count: int
    positions: list[dict]  # [{ref, x_mm, y_mm}]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/place", response_model=PlacementResponse)
def place(req: PlacementRequest) -> PlacementResponse:
    """
    Placement explicite : positionne les footprints aux coordonnées fournies.
    Requiert pcbnew + accès filesystem.
    """
    try:
        from tools.placement import place_components
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        result = place_components(
            req.pcb_path,
            [c.model_dump() for c in req.components],
            req.output_path,
        )
    except Exception as exc:
        logger.exception("Erreur place_components: %s", exc)
        raise HTTPException(status_code=500, detail="placement failed") from exc

    return PlacementResponse(**result)


@router.post("/place/auto", response_model=AutoPlacementResponse)
def place_auto(req: AutoPlacementRequest) -> AutoPlacementResponse:
    """
    Auto-placement grille : calcule automatiquement les positions de tous les footprints.
    I/O base64 — aucun filesystem partagé requis entre l'agent et le service.
    """
    try:
        from tools.placement import auto_place
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        result = auto_place(
            kicad_pcb_b64=req.kicad_pcb_b64,
            board_width_mm=req.board_width_mm,
            board_height_mm=req.board_height_mm,
        )
    except Exception as exc:
        logger.exception("Erreur auto_place: %s", exc)
        raise HTTPException(status_code=500, detail="auto-placement failed") from exc

    return AutoPlacementResponse(**result)

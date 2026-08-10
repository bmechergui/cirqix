"""
Cirqix — Router placement
POST /place         → placement explicite (coordonnées fournies par l'agent)
POST /place/auto    → auto-placement grille (I/O base64, pas de filesystem partagé)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["placement"])

_PCBNEW_RUNNER = Path(__file__).resolve().parent.parent / "tools" / "placement_pcbnew_runner.py"
_PCBNEW_TIMEOUT_S: int = 120


class _PcbnewUnavailable(RuntimeError):
    """pcbnew absent dans l'enfant — 503, pas 500 : c'est un défaut
    d'environnement (KiCad non installé), pas un défaut de la requête."""


def _place_components_isolated(
    pcb_path: str, components: list[dict[str, Any]], output_path: str
) -> dict[str, Any]:
    """Exécute ``place_components`` dans un processus enfant borné.

    Voir le commentaire dans ``place`` pour le pourquoi. Le résultat transite
    par un fichier JSON : rien ne dépend de la sortie standard de l'enfant, que
    pcbnew pollue de ses propres messages.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result_path = Path(tmp) / "result.json"
        payload = json.dumps({
            "pcb_path": pcb_path,
            "components": components,
            "output_path": output_path,
            "result_path": str(result_path),
        })
        proc = subprocess.run(
            [sys.executable, str(_PCBNEW_RUNNER), payload],
            capture_output=True, text=True,
            timeout=_PCBNEW_TIMEOUT_S, check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "")[:500]
            if "pcbnew non disponible" in stderr or "No module named 'pcbnew'" in stderr:
                raise _PcbnewUnavailable(
                    "pcbnew non disponible — KiCad doit être installé"
                )
            raise RuntimeError(f"placement enfant échoué (rc={proc.returncode}): {stderr}")
        if not result_path.exists():
            raise RuntimeError("placement enfant n'a produit aucun résultat")
        return json.loads(result_path.read_text(encoding="utf-8"))


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
    # `place_components` importe `pcbnew`, dont l'état C++ global n'est PAS
    # thread-safe, et ce handler est déclaré en `def` : uvicorn l'exécute dans
    # son threadpool, donc deux `/place` concurrents le partagent sur le même
    # worker. L'appel part donc dans un processus enfant borné.
    # L'appel à pcbnew est INDIRECT (via tools.placement) — c'est précisément
    # pourquoi un grep de « pcbnew » dans routers/ ne le voit pas.
    try:
        result = _place_components_isolated(
            req.pcb_path,
            [c.model_dump() for c in req.components],
            req.output_path,
        )
    except _PcbnewUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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

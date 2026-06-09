"""FastAPI router — agent Reasoner (sauvetage de routage agentique).

POST /reason/auto — l'orchestrateur l'appelle EXPLICITEMENT quand le routage
classique (`/route/auto`) laisse des nets bloqués. Étape visible dans l'UI/SSE.

- reasoner LLM (PCBReasoningAgent + Claude Haiku) si ANTHROPIC_API_KEY dispo
- sinon `kct reason --auto-route` (heuristique, sans LLM)

Renvoie le board + le routed_percent + le log des actions IA (pour affichage).
"""
from __future__ import annotations

import base64
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tools import kct_route, reasoning

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reasoning"])

_REASON_TIMEOUT_S = 120


class ReasonAutoRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb routé partiellement, base64")
    max_steps: int = Field(default=15, ge=1, le=40,
                           description="legacy — utilisé uniquement par la voie heuristique/full-LLM")
    max_iterations: int = Field(default=3, ge=1, le=5,
                                description="itérations placement-feedback (déplace → reroute)")


class ReasonAutoResponse(BaseModel):
    kicad_pcb_b64: Optional[str] = None
    routed_percent: int = 0
    steps: list[str] = Field(default_factory=list)  # log des actions IA (UI/SSE)
    used_llm: bool = False
    warning: Optional[str] = None


@router.post("/reason/auto", response_model=ReasonAutoResponse)
def reason_auto(req: ReasonAutoRequest) -> ReasonAutoResponse:
    """Débloque le routage via le reasoner (LLM Claude ou heuristique)."""
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    # Voie 1 : boucle placement-feedback (le LLM déplace, kct route reroute).
    # Validée sur examples/stm32-validation : 22% → 92% en déplaçant D1/R2.
    if reasoning.available():
        try:
            out_bytes, pct, steps = reasoning.rescue_with_placement_feedback(
                pcb_bytes,
                route_fn=kct_route.route_kct,
                max_iterations=req.max_iterations,
            )
            logger.info("reasoner placement-feedback: %d%% (%d étapes)", pct, len(steps))
            return ReasonAutoResponse(
                kicad_pcb_b64=base64.b64encode(out_bytes).decode("ascii"),
                routed_percent=pct, steps=steps, used_llm=True,
            )
        except Exception as exc:
            logger.warning("reasoner placement-feedback échoué (%s) — heuristique", exc)

    # Voie 2 : heuristique officielle `kct reason --auto-route` (sans LLM)
    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        board.write_bytes(pcb_bytes)
        r = subprocess.run(
            [sys.executable, "-m", "kicad_tools.cli", "reason",
             str(board), "-o", str(board), "--auto-route"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_REASON_TIMEOUT_S, check=False,
        )
        m = re.findall(r'Routed:\s*(\d+)\s*/\s*(\d+)\s+nets', r.stdout)
        pct = round(int(m[-1][0]) / int(m[-1][1]) * 100) if m and int(m[-1][1]) else 0
        return ReasonAutoResponse(
            kicad_pcb_b64=base64.b64encode(board.read_bytes()).decode("ascii"),
            routed_percent=pct,
            steps=[f"Routage heuristique des nets prioritaires (kct reason --auto-route) → {pct}%"],
            used_llm=False,
            warning="ANTHROPIC_API_KEY absente — reasoner LLM indisponible, heuristique utilisée",
        )

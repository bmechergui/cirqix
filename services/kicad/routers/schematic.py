"""
Cirqix — Schematic HTTP endpoints
POST /schematic/execute          → execute circuit_synth Python code → .kicad_sch
POST /schematic/generate         → JSON schema → .kicad_sch
POST /schematic/validate-symbols → validate KiCad symbol ids
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tools.schematic import (
    SchemaComponent,
    SchemaNet,
    generate_schematic,
    execute_cs_code,
    validate_symbols,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schematic", tags=["schematic"])


# ============================================================
# HTTP models
# ============================================================

class SchematicRequest(BaseModel):
    components: list[SchemaComponent]
    nets: list[str]
    connections: list[SchemaNet] = Field(default_factory=list)
    board_width_mm: float = Field(default=50.0, ge=10.0, le=200.0)
    board_height_mm: float = Field(default=50.0, ge=10.0, le=200.0)
    project_id: str = ""


class SchematicResponse(BaseModel):
    success: bool
    kicad_sch_content: Optional[str] = None
    error: Optional[str] = None


class ExecuteRequest(BaseModel):
    code: str
    project_id: str = ""
    board_width_mm: float = Field(default=50.0, ge=10.0, le=200.0)
    board_height_mm: float = Field(default=50.0, ge=10.0, le=200.0)


class ExecuteResponse(BaseModel):
    success: bool
    kicad_sch_content: Optional[str] = None
    kicad_pcb_content: Optional[str] = None
    error: Optional[str] = None


class SymbolValidationResult(BaseModel):
    ref: str
    original_symbol: str
    validated_symbol: str
    corrected: bool


class ValidateSymbolsRequest(BaseModel):
    components: list[SchemaComponent]


class ValidateSymbolsResponse(BaseModel):
    results: list[SymbolValidationResult]
    corrected_components: list[SchemaComponent]
    has_corrections: bool


# ============================================================
# Endpoints
# ============================================================

@router.post("/execute", response_model=ExecuteResponse)
def execute_circuit_synth_code(req: ExecuteRequest) -> ExecuteResponse:
    """Execute circuit_synth Python code → .kicad_sch + .kicad_pcb."""
    if not req.code.strip():
        return ExecuteResponse(success=False, error="Empty code")
    try:
        sch, pcb = execute_cs_code(req.code, req.project_id, req.board_width_mm, req.board_height_mm)
        return ExecuteResponse(success=True, kicad_sch_content=sch, kicad_pcb_content=pcb)
    except Exception as exc:
        logger.error("execute failed: %s", exc)
        return ExecuteResponse(success=False, error=str(exc))


@router.post("/generate", response_model=SchematicResponse)
def generate(req: SchematicRequest) -> SchematicResponse:
    """JSON schema → .kicad_sch (circuit_synth pip → S-expr fallback)."""
    if not req.components:
        return SchematicResponse(success=False, error="No components in schema")
    try:
        sch_content = generate_schematic(
            req.components, req.connections, req.nets,
            req.board_width_mm, req.board_height_mm, req.project_id,
        )
        if sch_content:
            return SchematicResponse(success=True, kicad_sch_content=sch_content)
        return SchematicResponse(success=False, error="All Python schematic paths failed — TypeScript S-expr fallback")
    except Exception as exc:
        logger.error("generate schematic failed: %s", exc)
        return SchematicResponse(success=False, error=str(exc))


@router.post("/validate-symbols", response_model=ValidateSymbolsResponse)
def validate_symbols_endpoint(req: ValidateSymbolsRequest) -> ValidateSymbolsResponse:
    """Validate KiCad symbol ids against local .kicad_sym libraries."""
    results_raw, corrected, has_corrections = validate_symbols(req.components)
    results = [SymbolValidationResult(**r) for r in results_raw]
    return ValidateSymbolsResponse(
        results=results,
        corrected_components=corrected,
        has_corrections=has_corrections,
    )

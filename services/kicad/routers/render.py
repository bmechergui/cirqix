"""FastAPI router — rendu PNG / 3D d'un board par `kicad-cli pcb render`.

POST /render/auto prend un `.kicad_pcb` en base64 et rend UNE image PNG,
produite par le lanceur de rayons de KiCad (le même que la vue 3D de l'éditeur).
Rien n'est dessiné ici : ce que voit l'utilisateur est ce que KiCad rend.

Vues : `side` (top/bottom/left/right/front/back) en projection orthogonale,
ou `perspective=true` + `rotate="x,y,z"` pour une vue 3D — l'isométrique de
KiCad est `-45,0,45`.

FAIL CLOSED : pas de kicad-cli → 503 ; base64 illisible → 422 ; rendu en
échec, fichier absent ou qui n'est pas un PNG → 500 avec l'extrait de stderr.
Jamais d'image de remplacement : une vignette grise passerait pour un rendu.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["render"])

_RENDER_TIMEOUT_S: int = 180
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Un PNG plus petit que ça n'est pas un rendu de carte : c'est un cadre vide.
_TAILLE_PNG_MINIMALE = 1024
_ROTATE_RE = re.compile(r"^-?\d{1,3}(?:\.\d+)?,-?\d{1,3}(?:\.\d+)?,-?\d{1,3}(?:\.\d+)?$")

Side = Literal["top", "bottom", "left", "right", "front", "back"]
Quality = Literal["basic", "high"]
Background = Literal["default", "transparent", "opaque"]


class RenderRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encodé en base64")
    side: Side = "top"
    rotate: Optional[str] = Field(
        default=None, description="Rotation 'X,Y,Z' en degrés — '-45,0,45' = isométrique",
    )
    perspective: bool = False
    zoom: float = Field(default=1.0, ge=0.1, le=10.0)
    quality: Quality = "basic"
    width: int = Field(default=1600, ge=64, le=4096)
    height: int = Field(default=900, ge=64, le=4096)
    background: Background = "transparent"
    floor: bool = False

    @field_validator("rotate")
    @classmethod
    def _rotation_lisible(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _ROTATE_RE.match(v):
            raise ValueError("rotate doit être 'X,Y,Z' en degrés, ex. '-45,0,45'")
        return v


class RenderResponse(BaseModel):
    png_b64: str
    width: int
    height: int
    duration_ms: int
    side: str
    rotate: Optional[str]
    perspective: bool
    quality: str


def _find_kicad_cli() -> Optional[str]:
    override = os.environ.get("KICAD_CLI_PATH")
    if override and Path(override).exists():
        return override
    return shutil.which("kicad-cli")


def construire_commande(cli: str, req: RenderRequest, entree: Path, sortie: Path) -> list[str]:
    """La ligne de commande exacte — une fonction pure, pour la tester sans rendre."""
    cmd = [
        cli, "pcb", "render",
        "--side", req.side,
        "--quality", req.quality,
        "--background", req.background,
        "--width", str(req.width),
        "--height", str(req.height),
        "--zoom", str(req.zoom),
    ]
    if req.rotate:
        cmd += ["--rotate", req.rotate]
    if req.perspective:
        cmd.append("--perspective")
    if req.floor:
        cmd.append("--floor")
    cmd += ["-o", str(sortie), str(entree)]
    return cmd


def dimensions_png(data: bytes) -> tuple[int, int]:
    """(largeur, hauteur) lues dans l'en-tête IHDR ; lève si ce n'est pas un PNG."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    largeur, hauteur = struct.unpack(">II", data[16:24])
    return int(largeur), int(hauteur)


def verifier_png(data: bytes) -> tuple[int, int]:
    """Un rendu recevable : signature PNG, en-tête IHDR, et une taille de vraie image."""
    try:
        dims = dimensions_png(data)
    except ValueError as exc:
        raise RuntimeError("kicad-cli did not produce a PNG") from exc
    if len(data) < _TAILLE_PNG_MINIMALE:
        raise RuntimeError(f"rendered PNG is only {len(data)} bytes — not a board render")
    return dims


def _decoder_board(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"kicad_pcb_b64 is not valid base64: {exc}") from exc
    if not data.strip().startswith(b"(kicad_pcb"):
        raise HTTPException(status_code=422, detail="kicad_pcb_b64 does not decode to a .kicad_pcb")
    return data


def rendre(cli: str, req: RenderRequest, pcb: bytes) -> tuple[bytes, int, int, int]:
    """Exécute kicad-cli dans un dossier jetable ; rend (png, largeur, hauteur, durée ms)."""
    with tempfile.TemporaryDirectory(prefix="cirqix-render-") as tmp:
        entree = Path(tmp) / "board.kicad_pcb"
        sortie = Path(tmp) / "render.png"
        entree.write_bytes(pcb)
        debut = time.monotonic()
        try:
            result = subprocess.run(
                construire_commande(cli, req, entree, sortie),
                # errors="replace" : un stderr non UTF-8 (diagnostics Cairo/Freetype)
                # ne doit pas lever UnicodeDecodeError hors du contrat fail-closed.
                capture_output=True, text=True, errors="replace", timeout=_RENDER_TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"kicad-cli pcb render timed out after {_RENDER_TIMEOUT_S}s") from exc
        duree_ms = int((time.monotonic() - debut) * 1000)
        if result.returncode != 0:
            extrait = (result.stderr or result.stdout or "").strip()[-400:]
            raise RuntimeError(f"kicad-cli pcb render failed (rc={result.returncode}): {extrait}")
        if not sortie.exists():
            raise RuntimeError("kicad-cli pcb render exited 0 but wrote no file")
        data = sortie.read_bytes()
        largeur, hauteur = verifier_png(data)
        return data, largeur, hauteur, duree_ms


@router.post("/render/auto", response_model=RenderResponse)
def render_auto(req: RenderRequest) -> RenderResponse:
    pcb = _decoder_board(req.kicad_pcb_b64)
    cli = _find_kicad_cli()
    if not cli:
        raise HTTPException(status_code=503, detail="kicad-cli not available — no render possible")
    try:
        png, largeur, hauteur, duree_ms = rendre(cli, req, pcb)
    except RuntimeError as exc:
        logger.error("render/auto: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info(
        "render/auto: side=%s rotate=%s perspective=%s quality=%s %dx%d en %d ms",
        req.side, req.rotate, req.perspective, req.quality, largeur, hauteur, duree_ms,
    )
    return RenderResponse(
        png_b64=base64.b64encode(png).decode("ascii"),
        width=largeur, height=hauteur, duration_ms=duree_ms,
        side=req.side, rotate=req.rotate, perspective=req.perspective, quality=req.quality,
    )

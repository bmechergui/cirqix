"""FastAPI router — rendu PNG / 3D (`kicad-cli pcb render`) et modèle GLB (`kicad-cli pcb export glb`) d'un board.

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


# ---------------------------------------------------------------------------
# Modèle 3D interactif — `kicad-cli pcb export glb`
# ---------------------------------------------------------------------------

_GLB_SIGNATURE = b"glTF"
_GLB_TIMEOUT_S: int = 120


class GlbRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encodé en base64")
    include_tracks: bool = True
    include_pads: bool = True
    include_zones: bool = True
    # ⚠️ Le VERNIS et la SERIGRAPHIE font le rendu du visualiseur 3D de KiCad
    # (demande du 2026-09-14, captures a l appui). Mesure sur carte-01 : le
    # masque sort en vert SEMI-TRANSPARENT (alpha 0,83, alphaMode BLEND) — on
    # voit donc les pistes au travers, comme dans KiCad — et la serigraphie en
    # blanc (alpha 0,9). Coût : +43 ko et zero seconde (1,35 s contre 1,46 s).
    include_silkscreen: bool = True
    include_soldermask: bool = True
    # ⚠️ L image n embarque AUCUN modèle 3D de composant (0 dans
    # /usr/share/kicad/3dmodels, mesuré le 2026-09-14) : le GLB porte la carte,
    # les pistes, les pastilles et les zones — la géométrie réelle du board.
    components: bool = True


class GlbResponse(BaseModel):
    glb_b64: str
    bytes: int
    duration_ms: int
    # Honnetete du modele : combien de composants DECLARENT un modele 3D dans
    # le board, et combien de ces fichiers existent sur ce service. 0 trouve
    # sur N declares = la carte sort nue, et le viewer doit le dire.
    models_declared: int = 0
    models_found: int = 0


_MODEL_RE = re.compile(r'\(model\s+"([^"]+)"')
_VARIABLES_MODELES = ("KICAD10_3DMODEL_DIR", "KICAD9_3DMODEL_DIR", "KICAD8_3DMODEL_DIR", "KISYS3DMOD")


def compter_modeles(pcb: bytes, model_dir: Optional[str]) -> tuple[int, int]:
    """(modeles declares dans le board, fichiers reellement presents).

    `kicad-cli pcb export glb` charge le STEP d un modele meme quand le board
    cite le `.wrl` : un `.step`/`.stp` voisin compte comme present. Sans
    repertoire de modeles, rien n est present — et on le dit, plutot que de
    laisser croire que le GLB porte les composants.
    """
    chemins = _MODEL_RE.findall(pcb.decode("utf-8", "replace"))
    if not chemins:
        return 0, 0
    trouves = 0
    for chemin in chemins:
        resolu = chemin
        for var in _VARIABLES_MODELES:
            resolu = resolu.replace("${%s}" % var, model_dir or "")
        if not model_dir and resolu == chemin and chemin.startswith("${"):
            continue
        base = Path(resolu)
        candidats = [base] + [base.with_suffix(ext) for ext in (".step", ".stp", ".STEP")]
        if any(c.is_file() for c in candidats):
            trouves += 1
    return len(chemins), trouves


def construire_commande_glb(cli: str, req: GlbRequest, entree: Path, sortie: Path) -> list[str]:
    """La ligne de commande exacte — pure, testable sans exporter."""
    cmd = [cli, "pcb", "export", "glb", "--force", "--no-unspecified", "--no-dnp"]
    if req.include_tracks:
        cmd.append("--include-tracks")
    if req.include_pads:
        cmd.append("--include-pads")
    if req.include_zones:
        cmd.append("--include-zones")
    if req.include_silkscreen:
        cmd.append("--include-silkscreen")
    if req.include_soldermask:
        cmd.append("--include-soldermask")
    if not req.components:
        cmd.append("--no-components")
    cmd += ["-o", str(sortie), str(entree)]
    return cmd


def verifier_glb(data: bytes) -> int:
    """Un GLB recevable : l en-tête binaire glTF (`glTF`, version 2) et une taille réelle."""
    if len(data) < 20 or data[:4] != _GLB_SIGNATURE:
        raise RuntimeError("kicad-cli did not produce a GLB")
    version = int.from_bytes(data[4:8], "little")
    if version != 2:
        raise RuntimeError(f"unexpected glTF version {version}")
    longueur = int.from_bytes(data[8:12], "little")
    if longueur != len(data):
        raise RuntimeError(f"GLB length header {longueur} != {len(data)} bytes — truncated export")
    return len(data)


def exporter_glb(cli: str, req: GlbRequest, pcb: bytes) -> tuple[bytes, int]:
    with tempfile.TemporaryDirectory(prefix="cirqix-glb-") as tmp:
        entree = Path(tmp) / "board.kicad_pcb"
        sortie = Path(tmp) / "board.glb"
        entree.write_bytes(pcb)
        debut = time.monotonic()
        try:
            result = subprocess.run(
                construire_commande_glb(cli, req, entree, sortie),
                capture_output=True, text=True, errors="replace", timeout=_GLB_TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"kicad-cli pcb export glb timed out after {_GLB_TIMEOUT_S}s") from exc
        duree_ms = int((time.monotonic() - debut) * 1000)
        if result.returncode != 0:
            extrait = (result.stderr or result.stdout or "").strip()[-400:]
            raise RuntimeError(f"kicad-cli pcb export glb failed (rc={result.returncode}): {extrait}")
        if not sortie.exists():
            raise RuntimeError("kicad-cli pcb export glb exited 0 but wrote no file")
        data = sortie.read_bytes()
        verifier_glb(data)
        return data, duree_ms


@router.post("/export/glb", response_model=GlbResponse)
def export_glb(req: GlbRequest) -> GlbResponse:
    """Le modèle 3D du board, pour le viewer interactif (Three.js). Fail closed."""
    pcb = _decoder_board(req.kicad_pcb_b64)
    cli = _find_kicad_cli()
    if not cli:
        raise HTTPException(status_code=503, detail="kicad-cli not available — no 3D export possible")
    try:
        glb, duree_ms = exporter_glb(cli, req, pcb)
    except RuntimeError as exc:
        logger.error("export/glb: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    declares, trouves = compter_modeles(pcb, os.environ.get("KICAD10_3DMODEL_DIR")) if req.components else (0, 0)
    logger.info("export/glb: %d octets en %d ms — modeles 3D %d/%d", len(glb), duree_ms, trouves, declares)
    return GlbResponse(glb_b64=base64.b64encode(glb).decode("ascii"), bytes=len(glb), duration_ms=duree_ms,
                       models_declared=declares, models_found=trouves)


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

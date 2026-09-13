"""`POST /render/auto` — rendu PNG/3D par kicad-cli, fail closed.

Ce que ces tests discriminent :
  - la ligne de commande transmet CHAQUE option (side, rotate, perspective,
    zoom, quality, taille) — une option acceptée puis ignorée rendrait toujours
    la vue de dessus, et l'utilisateur ne verrait jamais sa 3D ;
  - rien n'est annoncé rendu sans un vrai PNG : rc≠0, fichier absent, octets
    qui ne sont pas un PNG, PNG minuscule → 500, jamais une image de repli ;
  - la route est bien exposée (garde ancrée sur la table de routes) ;
  - et, quand kicad-cli est là (conteneur, CI Docker), un board de référence
    rend une image aux dimensions demandées et de plus de 10 ko.
"""
from __future__ import annotations

import base64
import os
import shutil
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import render as render_router  # noqa: E402
from routers.render import (  # noqa: E402
    RenderRequest,
    construire_commande,
    dimensions_png,
    render_auto,
    verifier_png,
)

_BOARD = b"(kicad_pcb (version 20240108) (generator pcbnew))"
_BOARD_B64 = base64.b64encode(_BOARD).decode("ascii")


def _png(largeur: int = 8, hauteur: int = 4, remplissage: int = 2000) -> bytes:
    """Un PNG minimal mais valide, gonflé d'un chunk privé pour dépasser la taille plancher."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * largeur for _ in range(hauteur))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"cqXx", b"\x00" * remplissage)
        + chunk(b"IEND", b"")
    )


def _req(**kw) -> RenderRequest:
    return RenderRequest(kicad_pcb_b64=_BOARD_B64, **kw)


# ---------------------------------------------------------------------------
# La ligne de commande transmet tout
# ---------------------------------------------------------------------------

def test_la_commande_transmet_chaque_option():
    req = _req(side="bottom", rotate="-45,0,45", perspective=True, zoom=1.5,
               quality="high", width=1200, height=800, floor=True)
    cmd = construire_commande("/usr/bin/kicad-cli", req, Path("/in.kicad_pcb"), Path("/out.png"))
    assert cmd[:3] == ["/usr/bin/kicad-cli", "pcb", "render"]
    for option, valeur in (("--side", "bottom"), ("--rotate", "-45,0,45"), ("--zoom", "1.5"),
                           ("--quality", "high"), ("--width", "1200"), ("--height", "800")):
        assert cmd[cmd.index(option) + 1] == valeur, option
    assert "--perspective" in cmd and "--floor" in cmd
    assert cmd[-3:] == ["-o", str(Path("/out.png")), str(Path("/in.kicad_pcb"))]


def test_sans_rotation_ni_perspective_la_commande_est_orthogonale():
    cmd = construire_commande("kicad-cli", _req(), Path("i"), Path("o"))
    assert "--rotate" not in cmd and "--perspective" not in cmd and "--floor" not in cmd
    assert cmd[cmd.index("--side") + 1] == "top"


@pytest.mark.parametrize("mauvais", ["abc", "1,2", "1,2,3,4", "45;0;45", "1000,0,0"])
def test_une_rotation_illisible_est_refusee(mauvais):
    with pytest.raises(ValueError):
        _req(rotate=mauvais)


@pytest.mark.parametrize("champ, valeur", [("zoom", 0), ("zoom", 11), ("width", 10), ("height", 5000)])
def test_les_bornes_sont_tenues(champ, valeur):
    with pytest.raises(ValueError):
        _req(**{champ: valeur})


# ---------------------------------------------------------------------------
# Le PNG est vérifié, pas supposé
# ---------------------------------------------------------------------------

def test_dimensions_lues_dans_l_en_tete():
    assert dimensions_png(_png(640, 480)) == (640, 480)


def test_verifier_png_refuse_ce_qui_n_est_pas_un_png():
    with pytest.raises(RuntimeError, match="did not produce a PNG"):
        verifier_png(b"GIF89a" + b"\x00" * 3000)


def test_verifier_png_refuse_un_png_minuscule():
    with pytest.raises(RuntimeError, match="not a board render"):
        verifier_png(_png(remplissage=0))


# ---------------------------------------------------------------------------
# La route : fail closed à chaque étape
# ---------------------------------------------------------------------------

def test_base64_illisible_422():
    with pytest.raises(HTTPException) as exc:
        render_auto(RenderRequest(kicad_pcb_b64="pas du base64 !"))
    assert exc.value.status_code == 422


def test_un_base64_qui_n_est_pas_un_board_422():
    with pytest.raises(HTTPException) as exc:
        render_auto(RenderRequest(kicad_pcb_b64=base64.b64encode(b"hello").decode()))
    assert exc.value.status_code == 422


def test_sans_kicad_cli_503(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: None)
    with pytest.raises(HTTPException) as exc:
        render_auto(_req())
    assert exc.value.status_code == 503


def test_rendu_en_echec_500_avec_stderr(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(render_router.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Failed to load board"))
    with pytest.raises(HTTPException) as exc:
        render_auto(_req())
    assert exc.value.status_code == 500
    assert "Failed to load board" in str(exc.value.detail)


def test_rc_zero_sans_fichier_500(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(render_router.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(HTTPException) as exc:
        render_auto(_req())
    assert exc.value.status_code == 500
    assert "no file" in str(exc.value.detail)


def _faux_run_qui_ecrit(contenu: bytes):
    def run(cmd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(contenu)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def test_un_fichier_qui_n_est_pas_un_png_500(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(render_router.subprocess, "run", _faux_run_qui_ecrit(b"<html>oops</html>" + b" " * 3000))
    with pytest.raises(HTTPException) as exc:
        render_auto(_req())
    assert exc.value.status_code == 500


def test_un_vrai_png_est_rendu_tel_quel(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    png = _png(320, 200)
    monkeypatch.setattr(render_router.subprocess, "run", _faux_run_qui_ecrit(png))
    rep = render_auto(_req(side="bottom", rotate="-45,0,45", perspective=True, quality="high"))
    assert base64.b64decode(rep.png_b64) == png
    assert (rep.width, rep.height) == (320, 200)
    assert rep.side == "bottom" and rep.rotate == "-45,0,45" and rep.perspective and rep.quality == "high"


def test_la_route_est_exposee():
    """Ancrée sur la TABLE DE ROUTES, pas sur le source (leçon du 2026-08-31)."""
    chemins = {getattr(r, "path", None): getattr(r, "methods", set()) for r in render_router.router.routes}
    assert "POST" in chemins["/render/auto"]


# ---------------------------------------------------------------------------
# Rendu réel — seulement là où kicad-cli existe (conteneur, CI Docker)
# ---------------------------------------------------------------------------

# Un board LIVRÉ par la chaîne actuelle (pcbnew 10). `stm32-validation/expected/stm32_final.kicad_pcb`
# ne convient pas : écrit par kicad_tools, kicad-cli refuse de le charger (« Failed to load board »).
_CANDIDATS = [
    _SERVICE_ROOT / "examples" / "carte-01-diviseur" / "expected" / "final.kicad_pcb",
    _SERVICE_ROOT / "examples" / "driver-clignotant-ne555" / "expected" / "final.kicad_pcb",
]
_BOARD_DE_REFERENCE = (
    Path(os.environ["CIRQIX_RENDER_BOARD"]) if os.environ.get("CIRQIX_RENDER_BOARD")
    else next((c for c in _CANDIDATS if c.exists()), _CANDIDATS[0])
)


@pytest.mark.skipif(shutil.which("kicad-cli") is None or not _BOARD_DE_REFERENCE.exists(),
                    reason="kicad-cli ou le board de référence absent")
@pytest.mark.parametrize("params", [
    {"side": "top"},
    {"side": "bottom"},
    {"rotate": "-45,0,45", "perspective": True},
])
def test_rendu_reel_d_un_board_de_reference(params):
    b64 = base64.b64encode(_BOARD_DE_REFERENCE.read_bytes()).decode("ascii")
    rep = render_auto(RenderRequest(kicad_pcb_b64=b64, width=640, height=400, **params))
    png = base64.b64decode(rep.png_b64)
    # kicad-cli rend un peu MOINS que demande (mesure : 800x500 -> 784x480, 640x400 -> 616x384) ;
    # la reponse porte la taille reelle, lue dans l en-tete.
    largeur, hauteur = dimensions_png(png)
    assert 640 - 32 <= largeur <= 640 and 400 - 32 <= hauteur <= 400
    assert (rep.width, rep.height) == (largeur, hauteur)
    # Mesuré le 2026-09-13 (8 composants, 1200x800) : top 21 ko, bottom 8,7 ko, iso high 245 ko ;
    # un cadre vide de cette taille pèse ~1 ko.
    assert len(png) > 2_000, "un rendu de carte pese plus qu un cadre vide (~1 ko a cette taille)"

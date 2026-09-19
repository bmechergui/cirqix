"""`POST /export/glb` — le modèle 3D du board pour le viewer interactif, fail closed.

Ce que ces tests discriminent : chaque option atteint la ligne de commande ;
rien n'est annoncé exporté sans un vrai GLB (en-tête `glTF` v2, longueur
déclarée = longueur réelle — un export tronqué se voit) ; la route est
exposée ; et, là où kicad-cli existe, un board livré donne un GLB de plus de
100 ko contenant une scène.
"""
from __future__ import annotations

import base64
import os
import shutil
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import render as render_router  # noqa: E402
from routers.render import (  # noqa: E402
    GlbRequest,
    construire_commande_glb,
    export_glb,
    verifier_glb,
)

_BOARD_B64 = base64.b64encode(b"(kicad_pcb (version 20240108) (generator pcbnew))").decode("ascii")


def _glb(charge: bytes = b"\x00" * 64) -> bytes:
    """Un GLB minimal valide : en-tete 12 octets + un chunk JSON."""
    json_chunk = b'{"asset":{"version":"2.0"}}'
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    corps = struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    corps += struct.pack("<II", len(charge), 0x004E4942) + charge
    total = 12 + len(corps)
    return b"glTF" + struct.pack("<II", 2, total) + corps


def test_la_commande_transmet_chaque_option():
    cmd = construire_commande_glb("kicad-cli", GlbRequest(kicad_pcb_b64=_BOARD_B64), Path("/i"), Path("/o.glb"))
    assert cmd[:4] == ["kicad-cli", "pcb", "export", "glb"]
    for opt in ("--force", "--no-unspecified", "--no-dnp", "--include-tracks", "--include-pads",
                "--include-zones", "--include-silkscreen", "--include-soldermask"):
        assert opt in cmd
    assert "--no-components" not in cmd
    assert cmd[-3:] == ["-o", str(Path("/o.glb")), str(Path("/i"))]
    sans = construire_commande_glb("kicad-cli", GlbRequest(kicad_pcb_b64=_BOARD_B64, include_zones=False, components=False), Path("i"), Path("o"))
    assert "--include-zones" not in sans and "--no-components" in sans
    nu = construire_commande_glb(
        "kicad-cli",
        GlbRequest(kicad_pcb_b64=_BOARD_B64, include_silkscreen=False, include_soldermask=False),
        Path("i"), Path("o"))
    assert "--include-silkscreen" not in nu and "--include-soldermask" not in nu


def test_verifier_glb_accepte_un_vrai_glb_et_refuse_le_reste():
    assert verifier_glb(_glb()) == len(_glb())
    with pytest.raises(RuntimeError, match="not produce a GLB"):
        verifier_glb(b"<html>" + b"\x00" * 40)
    tronque = _glb()[:-10]
    with pytest.raises(RuntimeError, match="truncated"):
        verifier_glb(tronque)


def test_sans_kicad_cli_503(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: None)
    with pytest.raises(HTTPException) as exc:
        export_glb(GlbRequest(kicad_pcb_b64=_BOARD_B64))
    assert exc.value.status_code == 503


def test_export_en_echec_500_avec_stderr(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(render_router.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Failed to load board"))
    with pytest.raises(HTTPException) as exc:
        export_glb(GlbRequest(kicad_pcb_b64=_BOARD_B64))
    assert exc.value.status_code == 500 and "Failed to load board" in str(exc.value.detail)


def test_un_vrai_glb_est_rendu_tel_quel(monkeypatch):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    glb = _glb(b"\x01" * 128)

    def run(cmd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(glb)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(render_router.subprocess, "run", run)
    rep = export_glb(GlbRequest(kicad_pcb_b64=_BOARD_B64))
    assert base64.b64decode(rep.glb_b64) == glb and rep.bytes == len(glb)


def test_compter_modeles_ne_compte_que_le_fichier_CITE(tmp_path):
    """Un .step voisin ne sauve PAS un .wrl absent — mesure du 2026-09-15.

    Le compteur creditait le `.step` de meme nom, au motif que kicad-cli
    chargerait le STEP a la place du VRML cite. Mesure sur carte-05, meme board,
    chemins bascules en `.wrl` (le volume de modeles n'en contient AUCUN :
    0 `.wrl`, 3423 `.step`) :

        cite .step | 26 fichiers cites presents | compteur 26/26 | 26 corps dans le GLB
        cite .wrl  |  0 fichier  cite  present  | compteur 26/26 |  0 corps

    La carte sortait donc NUE pendant que le service annoncait 26 composants sur
    26, et `--subst-models` n'y change rien : « Could not add 3D model for C15 —
    File not found: …/C_0603_1608Metric.wrl », 0 corps avec comme sans l'option.
    """
    from routers.render import compter_modeles
    (tmp_path / "Resistor_SMD.3dshapes").mkdir()
    (tmp_path / "Resistor_SMD.3dshapes" / "R_0603_1608Metric.step").write_bytes(b"step")
    board = (
        b'(footprint "R" (model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.wrl"))'
        b'(footprint "C" (model "${KICAD10_3DMODEL_DIR}/Capacitor_SMD.3dshapes/C_0603.wrl"))'
    )
    # Le .step voisin existe, mais c'est le .wrl qui est cite et il est absent.
    assert compter_modeles(board, str(tmp_path)) == (2, 0)
    # Ce que citent nos boards aujourd'hui : le .step lui-meme, present.
    cite_le_step = b'(footprint "R" (model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.step"))'
    assert compter_modeles(cite_le_step, str(tmp_path)) == (1, 1)
    # Sans repertoire de modeles : declares, mais rien de present — et on le dit.
    assert compter_modeles(board, None) == (2, 0)
    assert compter_modeles(b"(kicad_pcb)", str(tmp_path)) == (0, 0)


def test_raison_des_modeles_distingue_la_bibliotheque_absente_des_fichiers_absents(tmp_path):
    """0 trouve sur N a DEUX causes, et le viewer n en disait qu une.

    « aucun modele 3D installe sur le service » est vrai quand le volume de
    modeles manque ; c est FAUX — et trompeur — quand le volume est plein et que
    c est le board qui cite des fichiers absents (cas mesure le 2026-09-15 : un
    board citant des `.wrl` face a 3423 `.step`). Un lecteur ira chercher le
    defaut du mauvais cote.
    """
    from routers.render import raison_des_modeles
    assert raison_des_modeles(None, 9, 0) == "bibliotheque_absente"
    assert raison_des_modeles(str(tmp_path / "pas-de-volume"), 9, 0) == "bibliotheque_absente"
    # Un volume MONTE mais VIDE : la bibliotheque n a jamais ete installee
    # (`scripts/modeles_3d.sh` pas passe, ou echoue). Accuser le board serait
    # l inversion de diagnostic que ce correctif est cense supprimer.
    vide = tmp_path / "volume-vide"
    vide.mkdir()
    assert raison_des_modeles(str(vide), 9, 0) == "bibliotheque_absente"
    # Bibliotheque peuplee : c est bien la carte qui cite des fichiers absents.
    (tmp_path / "Resistor_SMD.3dshapes").mkdir(exist_ok=True)
    (tmp_path / "Resistor_SMD.3dshapes" / "R_0603_1608Metric.step").write_bytes(b"step")
    assert raison_des_modeles(str(tmp_path), 9, 0) == "fichiers_absents"
    # Rien a expliquer : des modeles ont ete trouves, ou le board n en declare aucun.
    assert raison_des_modeles(str(tmp_path), 9, 9) == ""
    assert raison_des_modeles(str(tmp_path), 9, 4) == ""
    assert raison_des_modeles(str(tmp_path), 0, 0) == ""


def test_la_reponse_porte_le_compte_des_modeles(monkeypatch, tmp_path):
    monkeypatch.setattr(render_router, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path))
    # Bibliotheque PEUPLEE — mais pas du fichier que le board cite.
    (tmp_path / "Autre.3dshapes").mkdir()
    (tmp_path / "Autre.3dshapes" / "Autre.step").write_bytes(b"step")
    glb = _glb()

    def run(cmd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(glb)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(render_router.subprocess, "run", run)
    board = b'(kicad_pcb (footprint "R" (model "${KICAD10_3DMODEL_DIR}/X.3dshapes/Y.wrl")))'
    rep = export_glb(GlbRequest(kicad_pcb_b64=base64.b64encode(board).decode("ascii")))
    assert (rep.models_declared, rep.models_found) == (1, 0)
    # La bibliotheque existe et porte des modeles : c est le fichier CITE qui
    # manque — et c est ce qu on dit, sans accuser le service.
    assert rep.models_reason == "fichiers_absents"
    sans = export_glb(GlbRequest(kicad_pcb_b64=base64.b64encode(board).decode("ascii"), components=False))
    assert (sans.models_declared, sans.models_found) == (0, 0)
    assert sans.models_reason == ""


def test_le_compte_des_modeles_se_demande_sans_exporter(monkeypatch, tmp_path):
    """Parcours local du 2026-09-19 : le GLB servi depuis le CACHE — le cas le
    plus frequent, le pipeline le depose a chaque livraison — perdait son compte
    de composants, faute de service interroge. La route redemande donc le seul
    compte, sans relancer l export (1-6 s)."""
    from routers.render import compter_modeles_glb, ComptageRequest
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path))
    (tmp_path / "Autre.3dshapes").mkdir()
    (tmp_path / "Autre.3dshapes" / "Autre.step").write_bytes(b"step")
    monkeypatch.setattr(render_router.subprocess, "run",
                        lambda *a, **k: pytest.fail("le comptage ne doit JAMAIS exporter"))
    board = b'(kicad_pcb (footprint "R" (model "${KICAD10_3DMODEL_DIR}/X.3dshapes/Y.step")))'
    rep = compter_modeles_glb(ComptageRequest(kicad_pcb_b64=base64.b64encode(board).decode("ascii")))
    assert (rep.models_declared, rep.models_found, rep.models_reason) == (1, 0, "fichiers_absents")


def test_la_route_de_comptage_est_exposee():
    chemins = {getattr(r, "path", None): getattr(r, "methods", set()) for r in render_router.router.routes}
    assert "POST" in chemins["/export/glb/composants"]


def test_la_route_est_exposee():
    chemins = {getattr(r, "path", None): getattr(r, "methods", set()) for r in render_router.router.routes}
    assert "POST" in chemins["/export/glb"]


_CANDIDATS = [
    Path(os.environ["CIRQIX_RENDER_BOARD"]) if os.environ.get("CIRQIX_RENDER_BOARD") else None,
    _SERVICE_ROOT / "examples" / "carte-01-diviseur" / "expected" / "final.kicad_pcb",
]
_BOARD = next((c for c in _CANDIDATS if c and c.exists()), None)


@pytest.mark.skipif(shutil.which("kicad-cli") is None or _BOARD is None, reason="kicad-cli ou board de référence absent")
def test_export_reel_d_un_board_livre():
    rep = export_glb(GlbRequest(kicad_pcb_b64=base64.b64encode(_BOARD.read_bytes()).decode("ascii")))
    glb = base64.b64decode(rep.glb_b64)
    assert verifier_glb(glb) > 100_000, "une carte routée pèse plus qu un cadre vide"
    # Le chunk JSON du NE555 pese ~395 ko : on cherche dans tout le chunk.
    longueur_json = int.from_bytes(glb[12:16], "little")
    assert b'"meshes"' in glb[20:20 + longueur_json]

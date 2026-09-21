"""D-2026-09-13-c — occupation de la surface (option C, validée).

Ce que ces tests discriminent, sur un board LIVRÉ du banc (carte-01, 5
composants, contour 25 x 20 mm, origine de feuille (136, 95)) :
  - B : les connecteurs partent du MILIEU du bord gauche, corps à la marge,
    répartis quand ils sont plusieurs ; les autres empreintes ne bougent pas ;
  - A : le contour est resserré sur les courtyards + marge, en repère
    FEUILLE (le piège de repère de ce dépôt), sans déplacer une empreinte,
    et jamais agrandi ; un second passage ne change rien ;
  - le câblage : `auto_place` ne touche PAS aux connecteurs (B mesurée et
    retirée le 2026-09-13) et resserre APRÈS, seulement sur `auto_size_board`
    — une règle jamais appelée est indistinguable d'une règle absente, et une
    règle retirée doit l'être vraiment.
"""
from __future__ import annotations

import base64
import shutil
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
for chemin in (_SERVICE_ROOT, _SERVICE_ROOT / "kicad-tools" / "src"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from kicad_tools.schema.pcb import PCB  # noqa: E402
from tools import placement as placement_mod  # noqa: E402
from tools.contour_et_bords import (  # noqa: E402
    MARGE_BORD_MM,
    ajuster_contour_au_placement,
    ancrer_connecteurs_au_bord,
    ancrer_connecteurs_au_bord_b64,
    boite_des_courtyards,
    taille_contour_texte,
)

# ⚠️ Fixture FIGEE : le placement livre de carte-01 (25 x 20, J1 au coin de la
# grille) tel qu il etait avant le contour resserre. `examples/` bouge a chaque
# livraison ; un test qui y lit ses hypotheses casse a la premiere (CI de #179).
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "carte-01-placement-25x20.kicad_pcb"
pytestmark = pytest.mark.skipif(not _FIXTURE.exists(), reason="fixture carte-01-placement-25x20 absente")


@pytest.fixture
def board(tmp_path: Path) -> Path:
    f = tmp_path / "b.kicad_pcb"
    shutil.copy(_FIXTURE, f)
    return f


def _positions(pcb) -> dict[str, tuple[float, float]]:
    return {fp.reference: tuple(fp.position) for fp in pcb.footprints}


def _positions_feuille(pcb) -> dict[str, tuple[float, float]]:
    """Positions en repère FEUILLE : `board_origin` suit le contour, donc
    resserrer le contour décale les positions relatives sans rien déplacer."""
    ox, oy = pcb.board_origin
    return {fp.reference: (round(fp.position[0] + ox, 3), round(fp.position[1] + oy, 3))
            for fp in pcb.footprints}


# ---------------------------------------------------------------------------
# B — connecteurs au milieu d'un bord
# ---------------------------------------------------------------------------

def test_le_connecteur_part_du_milieu_du_bord_gauche(board: Path):
    pcb = PCB.load(str(board))
    avant = _positions(pcb)
    assert avant["J1"] == (5.0, 5.0), "la fixture ancre J1 dans le coin de la grille"

    deplaces = ancrer_connecteurs_au_bord(pcb)
    assert deplaces == ["J1"]

    apres = _positions(pcb)
    for ref in ("R1", "R2", "R3", "D1"):
        assert apres[ref] == avant[ref], f"{ref} ne doit pas bouger"

    j1 = next(fp for fp in pcb.footprints if fp.reference == "J1")
    bx0, by0, bx1, by1 = placement_mod._boite_locale_fp(j1)
    corps_x0 = j1.position[0] + bx0
    corps_cy = j1.position[1] + (by0 + by1) / 2.0
    # Contour de la fixture : 25 x 20 en repère board (0..25, 0..20).
    assert corps_x0 == pytest.approx(MARGE_BORD_MM, abs=0.01)
    assert corps_cy == pytest.approx(10.0, abs=0.01)


def test_chaque_connecteur_va_au_bord_le_plus_proche_et_les_bords_sont_repartis(board: Path):
    pcb = PCB.load(str(board))
    # Contour 25 x 20. On promeut R1..R3 et D1 en connecteurs et on les pose
    # explicitement : deux pres du bas, un pres de la droite, J1 au coin.
    renommage = {"R1": "J2", "R2": "J3", "R3": "J4", "D1": "P9"}
    positions = {"J2": (8.0, 18.0), "J3": (16.0, 17.5), "J4": (23.0, 6.0), "P9": (12.0, 12.0)}
    for fp in pcb.footprints:
        if fp.reference in renommage:
            fp.reference = renommage[fp.reference]
            fp.position = positions[fp.reference]
    deplaces = ancrer_connecteurs_au_bord(pcb)
    assert sorted(deplaces) == ["J1", "J2", "J3", "J4", "P9"]
    par_ref = {fp.reference: fp for fp in pcb.footprints}

    def corps(ref):
        fp = par_ref[ref]; b = placement_mod._boite_locale_fp(fp)
        return (fp.position[0] + b[0], fp.position[1] + b[1], fp.position[0] + b[2], fp.position[1] + b[3])

    # J1 (coin) -> bord gauche, seul dessus : centre a mi-hauteur.
    assert corps("J1")[0] == pytest.approx(MARGE_BORD_MM, abs=0.01)
    assert (corps("J1")[1] + corps("J1")[3]) / 2 == pytest.approx(10.0, abs=0.01)
    # J2, P9 et J3 -> bord bas (P9 au centre : 7,3 mm du bas, son plus proche),
    # repartis a 25/4, 50/4, 75/4 dans l ordre de leur x.
    for ref, cx in (("J2", 6.25), ("P9", 12.5), ("J3", 18.75)):
        assert corps(ref)[3] == pytest.approx(20.0 - MARGE_BORD_MM, abs=0.01), ref
        assert (corps(ref)[0] + corps(ref)[2]) / 2 == pytest.approx(cx, abs=0.01), ref
    # J4 -> bord droit, seul dessus.
    assert corps("J4")[2] == pytest.approx(25.0 - MARGE_BORD_MM, abs=0.01)
    assert (corps("J4")[1] + corps("J4")[3]) / 2 == pytest.approx(10.0, abs=0.01)


def test_la_variante_b64_rend_un_board_relisible(board: Path):
    b64 = base64.b64encode(board.read_bytes()).decode()
    sortie = ancrer_connecteurs_au_bord_b64(b64)
    assert sortie != b64
    board.write_bytes(base64.b64decode(sortie))
    pcb = PCB.load(str(board))
    assert _positions(pcb)["J1"] != (5.0, 5.0)


# ---------------------------------------------------------------------------
# A — contour resserré sur le placement
# ---------------------------------------------------------------------------

def test_le_contour_est_resserre_sur_les_courtyards_en_repere_feuille(board: Path):
    avant = _positions_feuille(PCB.load(str(board)))
    assert taille_contour_texte(board.read_text(encoding="utf-8")) == (25.0, 20.0)

    taille = ajuster_contour_au_placement(board)
    assert taille is not None
    largeur, hauteur = taille
    # Sur carte-01 la largeur est deja tenue (J1 et D1 touchent la marge) ;
    # c est la hauteur qui a du vide. On ne fait que resserrer.
    assert largeur <= 25.0 and hauteur < 20.0

    pcb = PCB.load(str(board))
    assert _positions_feuille(pcb) == avant, "resserrer le contour ne déplace rien (repère feuille)"
    boite = boite_des_courtyards(pcb)
    texte = board.read_text(encoding="utf-8")
    assert texte.count('(layer "Edge.Cuts")') == 1, "un seul rectangle, les anciens blocs retirés"
    assert taille_contour_texte(texte) == pytest.approx((largeur, hauteur), abs=0.01)
    # Le contour entoure les courtyards à la marge — en coordonnées de FEUILLE.
    import re
    m = re.search(r"\(gr_rect\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)", texte)
    assert m, "le rectangle doit être un gr_rect"
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    # Boite + marge, bornee par l ancien contour (136,95)-(161,115) : jamais agrandi.
    assert (x0, y0) == pytest.approx((max(boite[0] - MARGE_BORD_MM, 136.0), max(boite[1] - MARGE_BORD_MM, 95.0)), abs=0.01)
    assert (x1, y1) == pytest.approx((min(boite[2] + MARGE_BORD_MM, 161.0), min(boite[3] + MARGE_BORD_MM, 115.0)), abs=0.01)
    assert x0 > 100, "repère feuille (origine 136, 95), pas repère board"


def test_un_second_passage_ne_change_rien(board: Path):
    premiere = ajuster_contour_au_placement(board)
    texte1 = board.read_text(encoding="utf-8")
    seconde = ajuster_contour_au_placement(board)
    assert seconde == pytest.approx(premiere, abs=0.01)
    assert board.read_text(encoding="utf-8") == texte1


def test_le_contour_n_est_jamais_agrandi(board: Path, monkeypatch):
    # Une boîte de courtyards plus grande que le contour : on garde le contour.
    monkeypatch.setattr("tools.contour_et_bords.boite_des_courtyards",
                        lambda pcb: (0.0, 0.0, 1000.0, 1000.0))
    assert ajuster_contour_au_placement(board) == (25.0, 20.0)
    assert taille_contour_texte(board.read_text(encoding="utf-8")) == (25.0, 20.0)


# ---------------------------------------------------------------------------
# Le câblage dans auto_place
# ---------------------------------------------------------------------------

def _faux_tirage(kicad_pcb_b64: str, w: float, h: float) -> dict:
    return {"kicad_pcb_b64": kicad_pcb_b64, "placed_count": 5, "positions": [], "conflits_restants": 0}


def test_auto_place_ne_touche_pas_aux_connecteurs_et_resserre_seulement_sur_demande(board: Path, monkeypatch):
    """B a ete mesuree et RETIREE (voir auto_place) : le tirage recoit le board
    tel quel ; A ne s applique que sur `auto_size_board`."""
    b64 = base64.b64encode(board.read_bytes()).decode()
    recus: list[str] = []

    # ⚠️ Le faux porte la MEME signature que le vrai, `graine` compris (ajoute le
    # 2026-09-21 pour la graine en etoile) : un faux plus pauvre que le vrai ne
    # revele pas un contrat rompu, il le CACHE — lecon deja payee par le faux
    # `pcbnew` sans `GetFootprints()` et le faux client Supabase.
    def tirage(kicad_pcb_b64: str, w: float, h: float, graine: bool = True) -> dict:
        recus.append(kicad_pcb_b64)
        return _faux_tirage(kicad_pcb_b64, w, h)

    monkeypatch.setattr(placement_mod, "_auto_place_une_fois", tirage)
    monkeypatch.setattr(placement_mod, "_TIRAGES_MINIMUM", 1)
    monkeypatch.setattr(placement_mod, "_tirages_utiles", lambda dominants: 1)

    sans = placement_mod.auto_place(b64, 25.0, 20.0)
    assert recus, "un tirage a eu lieu"
    pcb_recu = PCB.load(str(_ecrire(board.parent / "recu.kicad_pcb", recus[0])))
    assert _positions(pcb_recu)["J1"] == (5.0, 5.0), "le tirage recoit le board TEL QUEL (B retiree)"
    assert "board_width_mm" not in sans
    assert taille_contour_texte(base64.b64decode(sans["kicad_pcb_b64"]).decode()) == (25.0, 20.0)

    avec = placement_mod.auto_place(b64, 25.0, 20.0, auto_size_board=True)
    assert avec["board_width_mm"] <= 25.0 and avec["board_height_mm"] < 20.0
    assert taille_contour_texte(base64.b64decode(avec["kicad_pcb_b64"]).decode()) == pytest.approx(
        (avec["board_width_mm"], avec["board_height_mm"]), abs=0.01)


def _ecrire(chemin: Path, b64: str) -> Path:
    chemin.write_bytes(base64.b64decode(b64))
    return chemin

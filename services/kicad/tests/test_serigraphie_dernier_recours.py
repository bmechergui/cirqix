"""Un repere sans aucune place libre : 0,8 mm d abord, masque en dernier recours.

Banc du 2026-10-02 : 26 avertissements viennent de reperes (C33, C66, C71,
R10…) pour lesquels `degager_references` et `reorienter_et_degager` ont essaye
toutes les places jusqu a 1,4 mm du corps, a plat et tournees : zero place
libre a 1 mm de haut. D-2026-10-03-a (validee) : on essaie a 0,8 mm (minimum
JLCPCB), et on ne masque que si meme 0,8 mm ne trouve pas de place.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

pytest.importorskip("kicad_tools")
from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import serigraphie as S  # noqa: E402

BANC = RACINE / "examples" / "carte-05-capteur-i2c" / "expected" / "placement.kicad_pcb"


@pytest.fixture
def board(tmp_path):
    if not BANC.is_file():
        pytest.skip("board du banc absent")
    f = tmp_path / "b.kicad_pcb"
    shutil.copy(BANC, f)
    return f


def _sur_ses_pastilles(f: Path, ref: str) -> PCB:
    """Pose le repere au centre de son composant : sur ses propres pastilles."""
    pcb = PCB.load(str(f))
    pcb.move_reference(ref, absolute=(0.0, 0.0))
    pcb.save(str(f))
    return PCB.load(str(f))


def _font(f: Path, ref: str):
    texte = f.read_text(encoding="utf-8")
    i = texte.index('(property "Reference" "%s"' % ref)
    bloc = texte[i:texte.index("(property", i + 10)]
    return bloc


def test_apres_le_dernier_recours_aucun_repere_visible_ne_chevauche(board):
    pcb = _sur_ses_pastilles(board, "R1")
    S.degager_references(pcb)
    S.reorienter_et_degager(pcb)
    S.dernier_recours(pcb)
    pcb.save(str(board))             # le modele ne relit ni taille ni masque :
    assert S.compter_chevauchements(PCB.load(str(board))) == (0, 0)


def test_reduit_a_0_8_quand_seule_cette_taille_trouve_place(board, monkeypatch):
    pcb = _sur_ses_pastilles(board, "R1")
    libre = (500.0, 500.0)

    def candidats(corps, texte, hauteur, angle):
        if texte == "R1" and hauteur <= S._HAUTEUR_MIN_MM + 1e-9:
            yield 0.0, libre, S._boite_texte(libre[0], libre[1], texte, hauteur, 0.0)

    monkeypatch.setattr(S, "_candidats", candidats)
    monkeypatch.setattr(S, "_deborde", lambda b, c, marge=0.25: False)
    reduits, masques = S.dernier_recours(pcb)
    assert reduits == 1             # R1 seul trouve place (le faux ne libere que lui)
    pcb.save(str(board))
    bloc = _font(board, "R1")
    assert "(size 0.8 0.8)" in bloc
    assert "(hide yes)" not in bloc


def test_masque_quand_aucune_taille_ne_trouve_place(board, monkeypatch):
    pcb = _sur_ses_pastilles(board, "R1")
    monkeypatch.setattr(S, "_candidats", lambda *a, **k: iter(()))
    reduits, masques = S.dernier_recours(pcb)
    assert masques >= 1
    pcb.save(str(board))
    assert "(hide yes)" in _font(board, "R1")
    relu = PCB.load(str(board))
    r1 = next(fp for fp in relu.footprints if fp.reference == "R1")
    assert S._reference_visible(r1) is None


def test_appele_apres_les_deux_recherches():
    src = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
    corps = src[src.index("def _degager_la_serigraphie("):]
    corps = corps[:corps.index("\ndef ")]
    assert corps.index("reorienter_et_degager(pcb)") < corps.index(
        "dernier_recours(pcb, seulement=signales)")


def test_seuls_les_reperes_signales_par_le_drc():
    rapport = {"violations": [
        {"type": "silk_over_copper", "items": [{"description": "Reference field of C33"},
                                               {"description": "Pad 2 [GND] of C33 on F.Cu"}]},
        {"type": "silk_overlap", "items": [{"description": "Segment of D10 on F.Silkscreen"},
                                           {"description": "Reference field of R10"}]},
        {"type": "clearance", "items": [{"description": "Reference field of X1"}]},
    ]}
    assert S.reperes_signales(rapport) == {"C33", "R10"}
    assert S.reperes_signales({}) == set()


def test_un_repere_non_signale_n_est_jamais_touche(board, monkeypatch):
    pcb = _sur_ses_pastilles(board, "R1")
    monkeypatch.setattr(S, "_candidats", lambda *a, **k: iter(()))
    assert S.dernier_recours(pcb, seulement=set()) == (0, 0)


class TestMarqueDeMasque:
    """Revue du 2026-10-03 : la forme du masque depend du format du repere."""

    def _masquer(self, monkeypatch, texte):
        from kicad_tools.sexp.parser import parse_sexp, serialize_sexp
        noeud = parse_sexp(texte)
        monkeypatch.setattr(S, "_propriete_reference", lambda pcb, ref: noeud)
        assert S._masquer_reference(None, "R1")
        return serialize_sexp(noeud)

    def test_property_recoit_hide_yes(self, monkeypatch):
        out = self._masquer(monkeypatch, '(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS"))')
        assert "(hide yes)" in out

    def test_ancien_fp_text_recoit_l_atome_nu(self, monkeypatch):
        out = self._masquer(monkeypatch, '(fp_text reference "R1" (at 0 0) (layer "F.SilkS"))')
        assert "hide" in out.split() and "(hide yes)" not in out

    def test_sans_layer_on_ajoute_en_fin(self, monkeypatch):
        out = self._masquer(monkeypatch, '(property "Reference" "R1" (at 0 0 0))')
        assert "(hide yes)" in out

    def test_deja_masque_on_ne_double_pas(self, monkeypatch):
        out = self._masquer(monkeypatch,
                            '(property "Reference" "R1" (at 0 0 0) (layer "F.SilkS") (hide yes))')
        assert out.count("hide") == 1

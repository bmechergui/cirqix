"""Deux contours de serigraphie qui se touchent sont ecartes avant de livrer.

Banc du 2026-10-02 (30 tirages, tous 100 % / 0 erreur) : 42 avertissements de
serigraphie sur 4 tirages, TOUS presents des le board place — le routage n en
ajoute aucun. 16 sont des contours de corps qui se touchent, sur carte-07 :
D10 et D12 (LED 0603) poses a 1,5 mm de pas. Leurs courtyards (1,46 mm de
haut) ne se chevauchent pas — 0,04 mm d ecart, aucune erreur — mais leurs
traits de serigraphie (a +/- 0,735 mm, 0,12 mm d epaisseur), si.

REGLE (generale, aucune carte nommee) : apres la reparation des courtyards,
les paires `silk_overlap` entre les contours de DEUX empreintes sont reparees
comme les courtyards — le plus petit non ancre va a la case libre la plus
proche, avec une boite qui englobe courtyard ET serigraphie — et on ne garde
le resultat que s il n ajoute aucune erreur et retire des contours.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402


def _v(type_, *descriptions):
    return {"type": type_, "severity": "warning",
            "items": [{"description": d} for d in descriptions]}


class TestPaires:
    def test_contours_de_deux_empreintes(self):
        r = {"violations": [
            _v("silk_overlap", "Segment of D10 on F.Silkscreen", "Segment of D12 on F.Silkscreen"),
            _v("silk_overlap", "Segment of D12 on F.Silkscreen", "Segment of D10 on F.Silkscreen"),
        ]}
        assert P._paires_de_contours_serigraphie(r) == [("D10", "D12")]

    def test_un_repere_n_est_pas_un_contour(self):
        # Un repere se deplace seul (`serigraphie.py`) : bouger le composant
        # pour lui serait disproportionne.
        r = {"violations": [
            _v("silk_overlap", "Reference field of R10", "Segment of R2 on F.Silkscreen"),
            _v("silk_over_copper", "Segment of D1 on F.Silkscreen", "Pad 1 of D2 on F.Cu"),
            _v("silk_overlap", "Segment of R10 on F.Silkscreen", "Segment of R10 on F.Silkscreen"),
        ]}
        assert P._paires_de_contours_serigraphie(r) == []

    def test_rapport_vide(self):
        assert P._paires_de_contours_serigraphie({}) == []


class _G:
    def __init__(self, layer, start=(0.0, 0.0), end=(0.0, 0.0), graphic_type="line",
                 center=None):
        self.layer, self.start, self.end = layer, start, end
        self.graphic_type, self.center, self.points = graphic_type, center, []


class _Pad:
    def __init__(self, x, y):
        self.position = (x, y)


def _led(rotation=0.0):
    class Fp:
        pads = []
        graphics = [_G("F.CrtYd", (-1.48, -0.73), (1.48, 0.73)),
                    _G("F.SilkS", (-1.485, -0.735), (0.8, 0.735))]
    fp = Fp()
    fp.rotation = rotation
    return fp


class TestBoite:
    def test_la_boite_englobe_la_serigraphie(self):
        x0, y0, x1, y1 = P._boite_orientee_serigraphie(_led())
        assert y1 >= 0.735 + 0.06 and y0 <= -0.735 - 0.06
        assert x1 >= 1.48

    def test_elle_tourne_comme_le_courtyard(self):
        # Meme sens que `_boite_orientee_fp` : a 90 degres, x et y s echangent.
        x0, y0, x1, y1 = P._boite_orientee_serigraphie(_led(90.0))
        assert x1 >= 0.735 + 0.06 and x0 <= -0.735 - 0.06
        assert y0 <= -1.48 and y1 >= 1.48
        c = P._boite_orientee_fp(_led(90.0))
        assert x0 <= c[0] and y0 <= c[1] and x1 >= c[2] and y1 >= c[3]

    def test_un_cercle_compte_son_rayon(self):
        class Fp:
            rotation = 0.0
            pads = []
            graphics = [_G("F.CrtYd", (-1.0, -1.0), (1.0, 1.0)),
                        _G("F.SilkS", end=(3.0, 2.0), graphic_type="circle", center=(2.0, 2.0))]
        x0, y0, x1, y1 = P._boite_orientee_serigraphie(Fp())
        assert x1 >= 3.0 and y1 >= 3.0          # centre (2,2), rayon 1

    def test_sans_courtyard_les_pastilles_comptent(self):
        class Fp:
            rotation = 0.0
            pads = [_Pad(-3.0, 0.0), _Pad(3.0, 0.0)]
            graphics = [_G("F.SilkS", (-0.5, -0.5), (0.5, 0.5))]
        x0, _, x1, _ = P._boite_orientee_serigraphie(Fp())
        assert x0 <= -3.0 and x1 >= 3.0


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_apres_les_courtyards_avant_les_reperes(self):
        corps = self.SOURCE[self.SOURCE.index("def _auto_place_une_fois("):]
        courtyards = corps.index("_reparer_chevauchements_du_drc(out,")
        contours = corps.index("_ecarter_les_contours_de_serigraphie(out,")
        reperes = corps.index("_degager_la_serigraphie(out)")
        assert courtyards < contours < reperes


BANC = RACINE / "examples" / "carte-05-capteur-i2c" / "expected" / "placement.kicad_pcb"


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli absent : se lance dans le conteneur")
class TestSurUnVraiBoard:
    def test_deux_led_trop_proches_sont_ecartees(self, tmp_path):
        pytest.importorskip("kicad_tools")
        if not BANC.is_file():
            pytest.skip("board du banc absent")
        from kicad_tools.schema.pcb import PCB
        f = tmp_path / "b.kicad_pcb"
        shutil.copy(BANC, f)
        pcb = PCB.load(str(f))
        par_ref = {fp.reference: fp for fp in pcb.footprints}
        x, y = par_ref["D1"].position
        par_ref["D2"].rotation = par_ref["D1"].rotation
        par_ref["D2"].position = (x, y + 1.5)        # le defaut de carte-07, reproduit
        pcb.save(str(f))
        assert ("D1", "D2") in P._paires_de_contours_serigraphie(P._rapport_drc_sans_lever(f))
        erreurs = P._compter_conflits_erreur(f)
        assert P._ecarter_les_contours_de_serigraphie(f, ancres=[]) >= 1
        assert ("D1", "D2") not in P._paires_de_contours_serigraphie(P._rapport_drc_sans_lever(f))
        assert P._compter_conflits_erreur(f) <= erreurs

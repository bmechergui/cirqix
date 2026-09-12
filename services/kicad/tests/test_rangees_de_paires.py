"""Les paires LED/R sont posees en rangee le long du bord le plus libre.

Etape 8 du placement structure (2026-09-11). Sur carte-09, apres contrainte
de decouplage et graine hierarchique, les quinze paires restaient eparpillees
(35 mm de moyenne) : le GA les reordonne a chaque generation.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement_rangees as R  # noqa: E402

_NETS = {}


class _Pad:
    def __init__(self, number, net_name, x, y):
        self.number, self.net_name, self.position = number, net_name, (x, y)
        self.net_number = _NETS.setdefault(net_name, len(_NETS) + 1)


class _Fp:
    def __init__(self, ref, x, y, pads, rotation=0.0):
        self.reference, self.position, self.pads, self.rotation = ref, (x, y), pads, rotation
        self.layer = "F.Cu"


class _Pcb:
    def __init__(self, fps):
        self.footprints = fps


def _carte():
    """MCU au centre d une carte 100 x 60, connecteur en bas, 6 paires LED/R
    eparpillees. Le bord le plus libre est le HAUT."""
    u1 = _Fp("U1", 50.0, 35.0, [_Pad(str(i), "IO%d" % i if i <= 6 else "GND", -3 + 0.5 * i, -3) for i in range(1, 13)])
    j1 = _Fp("J1", 50.0, 57.0, [_Pad("1", "GND", 0, 0), _Pad("2", "+3V3", 2.54, 0)])
    fps = [u1, j1]
    for i in range(1, 7):
        fps.append(_Fp("R%d" % i, 10.0 * i, 20.0 + 3 * (i % 3), [_Pad("1", "IO%d" % i, -0.8, 0), _Pad("2", "LEDA%d" % i, 0.8, 0)]))
        fps.append(_Fp("D%d" % i, 10.0 * i + 15, 45.0 - 4 * (i % 2), [_Pad("1", "LEDA%d" % i, -1.0, 0), _Pad("2", "GND", 1.0, 0)]))
    return _Pcb(fps)


def _paires():
    return [("LEDA%d" % i, "D%d" % i, "R%d" % i) for i in range(1, 7)]


def _axes(pcb, figes, largeur, hauteur):
    """(indice de la coordonnee LE LONG du bord, indice de la PROFONDEUR)."""
    prof = R._profondeurs_libres(pcb, figes, largeur, hauteur)
    bord = max(prof, key=prof.get)
    return (0, 1) if bord in ("haut", "bas") else (1, 0)


class TestRangees:
    def test_le_bord_retenu_est_le_plus_libre(self):
        pcb = _carte()
        prof = R._profondeurs_libres(pcb, {"J1"}, 100.0, 60.0)
        # Le connecteur est en bas (3 mm libres) : le bas n est jamais retenu.
        assert max(prof, key=prof.get) != "bas", prof
        assert prof["bas"] < 5.0

    def test_les_LED_partagent_une_rangee_et_chaque_R_est_derriere_sa_LED(self):
        pcb = _carte()
        le_long, profondeur = _axes(pcb, {"J1"}, 100.0, 60.0)
        n = R.ranger_les_paires(pcb, _paires(), {"J1"}, 100.0, 60.0)
        assert n == 12
        par = {f.reference: f for f in pcb.footprints}
        prof_led = {round(par["D%d" % i].position[profondeur], 2) for i in range(1, 7)}
        assert len(prof_led) == 1, prof_led           # une seule rangee de LED
        for i in range(1, 7):
            d, r = par["D%d" % i], par["R%d" % i]
            assert abs(d.position[le_long] - r.position[le_long]) < 1e-6   # alignes
            assert 0 < abs(r.position[profondeur] - d.position[profondeur]) < 6.0  # R juste derriere

    def test_l_ordre_le_long_du_bord_suit_la_position_actuelle(self):
        pcb = _carte()
        le_long, _ = _axes(pcb, {"J1"}, 100.0, 60.0)
        avant = sorted(range(1, 7), key=lambda i: {f.reference: f for f in pcb.footprints}["D%d" % i].position[le_long])
        R.ranger_les_paires(pcb, _paires(), {"J1"}, 100.0, 60.0)
        par = {f.reference: f for f in pcb.footprints}
        apres = sorted(range(1, 7), key=lambda i: par["D%d" % i].position[le_long])
        assert apres == avant

    def test_une_paire_figee_n_est_pas_touchee(self):
        pcb = _carte()
        avant = {f.reference: f.position for f in pcb.footprints}
        R.ranger_les_paires(pcb, _paires(), {"J1", "D3", "R3"}, 100.0, 60.0)
        par = {f.reference: f for f in pcb.footprints}
        assert par["D3"].position == avant["D3"] and par["R3"].position == avant["R3"]

    def test_sans_bord_libre_rien_ne_bouge(self, monkeypatch):
        pcb = _carte()
        avant = {f.reference: f.position for f in pcb.footprints}
        # Aucune profondeur libre devant aucun bord : on ne pose rien.
        monkeypatch.setattr(R, "_profondeurs_libres",
                            lambda *a, **k: {"haut": 1.0, "bas": 1.0, "gauche": 1.0, "droite": 1.0})
        assert R.ranger_les_paires(pcb, _paires(), {"J1"}, 100.0, 60.0) == 0
        assert {f.reference: f.position for f in pcb.footprints} == avant

    def test_le_reglage_desarme(self):
        from tools import reglages_banc
        original = reglages_banc.reglage
        try:
            reglages_banc.reglage = lambda nom, defaut=None: False if nom == "rangees_paires" else defaut
            assert R.ranger_les_paires(_carte(), _paires(), {"J1"}, 100.0, 60.0) == 0
        finally:
            reglages_banc.reglage = original


class TestCablage:
    def test_auto_place_range_les_paires_apres_le_snap_et_avant_la_grille(self):
        from tools import placement as P
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(P._auto_place_une_fois).splitlines())
        i_snap = code.find("snap_cluster_members(")
        i_rang = code.find("ranger_les_paires(")
        i_grille = code.find("aligner_sur_grille(")
        assert i_snap != -1 and i_rang != -1 and i_grille != -1
        assert i_snap < i_rang < i_grille, "les rangees viennent apres le snap et avant la grille"

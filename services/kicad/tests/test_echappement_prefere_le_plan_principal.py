"""Le via d echappement PREFERE atterrir dans le plan principal de la face
opposee — sans jamais l exiger (on ordonne, on ne filtre pas).

Mesure du 2026-09-12 (carte-08/10, stm32-100) : le via reserve d une broche
GND du LQFP tombait sur B.Cu dans un ilot de 1 mm2 isole par les pistes
d echappement des signaux ; l ilot ne se cousait pas, il etait retire comme
flottant, et la broche restait orpheline — tirage apres tirage, 96-98 %.
Apres le retrait des ilots, le fanout repasse et choisit, parmi les sorties
degagees, celle dont le via touche le PLAN PRINCIPAL d en face.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


class TestChoixOrdonne:
    def test_sans_preference_la_premiere_sortie_degagee_est_gardee(self):
        s = runner._choisir_sortie(0, 0, 1.0, 0.0, 1.2 * MM, [], MM // 2)
        assert s is not None and s[0] > 0 and abs(s[1]) < 1000

    def test_la_preference_fait_tourner_vers_le_plan(self):
        # Tout est degage ; seul le demi-plan y > 0 porte du cuivre en face.
        prefere = lambda x, y: y > 0.5 * MM  # noqa: E731
        s = runner._choisir_sortie(0, 0, 1.0, 0.0, 1.2 * MM, [], MM // 2, prefere=prefere)
        assert s is not None and s[1] > 0.5 * MM

    def test_sans_candidat_prefere_on_garde_la_premiere_degagee(self):
        # On ordonne, on ne filtre pas : une sortie sans cuivre en face vaut
        # mieux qu aucune sortie (mesure du 2026-09-01, 1 -> 4 manquantes).
        s = runner._choisir_sortie(0, 0, 1.0, 0.0, 1.2 * MM, [], MM // 2,
                                   prefere=lambda x, y: False)
        assert s is not None and s[0] > 0 and abs(s[1]) < 1000

    def test_aucune_sortie_degagee_reste_none(self):
        mur = (-20 * MM, -20 * MM, 20 * MM, 20 * MM)  # tout est obstacle
        assert runner._choisir_sortie(0, 0, 1.0, 0.0, 1.2 * MM, [mur], MM // 2,
                                      prefere=lambda x, y: True) is None


class _Poly:
    """Faux SHAPE_POLY_SET : des rectangles (x1, y1, x2, y2) comme contours."""

    def __init__(self, rects):
        self.rects = rects

    def OutlineCount(self):
        return len(self.rects)

    def Contains(self, pt, i):
        x1, y1, x2, y2 = self.rects[i]
        return x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2

    class _O:
        def __init__(self, r):
            self.r = r

        def Area(self):
            return float((self.r[2] - self.r[0]) * (self.r[3] - self.r[1]))

    def Outline(self, i):
        return self._O(self.rects[i])


class TestPlanPrincipal:
    def test_un_point_dans_le_plus_grand_contour_est_prefere(self):
        grand = (0, 0, 100 * MM, 100 * MM)
        ilot = (150 * MM, 150 * MM, 151 * MM, 151 * MM)
        polys = [_Poly([ilot, grand])]
        assert runner._dans_le_plan_principal(polys, 50 * MM, 50 * MM, lambda x, y: (x, y))
        assert not runner._dans_le_plan_principal(polys, 150.5 * MM, 150.5 * MM, lambda x, y: (x, y))

    def test_sans_cuivre_en_face_rien_n_est_prefere(self):
        assert not runner._dans_le_plan_principal([], 0, 0, lambda x, y: (x, y))


class TestCablage:
    SRC_RUNNER = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")
    SRC_ROUTER = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_fanout_transmet_la_preference(self):
        assert "prefere=prefere" in self.SRC_RUNNER

    def test_le_fanout_repasse_apres_le_retrait_des_ilots(self):
        i = self.SRC_ROUTER.index("final = _retirer_ilots_flottants(final)")
        suite = self.SRC_ROUTER[i:i + 600]
        assert "_fanout_pads_isolees(final)" in suite

    def test_le_fanout_lit_les_orphelines_avec_le_board(self):
        i = self.SRC_ROUTER.index("def _fanout_pads_isolees(")
        corps = self.SRC_ROUTER[i:i + 3000]
        assert "_pads_isolees_du_plan(rapport, pcb_bytes)" in corps

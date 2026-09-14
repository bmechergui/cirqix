"""La piste d echappement ne vit que sur la couche de sa pastille ; seul le VIA
traverse. Un obstacle sur une AUTRE couche ne peut donc bloquer que le point de
chute, jamais le trajet.

Mesure du 2026-09-14, carte-10 (placement du verdict par broches), broche
U1.8 (GND, F.Cu) : un via GND existait a 1,2 mm, le couloir sur F.Cu etait
libre, et le fanout RENONCAIT (« aucune sortie degagee ») parce qu une piste
IO_L14 sur B.Cu, sous la pastille, comptait comme obstacle du trajet. Les
obstacles etaient pris sur TOUTES les couches. La carte sortait a 98 % avec
une broche de masse orpheline, tirage apres tirage, palier apres palier — de
2 a 8 couches, puisque l escalade ne change rien a une piste qui n existe pas.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


def _mur_vertical(x: float, y0: float, y1: float, largeur: float = 0.2 * MM):
    """Une piste verticale en x, de y0 a y1 — la forme SEGMENT des obstacles."""
    return ("segment", float(x), float(y0), float(x), float(y1), float(largeur))


class TestTrajetEtViaOntChacunLeursObstacles:
    def test_un_obstacle_d_une_autre_couche_sur_le_trajet_ne_bloque_pas(self):
        # Piste sur B.Cu qui traverse le couloir a 0,6 mm : elle n est PAS sur la
        # couche du trajet. Le via, au bout (1,2 mm), est degage sur toutes les couches.
        sous_la_pastille = _mur_vertical(0.6 * MM, -2 * MM, 2 * MM)
        sortie = runner._choisir_sortie(
            0, 0, 1.0, 0.0, 1.2 * MM, obstacles=[], marge=0.5 * MM,
            marge_piste=0.325 * MM, obstacles_via=[sous_la_pastille])
        assert sortie == (int(1.2 * MM), 0)

    def test_le_meme_obstacle_sur_la_couche_du_trajet_bloque(self):
        # Meme mur, cette fois sur la couche de la piste : le trajet est coupe et
        # la recherche doit s ecarter (ou renoncer) — jamais le traverser.
        mur = _mur_vertical(0.6 * MM, -2 * MM, 2 * MM)
        sortie = runner._choisir_sortie(
            0, 0, 1.0, 0.0, 1.2 * MM, obstacles=[mur], marge=0.5 * MM,
            marge_piste=0.325 * MM, obstacles_via=[mur], portee=1.2 * MM, pas=0.3 * MM)
        assert sortie != (int(1.2 * MM), 0)

    def test_le_via_reste_juge_sur_toutes_les_couches(self):
        # Un obstacle d une autre couche AU POINT DE CHUTE bloque le via : il
        # traverse, lui. Le trajet est libre, la sortie doit s en ecarter.
        au_bout = _mur_vertical(1.2 * MM, -2 * MM, 2 * MM)
        sortie = runner._choisir_sortie(
            0, 0, 1.0, 0.0, 1.2 * MM, obstacles=[], marge=0.5 * MM,
            marge_piste=0.325 * MM, obstacles_via=[au_bout], portee=1.2 * MM, pas=0.3 * MM)
        assert sortie != (int(1.2 * MM), 0)

    def test_sans_obstacles_via_le_comportement_historique_est_conserve(self):
        mur = _mur_vertical(0.6 * MM, -2 * MM, 2 * MM)
        assert runner._choisir_sortie(0, 0, 1.0, 0.0, 1.2 * MM, [mur], marge=0.5 * MM,
                                      portee=1.2 * MM, pas=0.3 * MM) != (int(1.2 * MM), 0)

    def test_la_sortie_reservee_suit_la_meme_regle(self):
        sous_la_pastille = _mur_vertical(0.6 * MM, -2 * MM, 2 * MM)
        assert runner._sortie_reservee_valide(
            0, 0, 1.2 * MM, 0, obstacles=[], marge=0.5 * MM, marge_piste=0.325 * MM,
            obstacles_via=[sous_la_pastille])
        assert not runner._sortie_reservee_valide(
            0, 0, 1.2 * MM, 0, obstacles=[sous_la_pastille], marge=0.5 * MM,
            marge_piste=0.325 * MM, obstacles_via=[])


class TestCablage:
    """Une regle juste mais jamais appelee est indistinguable d une regle absente."""

    @staticmethod
    def _corps(fonction) -> str:
        return inspect.getsource(fonction)

    def test_le_fanout_prend_les_obstacles_du_trajet_sur_la_couche_de_la_pastille(self):
        corps = self._corps(runner._escape_pads)
        assert "couches={pad.GetLayer()}" in corps or "couches=_couches_cuivre_d_un_item(pad)" in corps
        assert "obstacles_via=" in corps

    def test_la_reservation_d_avant_routage_suit_la_meme_regle(self):
        corps = self._corps(runner._plan_escape)
        assert "couches={pad.GetLayer()}" in corps or "couches=_couches_cuivre_d_un_item(pad)" in corps
        assert "obstacles_via=" in corps
